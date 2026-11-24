"""Repository safety regression tests for the patch pipeline.

The pipeline used to undo itself with ``git reset --hard`` + ``git clean -fd``,
which destroys unrelated tracked modifications and untracked files belonging to
whoever owns the checkout. These tests pin the replacement: a transaction that
restores only what it wrote, removes only what it created, and reports a
conflict instead of overwriting anything changed underneath it.

Every fixture is a disposable git repository under pytest's ``tmp_path``. No
test touches a real connected repository.
"""
from pathlib import Path
import subprocess

import pytest

from app.models.generated_patch import GeneratedSeoPatch
from app.repo_agent.file_transaction import FileTransaction, TransactionError
from app.repo_agent.project_structure import detect_structure
from app.repo_agent.scanner import content_hash, read_repo_text
from app.services.patch_pipeline import PatchPipelineService


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def git(root: Path, *args: str):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A disposable git repo shaped like a Next.js src/app project, with a
    committed baseline plus the kind of mess a real checkout carries."""
    root = tmp_path / "site"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@test.local")
    git(root, "config", "user.name", "T")
    write(root / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(root / "tsconfig.json", "{}")
    write(root / "src" / "app" / "layout.tsx", "export default function L(){return null}\n")
    write(root / "src" / "app" / "page.tsx", "export default function P(){return null}\n")
    write(root / "src" / "app" / "sitemap.ts", "// the real sitemap\nexport default function s(){return []}\n")
    write(root / "tracked.txt", "committed\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


@pytest.fixture
def backups(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    return d


def dirty(root: Path):
    """Add the three kinds of pre-existing user work a rollback must preserve."""
    write(root / "tracked.txt", "USER EDIT\n")               # modified tracked
    write(root / "user_untracked.txt", "USER UNTRACKED\n")   # untracked
    write(root / "staged.txt", "USER STAGED\n")              # staged
    git(root, "add", "staged.txt")


def service():
    """The service without a DB session — only the pure apply helpers are used."""
    from app.repo_agent.architecture import RepoArchitectureDetector

    svc = PatchPipelineService.__new__(PatchPipelineService)
    svc.safety = RepoArchitectureDetector()
    return svc


def patch_row(target_file, code, *, is_new_file, original_content_hash=None):
    row = GeneratedSeoPatch(
        target_file=target_file, generated_code=code, is_new_file=is_new_file,
        surface="sitemap", patch_type="sitemap_update", framework="nextjs",
        language="typescript",
    )
    if original_content_hash is not None:
        row.original_content_hash = original_content_hash
    return row


# -- 1-3. pre-existing user work survives rollback ----------------------------

def test_preexisting_modified_tracked_file_survives_rollback(repo, backups):
    dirty(repo)
    tx = FileTransaction(repo, "run1", backup_root=backups)
    assert tx.write("src/app/robots.ts", "export default function r(){return {}}\n",
                    expect_new=True)[0]
    tx.rollback()
    assert (repo / "tracked.txt").read_text() == "USER EDIT\n"


def test_preexisting_untracked_file_survives_rollback(repo, backups):
    dirty(repo)
    tx = FileTransaction(repo, "run1", backup_root=backups)
    tx.write("src/app/robots.ts", "x\n", expect_new=True)
    tx.rollback()
    assert (repo / "user_untracked.txt").read_text() == "USER UNTRACKED\n"


def test_preexisting_staged_changes_survive_rollback(repo, backups):
    dirty(repo)
    staged_before = git(repo, "diff", "--cached", "--name-only").stdout
    tx = FileTransaction(repo, "run1", backup_root=backups)
    tx.write("src/app/robots.ts", "x\n", expect_new=True)
    tx.rollback()
    assert (repo / "staged.txt").read_text() == "USER STAGED\n"
    assert git(repo, "diff", "--cached", "--name-only").stdout == staged_before
    assert "staged.txt" in staged_before


# -- 4-6. the run's own changes are undone ------------------------------------

def test_created_file_is_removed_by_its_own_rollback(repo, backups):
    tx = FileTransaction(repo, "run1", backup_root=backups)
    tx.write("src/app/robots.ts", "x\n", expect_new=True)
    assert (repo / "src/app/robots.ts").exists()
    report = tx.rollback()
    assert not (repo / "src/app/robots.ts").exists()
    assert "src/app/robots.ts" in report.removed and report.clean


def test_modified_file_is_restored_byte_for_byte(repo, backups):
    original = (repo / "src/app/sitemap.ts").read_bytes()
    tx = FileTransaction(repo, "run1", backup_root=backups)
    ok, detail = tx.write("src/app/sitemap.ts", "REPLACED\n", expect_new=False)
    assert ok, detail
    assert (repo / "src/app/sitemap.ts").read_text() == "REPLACED\n"
    report = tx.rollback()
    assert (repo / "src/app/sitemap.ts").read_bytes() == original
    assert report.restored == ["src/app/sitemap.ts"] and report.clean


def test_partial_failure_rolls_back_only_this_run(repo, backups):
    dirty(repo)
    tx = FileTransaction(repo, "run1", backup_root=backups)
    assert tx.write("src/app/robots.ts", "new\n", expect_new=True)[0]
    assert tx.write("src/app/sitemap.ts", "changed\n", expect_new=False)[0]
    # a third write fails and must not be recorded
    ok, _ = tx.write("src/app/page.tsx", "x\n", expect_new=True)   # already exists
    assert not ok
    tx.rollback()
    assert not (repo / "src/app/robots.ts").exists()
    assert "the real sitemap" in (repo / "src/app/sitemap.ts").read_text()
    assert (repo / "src/app/page.tsx").read_text() == "export default function P(){return null}\n"
    assert (repo / "tracked.txt").read_text() == "USER EDIT\n"
    assert (repo / "user_untracked.txt").exists()


# -- 7. conflicts are detected, never overwritten -----------------------------

def test_rollback_detects_independent_change_to_a_modified_file(repo, backups):
    tx = FileTransaction(repo, "run1", backup_root=backups)
    tx.write("src/app/sitemap.ts", "pipeline wrote this\n", expect_new=False)
    # someone else edits it afterwards
    write(repo / "src" / "app" / "sitemap.ts", "SOMEONE ELSE\n")
    report = tx.rollback()
    assert (repo / "src/app/sitemap.ts").read_text() == "SOMEONE ELSE\n"
    assert not report.clean
    assert report.conflicts[0]["path"] == "src/app/sitemap.ts"
    assert "changed after this run" in report.conflicts[0]["reason"]


def test_rollback_detects_independent_change_to_a_created_file(repo, backups):
    tx = FileTransaction(repo, "run1", backup_root=backups)
    tx.write("src/app/robots.ts", "pipeline\n", expect_new=True)
    write(repo / "src" / "app" / "robots.ts", "USER TOOK IT OVER\n")
    report = tx.rollback()
    assert (repo / "src/app/robots.ts").read_text() == "USER TOOK IT OVER\n"
    assert not report.clean and report.conflicts


# -- 8-11. apply-time file safety ---------------------------------------------

def test_new_file_patch_refused_when_target_exists(repo, backups):
    tx = FileTransaction(repo, "run1", backup_root=backups)
    ok, detail = tx.write("src/app/sitemap.ts", "template\n", expect_new=True)
    assert not ok and "target_exists" in detail
    assert "the real sitemap" in (repo / "src/app/sitemap.ts").read_text()
    assert tx.changes == []


def test_existing_file_patch_refused_on_hash_mismatch(repo, backups):
    tx = FileTransaction(repo, "run1", backup_root=backups)
    ok, detail = tx.write("src/app/sitemap.ts", "x\n", expect_new=False,
                          expected_original_hash="0" * 64)
    assert not ok and "original_changed" in detail
    assert "the real sitemap" in (repo / "src/app/sitemap.ts").read_text()


def test_existing_file_patch_accepted_on_matching_hash(repo, backups):
    current = content_hash(read_repo_text(repo / "src" / "app" / "sitemap.ts"))
    tx = FileTransaction(repo, "run1", backup_root=backups)
    ok, detail = tx.write("src/app/sitemap.ts", "x\n", expect_new=False,
                          expected_original_hash=current)
    assert ok, detail


def test_new_file_refused_if_target_appears_before_application(repo, backups):
    """Prepared as a creation; the file shows up in between."""
    tx = FileTransaction(repo, "run1", backup_root=backups)
    write(repo / "src" / "app" / "robots.ts", "appeared\n")
    ok, detail = tx.write("src/app/robots.ts", "template\n", expect_new=True)
    assert not ok and "target_exists" in detail
    assert (repo / "src/app/robots.ts").read_text() == "appeared\n"


def test_update_patch_refused_when_target_missing(repo, backups):
    tx = FileTransaction(repo, "run1", backup_root=backups)
    ok, detail = tx.write("src/app/nope.ts", "x\n", expect_new=False)
    assert not ok and "target_missing" in detail


@pytest.mark.parametrize("evil", ["../escape.ts", "src/../../escape.ts", "a/../../b.ts"])
def test_path_traversal_is_refused(repo, backups, evil):
    tx = FileTransaction(repo, "run1", backup_root=backups)
    ok, detail = tx.write(evil, "x\n", expect_new=True)
    assert not ok and "unsafe_path" in detail
    assert not (repo.parent / "escape.ts").exists()


def test_write_fails_closed_when_backup_cannot_be_stored(repo, tmp_path):
    """No undo material, no write."""
    blocked = tmp_path / "blocked"
    blocked.write_text("I am a file, not a directory")
    tx = FileTransaction(repo, "run1", backup_root=blocked)
    ok, detail = tx.write("src/app/sitemap.ts", "x\n", expect_new=False)
    assert not ok and "backup_failed" in detail
    assert "the real sitemap" in (repo / "src/app/sitemap.ts").read_text()


# -- 12. stale historical patches ---------------------------------------------

def test_stale_template_path_patch_is_rejected_at_apply_time(repo, backups):
    """A record stored before path resolution existed must not be applied on its
    original assumptions."""
    svc = service()
    structure = detect_structure(str(repo))
    tx = FileTransaction(repo, "run1", backup_root=backups)
    # The historical row: unmapped template path, claims to create a new file.
    row = patch_row("app/sitemap.ts", "template\n", is_new_file=True)
    ok, rel, detail = svc._apply_one(repo, row, tx, structure)
    assert not ok
    # It resolves onto the real sitemap, which exists, so creation is refused.
    assert rel == "src/app/sitemap.ts"
    assert "target_exists" in detail
    assert "the real sitemap" in (repo / "src/app/sitemap.ts").read_text()


def test_apply_one_rejects_a_shadow_root_target(repo, backups):
    svc = service()
    structure = detect_structure(str(repo))
    tx = FileTransaction(repo, "run1", backup_root=backups)
    row = patch_row("app/robots.ts", "x\n", is_new_file=True)
    ok, rel, detail = svc._apply_one(repo, row, tx, structure)
    # Mapped onto src/app, which does not exist yet there -> allowed to create.
    assert ok, detail
    assert rel == "src/app/robots.ts"
    assert not (repo / "app").exists(), "must never create a parallel app/ root"


def test_apply_one_creates_under_the_real_root(repo, backups):
    svc = service()
    structure = detect_structure(str(repo))
    tx = FileTransaction(repo, "run1", backup_root=backups)
    row = patch_row("app/robots.ts", "export default function r(){return {}}\n", is_new_file=True)
    ok, rel, _ = svc._apply_one(repo, row, tx, structure)
    assert ok and (repo / "src" / "app" / "robots.ts").is_file()
    tx.rollback()
    assert not (repo / "src" / "app" / "robots.ts").exists()


# -- 13-14. no destructive git cleanup ----------------------------------------

def test_rollback_runs_no_git_command(repo, backups, monkeypatch):
    """The whole point: undoing a run must not touch git at all."""
    import app.repo_agent.file_transaction as ft

    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
        AssertionError("rollback must not shell out")))
    tx = FileTransaction(repo, "run1", backup_root=backups)
    tx.write("src/app/robots.ts", "x\n", expect_new=True)
    tx.rollback()
    assert called == []


def test_pipeline_source_contains_no_destructive_git_commands():
    """Guards against the old implementation creeping back."""
    source = Path(__file__).resolve().parents[1] / "app" / "services" / "patch_pipeline.py"
    text = source.read_text(encoding="utf-8")
    # strip the docstring that explains what was removed
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    for forbidden in ('"reset"', "'reset'", '"clean"', "'clean'", '"-fd"', "'-fd'"):
        assert forbidden not in code, f"{forbidden} reappeared in patch_pipeline.py"


def test_failed_commit_path_preserves_unrelated_content(repo, backups):
    """Simulates the commit-failure branch: undo only ours, keep the rest."""
    dirty(repo)
    tx = FileTransaction(repo, "run1", backup_root=backups)
    tx.write("src/app/robots.ts", "new\n", expect_new=True)
    tx.write("src/app/sitemap.ts", "changed\n", expect_new=False)
    report = tx.rollback()
    assert report.clean
    assert (repo / "tracked.txt").read_text() == "USER EDIT\n"
    assert (repo / "user_untracked.txt").read_text() == "USER UNTRACKED\n"
    assert (repo / "staged.txt").read_text() == "USER STAGED\n"
    assert "the real sitemap" in (repo / "src/app/sitemap.ts").read_text()
    assert not (repo / "src/app/robots.ts").exists()
    # the committed baseline is untouched too
    assert git(repo, "log", "--oneline").stdout.count("\n") == 1


# -- commit is pathspec-limited ----------------------------------------------

def test_commit_only_touches_given_paths(repo):
    """A bare `git commit` would sweep up the owner's staged work."""
    from app.repo_agent.git_ops import GitCommandRunner

    dirty(repo)
    write(repo / "src" / "app" / "robots.ts", "ours\n")
    runner = GitCommandRunner()
    runner.add(repo, ["src/app/robots.ts"])
    result = runner.commit(repo, "ours only", author_name="T", author_email="t@test.local",
                           paths=["src/app/robots.ts"])
    assert result.returncode == 0, result.output
    committed = git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert "src/app/robots.ts" in committed
    assert "staged.txt" not in committed
    # the owner's staged file is still staged, still uncommitted
    assert "staged.txt" in git(repo, "diff", "--cached", "--name-only").stdout

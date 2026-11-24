"""Patch pipeline tests: framework-aware apply, safety, real-git rollback, stages.

These exercise the pipeline's file-level operations with a REAL temporary git
repository (no Docker, no DB), so the apply/rollback behaviour is genuinely
verified, not mocked."""
import subprocess
from pathlib import Path
from types import SimpleNamespace as S

import pytest

from app.models.patch_pipeline import PIPELINE_STAGES, PatchPipeline, PatchPipelineStatus
from app.services.patch_pipeline import PatchPipelineService


def _svc():
    # Non-DB methods only; the service never touches self.db in these paths.
    return PatchPipelineService(db=None)  # type: ignore[arg-type]


def _patch(target, code="export default function robots(){return {}}", is_new=True):
    return S(target_file=target, generated_code=code, is_new_file=is_new)


def _tx(root, tmp_path, name="run"):
    """Writes now go through a FileTransaction, which owns the undo material."""
    from app.repo_agent.file_transaction import FileTransaction

    return FileTransaction(root, name, backup_root=Path(tmp_path) / f"backups-{name}")


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.io"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    # normalise base branch name
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, capture_output=True, check=True)
    return tmp_path


def test_resolve_target_maps_app_to_src_app(tmp_path):
    (tmp_path / "src" / "app").mkdir(parents=True)
    resolved = PatchPipelineService._resolve_target(tmp_path, "app/robots.ts")
    assert resolved == "src/app/robots.ts"


def test_resolve_target_keeps_app_when_present(tmp_path):
    (tmp_path / "app").mkdir()
    assert PatchPipelineService._resolve_target(tmp_path, "app/sitemap.ts") == "app/sitemap.ts"


def test_apply_one_writes_seo_file(tmp_path):
    svc = _svc()
    root = tmp_path / "repo"
    root.mkdir()
    ok, rel, detail = svc._apply_one(root, _patch("app/robots.ts"), _tx(root, tmp_path))
    assert ok and rel == "app/robots.ts", detail
    assert (root / "app" / "robots.ts").read_text().startswith("export default")


@pytest.mark.parametrize("bad", [
    "src/components/Navbar.tsx",   # UI component
    "app/checkout/page.tsx",        # business/payments
    "src/auth/login.tsx",           # authentication
    "app/api/users/route.ts",       # API behaviour
    "prisma/schema.prisma",         # database
])
def test_apply_one_refuses_protected_targets(tmp_path, bad):
    svc = _svc()
    root = tmp_path / "repo"
    root.mkdir()
    ok, rel, detail = svc._apply_one(root, _patch(bad, code="x"), _tx(root, tmp_path))
    assert not ok and "protected" in detail.lower()
    assert not (root / bad).exists()


def test_apply_one_allows_seo_component_files(tmp_path):
    # Our own generators target these — they must NOT be blocked by the UI guard.
    svc = _svc()
    root = tmp_path / "repo"
    root.mkdir()
    for good in ("app/components/JsonLd.tsx", "src/components/Seo.tsx"):
        ok, rel, detail = svc._apply_one(
            root, _patch(good, code="export default ()=>null"), _tx(root, tmp_path, good)
        )
        assert ok, f"{good} should be allowed ({detail})"


def test_real_git_rollback_removes_only_this_runs_files(tmp_path):
    """Rollback is transaction-scoped now.

    It used to run `git reset --hard` + `git clean -fd` + `git checkout <base>`,
    which also destroyed unrelated modified and untracked files. The contract is
    now narrower and safer: this run's own writes are undone, everything else —
    including the branch HEAD — is left exactly as it was.
    """
    root = _init_repo(tmp_path)
    svc = _svc()
    svc.git.checkout_branch(root, "seo-agent/test")
    # unrelated user work that the old rollback would have destroyed
    (root / "README.md").write_text("USER EDIT\n", encoding="utf-8")
    (root / "scratch.txt").write_text("USER UNTRACKED\n", encoding="utf-8")

    tx = _tx(root, tmp_path)
    ok, rel, _ = svc._apply_one(root, _patch("app/robots.ts"), tx)
    assert ok and (root / "app" / "robots.ts").exists()

    report = tx.rollback()
    assert report.clean
    assert not (root / "app" / "robots.ts").exists()
    # unrelated work survives
    assert (root / "README.md").read_text() == "USER EDIT\n"
    assert (root / "scratch.txt").read_text() == "USER UNTRACKED\n"
    # and we did NOT move off the working branch
    current = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
                             capture_output=True, text=True)
    assert current.stdout.strip() == "seo-agent/test"


def test_real_git_apply_commit_produces_sha(tmp_path):
    root = _init_repo(tmp_path)
    svc = _svc()
    svc.git.checkout_branch(root, "seo-agent/commit-test")
    ok, rel, _ = svc._apply_one(
        root, _patch("app/sitemap.ts", code="export default ()=>[]"), _tx(root, tmp_path)
    )
    assert ok
    svc.git.add(root, [rel])
    commit = svc.git.commit(root, "SEO Agent: test", paths=[rel])
    assert commit.returncode == 0
    assert svc.git.commit_sha(root)


def test_stage_helper_records_status_and_timestamps():
    svc = _svc()
    p = PatchPipeline(stages=[{"name": s, "status": "pending", "started_at": None, "finished_at": None, "detail": None}
                             for s in PIPELINE_STAGES])
    svc._stage(p, "apply", "succeeded", "applied 3 files")
    apply_stage = next(s for s in p.stages if s["name"] == "apply")
    assert apply_stage["status"] == "succeeded"
    assert apply_stage["started_at"] and apply_stage["finished_at"]
    assert p.current_stage == "apply"

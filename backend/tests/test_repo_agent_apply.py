from datetime import datetime
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.repo_agent import (
    PatchApplyResultStatus,
    PatchApplyRunStatus,
    PatchValidationStatus,
    PullRequestStatus,
    RepoProvider,
    RepoScanRunStatus,
    SeoCodePatchRisk,
    SeoCodePatchStatus,
    SeoCodePatchType,
)
from app.repo_agent.git_ops import CommandResult, PullRequestCreateResult, ValidationResult
from app.repo_agent.scanner import (
    PathSafetyError,
    content_hash,
    detect_newline_style,
    read_repo_text,
    write_repo_text,
)
from app.services.repo_agent import RepoAgentService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


class FakeGitRunner:
    def __init__(self):
        self.branches = []
        self.added = []
        self.commits = []
        self.commit_identity = []
        self.pushed = []
        self.push_auth = []

    def ensure_repo(self, root: Path):
        assert root.exists()

    def checkout_branch(self, root: Path, branch_name: str):
        self.branches.append(branch_name)

    def add(self, root: Path, file_paths):
        self.added.extend(file_paths)

    def commit(self, root: Path, message: str, **identity):
        # Records the authorship the service supplies, so a test can assert the
        # commit identity without a real git repository.
        self.commits.append(message)
        self.commit_identity.append(identity)
        return CommandResult(0, "committed", "")

    def commit_sha(self, root: Path):
        return "abc123"

    def push_branch(self, root: Path, branch_name: str, **auth):
        # Records how the push was authenticated so a test can assert the
        # credential was supplied without a real push ever happening.
        self.pushed.append(branch_name)
        self.push_auth.append(auth)
        return CommandResult(0, "pushed", "")

    def diff_summary(self, root: Path):
        return " app/page.tsx | 2 +"

    def run(self, root: Path, args, **kwargs):
        if args[:3] == ["diff", "--cached", "--stat"]:
            return CommandResult(0, " app/page.tsx | 2 +", "")
        return CommandResult(0, "", "")


class FakeValidationRunner:
    def __init__(self, passed=True):
        self.passed = passed
        self.commands = []

    def parse_commands(self, raw_commands: str):
        return [part.strip() for part in raw_commands.split(",") if part.strip()]

    def run(self, root: Path, commands):
        self.commands.extend(commands)
        return ValidationResult(self.passed, "validation ok" if self.passed else "validation failed")


class FakeGitHubClient:
    async def create_draft_pr(self, **kwargs):
        return PullRequestCreateResult(number=42, url="https://github.com/acme/site/pull/42", state="open")


class FakeRepoAgentRepository:
    def __init__(self, tenant_id, project_id, root, patches):
        now = datetime.utcnow()
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.connection = SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            provider=RepoProvider.local,
            repo_url="https://github.com/acme/site.git",
            local_path=str(root),
            default_branch="main",
            framework="nextjs_app_router",
        )
        self.run = SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            repo_connection_id=self.connection.id,
            status=RepoScanRunStatus.completed,
            created_at=now,
            updated_at=now,
        )
        self.patches = patches
        self.apply_runs = []
        self.results = []
        self.pull_requests = []

    async def get_scan_run(self, scan_id, tenant_id=None):
        return self.run if self.run.id == scan_id else None

    async def get_connection(self, connection_id, tenant_id=None):
        return self.connection if self.connection.id == connection_id else None

    async def list_patches(self, scan_id, tenant_id, status=None, limit=500, offset=0):
        items = [patch for patch in self.patches if patch.scan_run_id == scan_id and (not status or patch.status == status)]
        return items[offset : offset + limit]

    async def get_patch(self, patch_id, tenant_id):
        return next((patch for patch in self.patches if patch.id == patch_id), None)

    async def set_patch_status(self, patch, status):
        patch.status = status
        patch.updated_at = datetime.utcnow()
        return patch

    async def create_apply_run(self, run, branch_name, patches_requested):
        now = datetime.utcnow()
        apply_run = SimpleNamespace(
            id=uuid4(),
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            repo_connection_id=run.repo_connection_id,
            scan_run_id=run.id,
            branch_name=branch_name,
            status=PatchApplyRunStatus.queued,
            patches_requested=patches_requested,
            patches_applied=0,
            patches_failed=0,
            validation_status=PatchValidationStatus.not_run,
            validation_output=None,
            git_diff_summary=None,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.apply_runs.append(apply_run)
        return apply_run

    async def get_apply_run(self, apply_run_id, tenant_id=None):
        return next((run for run in self.apply_runs if run.id == apply_run_id), None)

    async def set_apply_run_status(self, apply_run, status, error_message=None):
        apply_run.status = status
        apply_run.error_message = error_message
        return apply_run

    async def finish_apply_run(self, apply_run, **kwargs):
        for key, value in kwargs.items():
            setattr(apply_run, key, value)
        return apply_run

    async def add_apply_results(self, records):
        created = [SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), **record) for record in records]
        self.results.extend(created)
        return created

    async def list_apply_results(self, apply_run_id, tenant_id, limit=500, offset=0):
        items = [result for result in self.results if result.apply_run_id == apply_run_id]
        return items[offset : offset + limit]

    async def set_apply_result_status(self, result, status, reason=None):
        result.status = status
        if reason:
            result.reason = reason
        return result

    async def create_pull_request_record(self, **kwargs):
        now = datetime.utcnow()
        record = SimpleNamespace(
            id=uuid4(),
            provider="github",
            created_at=now,
            updated_at=now,
            **kwargs,
        )
        self.pull_requests.append(record)
        return record

    async def get_pull_request(self, pr_id, tenant_id):
        return next((record for record in self.pull_requests if record.id == pr_id), None)


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_patch(run, tenant_id, project_id, connection_id, file_path, original, proposed, *, status, risk=SeoCodePatchRisk.low):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        scan_run_id=run.id,
        issue_id=uuid4(),
        file_path=file_path,
        patch_type=SeoCodePatchType.metadata_update,
        original_content_hash=content_hash(original),
        diff_text="diff",
        proposed_content=proposed,
        explanation="SEO metadata patch.",
        risk_level=risk,
        status=status,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture(autouse=True)
def _isolated_backup_root(tmp_path, monkeypatch):
    """Point the backup root at this test's own tmp_path.

    The configured default is an absolute container path on a named volume, and
    the suite must not write there.
    """
    monkeypatch.setattr(settings, "REPO_AGENT_BACKUP_ROOT", str(tmp_path / "agent-backups"))


def make_service(tmp_path, patch_specs, validation_passed=True):
    tenant_id = uuid4()
    project_id = uuid4()
    write(tmp_path / "app" / "page.tsx", "original")
    repository = FakeRepoAgentRepository(tenant_id, project_id, tmp_path, [])
    patches = []
    for spec in patch_specs:
        file_path, original, proposed, status, *rest = spec
        risk = rest[0] if rest else SeoCodePatchRisk.low
        patches.append(
            make_patch(
                repository.run,
                tenant_id,
                project_id,
                repository.connection.id,
                file_path,
                original,
                proposed,
                status=status,
                risk=risk,
            )
        )
    repository.patches = patches
    service = RepoAgentService(
        FakeDB(),
        git_runner=FakeGitRunner(),
        validation_runner=FakeValidationRunner(validation_passed),
        github_client=FakeGitHubClient(),
    )
    service.repository = repository
    return service, repository, tenant_id


@pytest.mark.asyncio
async def test_apply_approved_patch_creates_branch_backup_commit_and_result(tmp_path):
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )

    apply_run = await service.apply_approved_patches(
        repository.run.id,
        tenant_id,
        run_validation=True,
        validation_commands=["npm run typecheck"],
    )

    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "patched"
    assert apply_run.status == PatchApplyRunStatus.completed
    assert apply_run.patches_applied == 1
    assert repository.results[0].status == PatchApplyResultStatus.applied
    assert Path(repository.results[0].backup_path).exists()
    assert service.git_runner.branches[0].startswith("seo-agent/")
    assert service.git_runner.commits == ["SEO Agent: apply approved SEO fixes"]
    assert apply_run.validation_status == PatchValidationStatus.passed
    assert service.validation_runner.commands == ["npm run typecheck"]
    assert repository.patches[0].status == SeoCodePatchStatus.applied


@pytest.mark.asyncio
async def test_rejected_and_unapproved_patches_are_skipped(tmp_path):
    service, repository, tenant_id = make_service(
        tmp_path,
        [
            ("app/page.tsx", "original", "rejected", SeoCodePatchStatus.rejected),
            ("app/page.tsx", "original", "proposed", SeoCodePatchStatus.proposed),
        ],
    )

    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "original"
    assert apply_run.patches_applied == 0
    assert {result.status for result in repository.results} == {PatchApplyResultStatus.skipped}
    assert not service.git_runner.commits


@pytest.mark.asyncio
async def test_high_risk_patch_requires_explicit_flag(tmp_path):
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "risky", SeoCodePatchStatus.approved, SeoCodePatchRisk.high)],
    )

    first_run = await service.apply_approved_patches(repository.run.id, tenant_id)
    assert first_run.patches_applied == 0
    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "original"

    second_run = await service.apply_approved_patches(repository.run.id, tenant_id, allow_high_risk=True)
    assert second_run.patches_applied == 1
    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "risky"


@pytest.mark.asyncio
async def test_hash_mismatch_and_path_traversal_do_not_write(tmp_path):
    service, repository, tenant_id = make_service(
        tmp_path,
        [
            ("app/page.tsx", "stale-base", "bad", SeoCodePatchStatus.approved),
            ("../evil.ts", "", "bad", SeoCodePatchStatus.approved),
        ],
    )

    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    assert apply_run.patches_applied == 0
    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "original"
    assert not (tmp_path.parent / "evil.ts").exists()
    assert any("Hash mismatch" in result.reason for result in repository.results)
    assert any(result.status == PatchApplyResultStatus.failed for result in repository.results)


@pytest.mark.asyncio
async def test_validation_failure_is_recorded_but_commit_is_kept(tmp_path):
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
        validation_passed=False,
    )

    apply_run = await service.apply_approved_patches(
        repository.run.id,
        tenant_id,
        run_validation=True,
        validation_commands=["npm run lint"],
    )

    assert apply_run.validation_status == PatchValidationStatus.failed
    assert "validation failed" in apply_run.validation_output
    assert service.git_runner.commits == ["SEO Agent: apply approved SEO fixes"]


@pytest.mark.asyncio
async def test_github_pr_creation_and_missing_token_skip(tmp_path, monkeypatch):
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)
    skipped = await service.create_pull_request(apply_run.id, tenant_id)
    assert skipped.status == PullRequestStatus.failed
    assert "GITHUB_TOKEN" in skipped.error_message

    monkeypatch.setattr(settings, "GITHUB_TOKEN", "mock-token")
    created = await service.create_pull_request(apply_run.id, tenant_id)
    assert created.status == PullRequestStatus.draft
    assert created.pr_url == "https://github.com/acme/site/pull/42"
    assert "Applied patches: 1" in created.description
    assert service.git_runner.pushed == [apply_run.branch_name]


@pytest.mark.asyncio
async def test_rollback_restores_backup_and_patch_status(tmp_path):
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    rolled_back = await service.rollback_apply_run(apply_run.id, tenant_id)

    assert rolled_back.status == PatchApplyRunStatus.rolled_back
    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "original"
    assert repository.results[0].status == PatchApplyResultStatus.rolled_back
    assert repository.patches[0].status == SeoCodePatchStatus.approved


@pytest.mark.asyncio
async def test_pull_request_push_is_authenticated_from_settings(tmp_path, monkeypatch):
    """The service hands the configured credential to the push, not to argv."""
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    monkeypatch.setattr(settings, "GITHUB_TOKEN", "mock-token")
    monkeypatch.setattr(settings, "GITHUB_TOKEN_USERNAME", "x-access-token")
    record = await service.create_pull_request(apply_run.id, tenant_id)

    assert service.git_runner.pushed == [apply_run.branch_name]
    assert service.git_runner.push_auth == [
        {"token": "mock-token", "username": "x-access-token"}
    ]
    # The credential is never written into anything the PR record carries.
    for field in (record.branch_name, record.base_branch, record.title, record.description):
        assert "mock-token" not in (field or "")
    assert "mock-token" not in (getattr(record, "error_message", None) or "")


@pytest.mark.asyncio
async def test_apply_run_commits_under_the_agents_configured_identity(tmp_path, monkeypatch):
    """A container has no git identity, so the service must supply one."""
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    monkeypatch.setattr(settings, "REPO_AGENT_COMMIT_NAME", "SEO Agent")
    monkeypatch.setattr(settings, "REPO_AGENT_COMMIT_EMAIL", "seo-agent@localhost")

    await service.apply_approved_patches(repository.run.id, tenant_id)

    assert service.git_runner.commits == ["SEO Agent: apply approved SEO fixes"]
    assert service.git_runner.commit_identity == [
        {"author_name": "SEO Agent", "author_email": "seo-agent@localhost"}
    ]


# ---------------------------------------------------------------------------
# Part 1: persistent, safely scoped backups
# ---------------------------------------------------------------------------


def test_backup_root_comes_from_settings_and_not_from_the_repository(tmp_path, monkeypatch):
    """Backups must never live inside, or beside, the checkout.

    The original location was `<repo>/../.seo-agent-backups`, which in a
    container is the writable layer - destroyed by a container recreate, taking
    the only copy of the rollback material with it.
    """
    service = RepoAgentService(FakeDB())
    backups = tmp_path / "persistent"
    monkeypatch.setattr(settings, "REPO_AGENT_BACKUP_ROOT", str(backups))

    repo = tmp_path / "checkout" / "site"
    repo.mkdir(parents=True)
    target_dir = service.backup_dir_for_run(repo, uuid4())

    assert service.backup_root() == backups
    assert backups in target_dir.parents
    assert repo not in target_dir.parents
    assert repo.parent not in target_dir.parents
    assert ".seo-agent-backups" not in str(target_dir)


def test_backup_directory_is_scoped_per_repository_and_per_run(tmp_path, monkeypatch):
    service = RepoAgentService(FakeDB())
    monkeypatch.setattr(settings, "REPO_AGENT_BACKUP_ROOT", str(tmp_path / "b"))

    # Two checkouts sharing a basename must not collide.
    first = tmp_path / "one" / "site"
    second = tmp_path / "two" / "site"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    run_id = uuid4()

    a = service.backup_dir_for_run(first, run_id)
    b = service.backup_dir_for_run(second, run_id)
    assert a != b
    assert a.name == b.name == str(run_id)
    assert a.parent.name.startswith("site-")
    assert b.parent.name.startswith("site-")

    assert service.backup_dir_for_run(first, run_id) == a
    assert service.backup_dir_for_run(first, uuid4()) != a


def test_backup_filename_rejects_traversal_and_flattens_safely():
    service = RepoAgentService(FakeDB())
    patch_id = uuid4()

    for unsafe in ("../secrets.env", "a/../../etc/passwd", "..", "/", "", "./x/../.."):
        with pytest.raises(PathSafetyError):
            service._backup_file_name(patch_id, unsafe)

    name = service._backup_file_name(patch_id, "src/app/company/page.tsx")
    assert name == f"{patch_id}-src__app__company__page.tsx"
    assert "/" not in name and "\\" not in name

    # Long paths are truncated with a digest, so they stay unique and stay
    # inside the filesystem's name limit.
    long_path = "/".join(["segment"] * 60) + "/page.tsx"
    long_name = service._backup_file_name(patch_id, long_path)
    assert len(long_name) < 200
    assert long_name != service._backup_file_name(patch_id, long_path + "x")


def test_backup_is_written_under_the_run_directory(tmp_path, monkeypatch):
    service = RepoAgentService(FakeDB())
    monkeypatch.setattr(settings, "REPO_AGENT_BACKUP_ROOT", str(tmp_path / "backups"))
    repo = tmp_path / "site"
    repo.mkdir()
    run_id, patch_id = uuid4(), uuid4()

    content = 'export const metadata = { title: "Original" };\n'
    path = service._write_backup(repo, run_id, patch_id, "src/app/page.tsx", content)

    assert path.is_file()
    assert path.parent == service.backup_dir_for_run(repo, run_id)
    assert path.read_text(encoding="utf-8") == content


def test_backup_survives_losing_everything_outside_the_backup_root(tmp_path, monkeypatch):
    """The persistence assumption, stated as a test.

    Deleting the repository and its parent - what losing a container does to
    anything stored beside the checkout - must leave the backup readable.
    """
    service = RepoAgentService(FakeDB())
    monkeypatch.setattr(settings, "REPO_AGENT_BACKUP_ROOT", str(tmp_path / "volume"))
    ephemeral = tmp_path / "ephemeral"
    repo = ephemeral / "site"
    repo.mkdir(parents=True)

    content = "original content\n"
    backup = service._write_backup(repo, uuid4(), uuid4(), "src/app/page.tsx", content)

    shutil.rmtree(ephemeral)
    assert not repo.exists()
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_a_patch_is_not_applied_when_its_backup_cannot_be_written(tmp_path, monkeypatch):
    """No backup, no patch - and the file is left exactly as it was."""
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )

    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(service, "_write_backup", refuse)
    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    assert apply_run.patches_applied == 0
    assert len(repository.results) == 1
    assert repository.results[0].status == PatchApplyResultStatus.failed
    assert "rollback backup" in repository.results[0].reason.lower()
    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "original"


# ---------------------------------------------------------------------------
# Part 2: rollback reports honestly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_with_a_failing_commit_is_not_reported_as_rolled_back(tmp_path):
    """A rollback whose commit fails must not look like a success.

    The files are back on disk but the branch does not say so, and the next
    decision would be taken believing the working tree is clean.
    """
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    def failing_commit(root, message, **identity):
        return CommandResult(128, "", "fatal: unable to auto-detect email address")

    service.git_runner.commit = failing_commit
    rolled_back = await service.rollback_apply_run(apply_run.id, tenant_id)

    assert rolled_back.status == PatchApplyRunStatus.failed
    assert "git commit failed during rollback" in rolled_back.error_message
    assert "unable to auto-detect email" in rolled_back.error_message
    # The restore itself still happened.
    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_rollback_treats_nothing_to_commit_as_success(tmp_path):
    """Restoring the files can leave nothing staged; that is a clean rollback."""
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    def nothing_staged(root, message, **identity):
        return CommandResult(1, "nothing to commit, working tree clean", "")

    service.git_runner.commit = nothing_staged
    rolled_back = await service.rollback_apply_run(apply_run.id, tenant_id)

    assert rolled_back.status == PatchApplyRunStatus.rolled_back
    assert rolled_back.error_message is None


@pytest.mark.asyncio
async def test_rollback_with_a_missing_backup_is_not_reported_as_rolled_back(tmp_path):
    """This is the failure that actually happened on the first real apply run.

    The backups were gone, every file stayed patched, and the run was still
    marked rolled_back - so the state looked recovered when nothing had been.
    """
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)

    backup = Path(repository.results[0].backup_path)
    assert backup.is_file()
    backup.unlink()

    rolled_back = await service.rollback_apply_run(apply_run.id, tenant_id)

    assert rolled_back.status == PatchApplyRunStatus.failed
    assert "could not be restored" in rolled_back.error_message
    assert "app/page.tsx" in rolled_back.error_message
    assert repository.results[0].status == PatchApplyResultStatus.failed
    # The file was not silently left half-way: it still holds the patch.
    assert (tmp_path / "app" / "page.tsx").read_text(encoding="utf-8") == "patched"


# ---------------------------------------------------------------------------
# Newline preservation
#
# A CRLF checkout patched from a Linux container used to come back LF. git's
# clean filter hides it from `git diff`, so the only evidence is the bytes.
# ---------------------------------------------------------------------------


def _bytes_with(newline: str, *lines: str) -> bytes:
    return newline.join(lines).encode("utf-8") + newline.encode("utf-8")


def _eol_counts(raw: bytes) -> tuple:
    crlf = raw.count(b"\r\n")
    return crlf, raw.count(b"\n") - crlf


@pytest.mark.asyncio
@pytest.mark.parametrize("newline,label", [("\r\n", "CRLF"), ("\n", "LF")])
async def test_applying_a_patch_preserves_the_files_newline_convention(
    tmp_path, newline, label
):
    original_text = 'export const metadata = {\n  title: "Page",\n};\n'
    proposed_text = 'export const metadata = {\n  title: "Page",\n  alternates: {},\n};\n'

    target = tmp_path / "app" / "page.tsx"
    target.parent.mkdir(parents=True)
    target.write_bytes(original_text.replace("\n", newline).encode("utf-8"))

    service, repository, tenant_id = make_service(
        tmp_path, [("app/page.tsx", original_text, proposed_text, SeoCodePatchStatus.approved)]
    )
    # make_service seeds its own file; restore the convention under test.
    target.write_bytes(original_text.replace("\n", newline).encode("utf-8"))
    repository.patches[0].original_content_hash = content_hash(original_text)

    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)
    assert apply_run.patches_applied == 1, repository.results[0].reason

    raw = target.read_bytes()
    crlf, lf = _eol_counts(raw)
    if newline == "\r\n":
        assert lf == 0 and crlf == 4, f"{label}: expected pure CRLF, got {raw!r}"
    else:
        assert crlf == 0 and lf == 4, f"{label}: expected pure LF, got {raw!r}"

    # The logical content is the patch content either way.
    assert read_repo_text(target) == proposed_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"a\r\nb\r\n", "\r\n"),
        (b"a\nb\n", "\n"),
        (b"a\r\nb\n", "\r\n"),   # mixed: preserve the convention a plain write would destroy
        (b"no newline at all", "\n"),
        (b"", "\n"),
    ],
)
def test_newline_detection(raw, expected):
    assert detect_newline_style(raw) == expected


def test_newline_detection_from_a_path_and_from_text(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"a\r\nb\r\n")
    assert detect_newline_style(path) == "\r\n"
    assert detect_newline_style("a\r\nb") == "\r\n"
    assert detect_newline_style("a\nb") == "\n"
    # An unreadable path must not raise in the middle of an apply.
    assert detect_newline_style(tmp_path / "missing.txt") == "\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("newline", ["\r\n", "\n"])
async def test_backup_and_rollback_reproduce_the_original_bytes(tmp_path, newline):
    original_text = 'export const metadata = {\n  title: "Page",\n};\n'
    proposed_text = 'export const metadata = {\n  title: "Page",\n  alternates: {},\n};\n'
    original_bytes = original_text.replace("\n", newline).encode("utf-8")

    target = tmp_path / "app" / "page.tsx"
    target.parent.mkdir(parents=True)
    target.write_bytes(original_bytes)

    service, repository, tenant_id = make_service(
        tmp_path, [("app/page.tsx", original_text, proposed_text, SeoCodePatchStatus.approved)]
    )
    target.write_bytes(original_bytes)
    repository.patches[0].original_content_hash = content_hash(original_text)

    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)
    assert apply_run.patches_applied == 1

    # The backup is the original file, byte for byte.
    backup = Path(repository.results[0].backup_path)
    assert backup.read_bytes() == original_bytes

    await service.rollback_apply_run(apply_run.id, tenant_id)
    assert target.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_backup_preserves_a_byte_order_mark(tmp_path):
    """A BOM is part of the file's bytes, and read_repo_text strips it."""
    original_text = 'export const metadata = {};\n'
    original_bytes = b"\xef\xbb\xbf" + original_text.encode("utf-8")

    target = tmp_path / "app" / "page.tsx"
    target.parent.mkdir(parents=True)
    service, repository, tenant_id = make_service(
        tmp_path, [("app/page.tsx", original_text, 'export const metadata = { a: 1 };\n',
                    SeoCodePatchStatus.approved)]
    )
    target.write_bytes(original_bytes)
    repository.patches[0].original_content_hash = content_hash(original_text)

    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)
    assert apply_run.patches_applied == 1
    assert Path(repository.results[0].backup_path).read_bytes() == original_bytes

    await service.rollback_apply_run(apply_run.id, tenant_id)
    assert target.read_bytes() == original_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize("newline", ["\r\n", "\n"])
async def test_hash_conflict_detection_is_unaffected_by_newline_style(tmp_path, newline):
    """The base hash is computed on normalised text, so CRLF is not a conflict."""
    original_text = 'export const metadata = {\n  title: "Page",\n};\n'
    target = tmp_path / "app" / "page.tsx"
    target.parent.mkdir(parents=True)

    service, repository, tenant_id = make_service(
        tmp_path, [("app/page.tsx", original_text, "patched\n", SeoCodePatchStatus.approved)]
    )
    target.write_bytes(original_text.replace("\n", newline).encode("utf-8"))
    repository.patches[0].original_content_hash = content_hash(original_text)

    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)
    assert apply_run.patches_applied == 1
    assert repository.results[0].status == PatchApplyResultStatus.applied


@pytest.mark.asyncio
async def test_a_real_content_change_is_still_a_hash_conflict(tmp_path):
    """Newline tolerance must not weaken the conflict guard."""
    original_text = 'export const metadata = {\n  title: "Page",\n};\n'
    target = tmp_path / "app" / "page.tsx"
    target.parent.mkdir(parents=True)

    service, repository, tenant_id = make_service(
        tmp_path, [("app/page.tsx", original_text, "patched\n", SeoCodePatchStatus.approved)]
    )
    # Someone edited the file after the patch was generated.
    target.write_bytes(b"export const metadata = {\r\n  title: \"Edited\",\r\n};\r\n")
    repository.patches[0].original_content_hash = content_hash(original_text)

    apply_run = await service.apply_approved_patches(repository.run.id, tenant_id)
    assert apply_run.patches_applied == 0
    assert repository.results[0].status == PatchApplyResultStatus.skipped
    assert "hash mismatch" in repository.results[0].reason.lower()
    # Untouched.
    assert target.read_bytes() == b"export const metadata = {\r\n  title: \"Edited\",\r\n};\r\n"


@pytest.mark.asyncio
async def test_validation_still_runs_and_gates_the_result(tmp_path):
    """Newline handling must not disturb the validation step."""
    service, repository, tenant_id = make_service(
        tmp_path,
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
        validation_passed=False,
    )
    apply_run = await service.apply_approved_patches(
        repository.run.id, tenant_id, run_validation=True, validation_commands=["echo hi"]
    )
    assert apply_run.validation_status == PatchValidationStatus.failed

    service2, repository2, tenant2 = make_service(
        tmp_path / "ok",
        [("app/page.tsx", "original", "patched", SeoCodePatchStatus.approved)],
    )
    run2 = await service2.apply_approved_patches(
        repository2.run.id, tenant2, run_validation=True, validation_commands=["echo hi"]
    )
    assert run2.validation_status == PatchValidationStatus.passed


def test_writes_follow_the_file_not_the_host_platform(tmp_path):
    """Why the bug stayed invisible until it ran on the other platform.

    `Path.write_text` translates newlines to os.linesep, so the previous code
    rewrote every patched file in the host's convention: LF when the agent ran
    in a Linux container, CRLF when it ran on Windows. Either way the file
    stopped matching the checkout it came from.
    """
    text = "a\nb\n"

    host_default = tmp_path / "host.txt"
    host_default.write_text(text, encoding="utf-8")
    assert host_default.read_bytes() == text.replace("\n", os.linesep).encode("utf-8")

    for name, newline in (("lf", "\n"), ("crlf", "\r\n")):
        explicit = tmp_path / (name + ".txt")
        write_repo_text(explicit, text, newline=newline)
        assert explicit.read_bytes() == text.replace("\n", newline).encode("utf-8")

from datetime import datetime
from pathlib import Path
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
from app.repo_agent.scanner import content_hash
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
        self.pushed = []

    def ensure_repo(self, root: Path):
        assert root.exists()

    def checkout_branch(self, root: Path, branch_name: str):
        self.branches.append(branch_name)

    def add(self, root: Path, file_paths):
        self.added.extend(file_paths)

    def commit(self, root: Path, message: str):
        self.commits.append(message)
        return CommandResult(0, "committed", "")

    def commit_sha(self, root: Path):
        return "abc123"

    def push_branch(self, root: Path, branch_name: str):
        self.pushed.append(branch_name)
        return CommandResult(0, "pushed", "")

    def diff_summary(self, root: Path):
        return " app/page.tsx | 2 +"

    def run(self, root: Path, args):
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

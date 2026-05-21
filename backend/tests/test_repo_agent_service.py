from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.content_optimization import ContentOptimizationSuggestionType
from app.models.repo_agent import (
    RepoConnectionStatus,
    RepoProvider,
    RepoScanRunStatus,
    SeoCodeIssueStatus,
    SeoCodeIssueType,
    SeoCodePatchStatus,
)
from app.models.search_console import SearchConsoleOpportunityType
from app.services.repo_agent import RepoAgentService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_fixture(root: Path):
    write(root / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(
        root / "app" / "layout.tsx",
        "export default function RootLayout({ children }) { return <html><body>{children}</body></html>; }\n",
    )
    write(
        root / "app" / "page.tsx",
        "export default function Page() {\n  return (\n    <main><h1>Home</h1></main>\n  );\n}\n",
    )
    write(
        root / "app" / "services" / "page.tsx",
        "export default function Services() {\n  return (\n    <main><h1>Services</h1></main>\n  );\n}\n",
    )


class FakeRepoAgentRepository:
    def __init__(self, tenant_id, project_id, root):
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.root = root
        self.connection = None
        self.run = None
        self.files = []
        self.issues = []
        self.patches = []
        self.content_suggestions = []
        self.search_opportunities = []
        self.geo_recommendations = []
        self.architecture_profile = None

    async def get_project(self, project_id, tenant_id):
        if project_id == self.project_id and tenant_id == self.tenant_id:
            return SimpleNamespace(id=project_id, tenant_id=tenant_id, domain="example.com")
        return None

    async def create_connection(self, **kwargs):
        now = datetime.utcnow()
        self.connection = SimpleNamespace(id=uuid4(), created_at=now, updated_at=now, **kwargs)
        return self.connection

    async def get_connection(self, connection_id, tenant_id=None):
        if self.connection and self.connection.id == connection_id:
            return self.connection
        return None

    async def set_connection_status(self, connection, status, framework=None):
        connection.status = status
        if framework:
            connection.framework = framework
        return connection

    async def create_scan_run(self, connection):
        now = datetime.utcnow()
        self.run = SimpleNamespace(
            id=uuid4(),
            tenant_id=connection.tenant_id,
            project_id=connection.project_id,
            repo_connection_id=connection.id,
            status=RepoScanRunStatus.queued,
            framework_detected=None,
            files_scanned=0,
            issues_found=0,
            patches_created=0,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        return self.run

    async def get_scan_run(self, scan_id, tenant_id=None):
        if self.run and self.run.id == scan_id:
            return self.run
        return None

    async def set_scan_status(self, run, status, error_message=None, framework_detected=None):
        run.status = status
        run.error_message = error_message
        if framework_detected:
            run.framework_detected = framework_detected
        return run

    async def finish_scan(self, run, framework_detected, files_scanned, issues_found, patches_created=None):
        run.framework_detected = framework_detected
        run.files_scanned = files_scanned
        run.issues_found = issues_found
        run.status = RepoScanRunStatus.completed
        return run

    async def add_files(self, records):
        self.files = [SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), **record) for record in records]
        return self.files

    async def list_files(self, scan_id, tenant_id, limit=500, offset=0):
        return self.files[offset : offset + limit]

    async def add_issues(self, records):
        created = [SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **record) for record in records]
        self.issues.extend(created)
        return created

    async def list_issues(self, scan_id, tenant_id, status=None, limit=500, offset=0):
        items = [issue for issue in self.issues if not status or issue.status == status]
        return items[offset : offset + limit]

    async def existing_patch(self, issue_id, file_path, patch_type, original_content_hash):
        for patch in self.patches:
            if (
                patch.issue_id == issue_id
                and patch.file_path == file_path
                and patch.patch_type == patch_type
                and patch.original_content_hash == original_content_hash
            ):
                return patch
        return None

    async def add_patches(self, records):
        patches = [SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **record) for record in records]
        self.patches.extend(patches)
        return patches

    async def list_patches(self, scan_id, tenant_id, status=None, limit=500, offset=0):
        items = [patch for patch in self.patches if not status or patch.status == status]
        return items[offset : offset + limit]

    async def get_patch(self, patch_id, tenant_id):
        return next((patch for patch in self.patches if patch.id == patch_id), None)

    async def set_patch_status(self, patch, status):
        patch.status = status
        patch.updated_at = datetime.utcnow()
        return patch

    async def update_scan_patch_count(self, run, patches_created):
        run.patches_created = patches_created
        return run

    async def create_architecture_profile(self, run, values):
        now = datetime.utcnow()
        self.architecture_profile = SimpleNamespace(
            id=uuid4(),
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            repo_connection_id=run.repo_connection_id,
            scan_run_id=run.id,
            created_at=now,
            **values,
        )
        return self.architecture_profile

    async def get_architecture_profile(self, scan_id, tenant_id):
        if self.architecture_profile and self.architecture_profile.scan_run_id == scan_id:
            return self.architecture_profile
        return None

    async def list_content_suggestions(self, tenant_id, project_id):
        return self.content_suggestions

    async def list_search_console_opportunities(self, tenant_id, project_id):
        return self.search_opportunities

    async def list_geo_aeo_recommendations(self, tenant_id, project_id):
        return self.geo_recommendations


@pytest.mark.asyncio
async def test_service_scan_creates_repo_and_signal_issues_and_patches(tmp_path):
    create_fixture(tmp_path)
    tenant_id = uuid4()
    project_id = uuid4()
    repository = FakeRepoAgentRepository(tenant_id, project_id, tmp_path)
    repository.content_suggestions = [
        SimpleNamespace(
            id=uuid4(),
            suggestion_type=ContentOptimizationSuggestionType.schema,
            evidence={"url": "https://example.com/services"},
        )
    ]
    repository.search_opportunities = [
        SimpleNamespace(
            id=uuid4(),
            opportunity_type=SearchConsoleOpportunityType.high_impressions_low_ctr,
            query="seo services",
            page_url="https://example.com/services",
        )
    ]
    service = RepoAgentService(FakeDB())
    service.repository = repository

    connection = await service.create_connection(
        tenant_id=tenant_id,
        project_id=project_id,
        provider=RepoProvider.local,
        local_path=str(tmp_path),
    )
    run = await service.scan_connection(connection.id, tenant_id)
    patches = await service.generate_patches(run.id, tenant_id)

    issue_types = {issue.issue_type for issue in repository.issues}
    patch_types = {patch.patch_type.value for patch in patches}

    assert connection.framework == "nextjs_app_router"
    assert run.status == RepoScanRunStatus.completed
    assert run.files_scanned >= 3
    assert SeoCodeIssueType.missing_metadata in issue_types
    assert SeoCodeIssueType.missing_schema in issue_types
    assert SeoCodeIssueType.missing_sitemap in issue_types
    assert SeoCodeIssueType.missing_robots in issue_types
    assert SeoCodeIssueType.weak_metadata in issue_types
    assert "metadata_update" in patch_types
    assert "schema_addition" in patch_types
    assert "sitemap_update" in patch_types
    assert "robots_update" in patch_types
    assert all("className" not in patch.diff_text for patch in patches)


@pytest.mark.asyncio
async def test_patch_approval_rejection_flow(tmp_path):
    create_fixture(tmp_path)
    tenant_id = uuid4()
    project_id = uuid4()
    repository = FakeRepoAgentRepository(tenant_id, project_id, tmp_path)
    service = RepoAgentService(FakeDB())
    service.repository = repository
    connection = await service.create_connection(tenant_id, project_id, RepoProvider.local, local_path=str(tmp_path))
    run = await service.scan_connection(connection.id, tenant_id)
    patches = await service.generate_patches(run.id, tenant_id)

    approved = await service.update_patch_status(patches[0].id, tenant_id, SeoCodePatchStatus.approved)
    assert approved.status == SeoCodePatchStatus.approved
    rejected = await service.update_patch_status(patches[0].id, tenant_id, SeoCodePatchStatus.rejected)

    assert rejected.status == SeoCodePatchStatus.rejected

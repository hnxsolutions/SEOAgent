from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import repos as repo_routes
from app.models.repo_agent import (
    PatchApplyResultStatus,
    PatchApplyRunStatus,
    PatchValidationStatus,
    PullRequestStatus,
    RepoConnectionStatus,
    RepoProvider,
    RepoScanRunStatus,
    SeoCodeIssueSeverity,
    SeoCodeIssueSource,
    SeoCodeIssueStatus,
    SeoCodeIssueType,
    SeoCodePatchRisk,
    SeoCodePatchStatus,
    SeoCodePatchType,
)


def test_repo_agent_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    connection_id = uuid4()
    scan_id = uuid4()
    file_id = uuid4()
    issue_id = uuid4()
    patch_id = uuid4()
    now = datetime.utcnow()

    connection = SimpleNamespace(
        id=connection_id,
        tenant_id=tenant_id,
        project_id=project_id,
        provider=RepoProvider.local,
        repo_url=None,
        local_path="C:/site",
        default_branch="main",
        framework="nextjs_app_router",
        status=RepoConnectionStatus.connected,
        created_at=now,
        updated_at=now,
    )
    scan = SimpleNamespace(
        id=scan_id,
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        status=RepoScanRunStatus.completed,
        framework_detected="nextjs_app_router",
        files_scanned=3,
        issues_found=4,
        patches_created=2,
        error_message=None,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    repo_file = SimpleNamespace(
        id=file_id,
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        scan_run_id=scan_id,
        file_path="app/page.tsx",
        file_type="tsx",
        content_hash="a" * 64,
        detected_purpose="page",
        has_metadata=False,
        has_jsonld=False,
        has_canonical=False,
        has_open_graph=False,
        has_twitter_meta=False,
        has_sitemap=False,
        has_robots=False,
        created_at=now,
    )
    architecture_profile = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        scan_run_id=scan_id,
        detected_stack="nextjs_app_router",
        framework="nextjs",
        router_type="app_router",
        package_manager="npm",
        languages={"primary": "TypeScript", "counts": {"TypeScript": 2}},
        route_map=[{"route_path": "/", "file_path": "app/page.tsx", "route_type": "page", "dynamic": False, "confidence": 0.9}],
        content_sources=[],
        blog_system={"exists": False, "insertion_strategy": "unknown_manual_review"},
        metadata_strategy={"strategy": "next_metadata_export", "files": ["app/page.tsx"], "confidence": 0.9},
        schema_strategy={"strategy": "unknown", "files": [], "duplicate_risk": False},
        sitemap_strategy={"exists": False, "strategy": "missing", "rich_dynamic": False},
        robots_strategy={"exists": False, "strategy": "missing", "rich_dynamic": False},
        cms_strategy={"strategy": "none_detected"},
        client_server_boundaries={"client_components": [], "server_or_static_files": ["app/page.tsx"]},
        safe_patch_zones=[{"zone_type": "metadata", "file_path": "app/page.tsx", "patch_types": ["metadata_update"], "reason": "safe", "confidence": 0.9}],
        manual_review_zones=[],
        unsafe_patch_zones=[],
        confidence_score=0.94,
        detection_notes=[{"kind": "stack", "value": "Next.js App Router markers found."}],
        created_at=now,
    )
    safety_summary = {
        "detected_stack": "nextjs_app_router",
        "framework": "nextjs",
        "confidence_score": 0.94,
        "blog_system": architecture_profile.blog_system,
        "metadata_strategy": architecture_profile.metadata_strategy,
        "schema_strategy": architecture_profile.schema_strategy,
        "sitemap_strategy": architecture_profile.sitemap_strategy,
        "robots_strategy": architecture_profile.robots_strategy,
        "safe_patch_count": 1,
        "manual_review_count": 0,
        "unsafe_skipped_count": 0,
        "top_safety_reasons": [],
    }
    issue = SimpleNamespace(
        id=issue_id,
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        scan_run_id=scan_id,
        file_id=file_id,
        issue_type=SeoCodeIssueType.missing_metadata,
        severity=SeoCodeIssueSeverity.medium,
        title="Missing metadata",
        description="Missing metadata export.",
        recommended_fix="Add metadata export.",
        source_reference_type=SeoCodeIssueSource.repo_scan,
        source_reference_id=None,
        status=SeoCodeIssueStatus.open,
        created_at=now,
        updated_at=now,
    )
    patch = SimpleNamespace(
        id=patch_id,
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        scan_run_id=scan_id,
        issue_id=issue_id,
        file_path="app/page.tsx",
        patch_type=SeoCodePatchType.metadata_update,
        original_content_hash="a" * 64,
        diff_text="--- a/app/page.tsx\n+++ b/app/page.tsx\n",
        proposed_content="export const metadata = {};",
        explanation="Metadata-only patch.",
        risk_level=SeoCodePatchRisk.low,
        status=SeoCodePatchStatus.proposed,
        created_at=now,
        updated_at=now,
    )
    apply_run_id = uuid4()
    apply_result_id = uuid4()
    pr_id = uuid4()
    apply_run = SimpleNamespace(
        id=apply_run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        scan_run_id=scan_id,
        branch_name="seo-agent/scan-20260519120000",
        status=PatchApplyRunStatus.completed,
        patches_requested=1,
        patches_applied=1,
        patches_failed=0,
        validation_status=PatchValidationStatus.passed,
        validation_output="ok",
        git_diff_summary="app/page.tsx | 2 +",
        error_message=None,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    apply_result = SimpleNamespace(
        id=apply_result_id,
        tenant_id=tenant_id,
        project_id=project_id,
        apply_run_id=apply_run_id,
        patch_id=patch_id,
        file_path="app/page.tsx",
        status=PatchApplyResultStatus.applied,
        reason="Patch applied to working branch.",
        original_content_hash="a" * 64,
        new_content_hash="b" * 64,
        backup_path="C:/backup/app-page.tsx",
        created_at=now,
    )
    pull_request = SimpleNamespace(
        id=pr_id,
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=connection_id,
        apply_run_id=apply_run_id,
        provider="github",
        branch_name=apply_run.branch_name,
        base_branch="main",
        commit_sha="abc123",
        pr_number=42,
        pr_url="https://github.com/acme/site/pull/42",
        status=PullRequestStatus.draft,
        title="SEO Agent: approved SEO fixes",
        description="Applied patches: 1",
        error_message=None,
        created_at=now,
        updated_at=now,
    )

    class FakeRepoAgentService:
        def __init__(self, db):
            self.db = db

        async def create_connection(self, **kwargs):
            connection.local_path = kwargs["local_path"]
            connection.project_id = kwargs["project_id"]
            return connection

        async def list_connections(self, **kwargs):
            return [connection]

        async def get_connection(self, connection_id, tenant_id):
            return connection

        async def scan_connection(self, connection_id, tenant_id):
            return scan

        async def get_scan_status(self, scan_id, tenant_id):
            return scan

        async def list_files(self, scan_id, tenant_id, limit=500, offset=0):
            return [repo_file]

        async def get_architecture_profile(self, scan_id, tenant_id):
            return architecture_profile

        async def get_patch_safety_summary(self, scan_id, tenant_id):
            return safety_summary

        async def list_issues(self, scan_id, tenant_id, status=None, limit=500, offset=0):
            return [issue]

        async def generate_patches(self, scan_id, tenant_id):
            return [patch]

        async def list_patches(self, scan_id, tenant_id, status=None, limit=500, offset=0):
            return [patch]

        async def get_patch(self, patch_id, tenant_id):
            patch.id = patch_id
            return patch

        async def update_patch_status(self, patch_id, tenant_id, status):
            patch.id = patch_id
            patch.status = status
            return patch

        async def apply_approved_patches(self, scan_id, tenant_id, allow_high_risk=False, run_validation=False, validation_commands=None):
            assert allow_high_risk is False
            return apply_run

        async def get_apply_run_status(self, apply_run_id, tenant_id):
            return apply_run

        async def list_apply_results(self, apply_run_id, tenant_id, limit=500, offset=0):
            return [apply_result]

        async def create_pull_request(
            self,
            apply_run_id,
            tenant_id,
            force_pr_on_validation_failure=False,
            draft=True,
            title=None,
            description=None,
        ):
            return pull_request

        async def get_pull_request(self, pr_id, tenant_id):
            return pull_request

        async def rollback_apply_run(self, apply_run_id, tenant_id):
            apply_run.status = PatchApplyRunStatus.rolled_back
            return apply_run

    monkeypatch.setattr(repo_routes, "RepoAgentService", FakeRepoAgentService)

    app = FastAPI()
    app.include_router(repo_routes.router, prefix="/repos")
    app.dependency_overrides[repo_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[repo_routes.get_db] = lambda: object()
    client = TestClient(app)

    create_response = client.post(
        "/repos/connections",
        json={"project_id": str(project_id), "provider": "local", "local_path": "C:/site"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["framework"] == "nextjs_app_router"

    list_response = client.get("/repos/connections")
    assert list_response.status_code == 200
    assert list_response.json()["connections"][0]["id"] == str(connection_id)

    get_response = client.get(f"/repos/connections/{connection_id}")
    assert get_response.status_code == 200

    scan_response = client.post(f"/repos/connections/{connection_id}/scan")
    assert scan_response.status_code == 200
    assert scan_response.json()["issues_found"] == 4

    status_response = client.get(f"/repos/scans/{scan_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["framework_detected"] == "nextjs_app_router"

    files_response = client.get(f"/repos/scans/{scan_id}/files")
    assert files_response.status_code == 200
    assert files_response.json()["files"][0]["file_path"] == "app/page.tsx"

    architecture_response = client.get(f"/repos/scans/{scan_id}/architecture")
    assert architecture_response.status_code == 200
    assert architecture_response.json()["detected_stack"] == "nextjs_app_router"

    safety_response = client.get(f"/repos/scans/{scan_id}/patch-safety-summary")
    assert safety_response.status_code == 200
    assert safety_response.json()["safe_patch_count"] == 1

    issues_response = client.get(f"/repos/scans/{scan_id}/issues")
    assert issues_response.status_code == 200
    assert issues_response.json()["issues"][0]["issue_type"] == "missing_metadata"

    generate_response = client.post(f"/repos/scans/{scan_id}/patches/generate")
    assert generate_response.status_code == 200
    assert generate_response.json()["patches_created"] == 1

    patches_response = client.get(f"/repos/scans/{scan_id}/patches")
    assert patches_response.status_code == 200
    assert patches_response.json()["patches"][0]["patch_type"] == "metadata_update"

    patch_response = client.get(f"/repos/patches/{patch_id}")
    assert patch_response.status_code == 200

    approve_response = client.post(f"/repos/patches/{patch_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    reject_response = client.post(f"/repos/patches/{patch_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    applied_response = client.post(f"/repos/patches/{patch_id}/mark-applied")
    assert applied_response.status_code == 200
    assert applied_response.json()["status"] == "applied"

    apply_response = client.post(f"/repos/scans/{scan_id}/apply-approved-patches", json={"run_validation": True})
    assert apply_response.status_code == 200
    assert apply_response.json()["patches_applied"] == 1

    apply_status_response = client.get(f"/repos/apply-runs/{apply_run_id}/status")
    assert apply_status_response.status_code == 200
    assert apply_status_response.json()["branch_name"].startswith("seo-agent/")

    results_response = client.get(f"/repos/apply-runs/{apply_run_id}/results")
    assert results_response.status_code == 200
    assert results_response.json()["results"][0]["status"] == "applied"

    pr_response = client.post(f"/repos/apply-runs/{apply_run_id}/create-pr")
    assert pr_response.status_code == 200
    assert pr_response.json()["pr_url"] == "https://github.com/acme/site/pull/42"

    get_pr_response = client.get(f"/repos/pull-requests/{pr_id}")
    assert get_pr_response.status_code == 200
    assert get_pr_response.json()["status"] == "draft"

    rollback_response = client.post(f"/repos/apply-runs/{apply_run_id}/rollback")
    assert rollback_response.status_code == 200
    assert rollback_response.json()["status"] == "rolled_back"

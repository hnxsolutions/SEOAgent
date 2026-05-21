from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import blog_publishing as publishing_routes
from app.models.blog_publishing import (
    BlogInfrastructureStrategy,
    BlogPublishConnectionStatus,
    BlogPublishMode,
    BlogPublishProvider,
    BlogPublishResultStatus,
    BlogPublishRunStatus,
)


def test_blog_publishing_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    connection_id = uuid4()
    repo_connection_id = uuid4()
    draft_id = uuid4()
    run_id = uuid4()
    result_id = uuid4()
    check_id = uuid4()
    patch_id = uuid4()
    now = datetime.utcnow()

    connection = SimpleNamespace(
        id=connection_id,
        tenant_id=tenant_id,
        project_id=project_id,
        provider=BlogPublishProvider.markdown_export,
        site_url=None,
        repo_connection_id=repo_connection_id,
        export_folder_path="C:/exports",
        username=None,
        status=BlogPublishConnectionStatus.connected,
        auto_upload_drafts_enabled=False,
        auto_publish_enabled=False,
        created_at=now,
        updated_at=now,
    )
    check = SimpleNamespace(
        id=check_id,
        tenant_id=tenant_id,
        project_id=project_id,
        repo_connection_id=repo_connection_id,
        status="completed",
        framework_detected="nextjs_app_router",
        has_blog_index=False,
        has_blog_detail_route=False,
        has_content_directory=False,
        blog_route_path=None,
        content_directory=None,
        recommended_strategy=BlogInfrastructureStrategy.create_blog_infrastructure,
        issues=[{"code": "missing_blog_index", "message": "No blog index route was found."}],
        created_at=now,
    )
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        blog_draft_id=draft_id,
        connection_id=connection_id,
        provider=BlogPublishProvider.markdown_export,
        mode=BlogPublishMode.markdown_export,
        status=BlogPublishRunStatus.completed,
        started_at=now,
        completed_at=now,
        error_message=None,
        created_at=now,
    )
    result = SimpleNamespace(
        id=result_id,
        tenant_id=tenant_id,
        project_id=project_id,
        publish_run_id=run_id,
        blog_draft_id=draft_id,
        provider=BlogPublishProvider.markdown_export,
        status=BlogPublishResultStatus.file_exported,
        external_id=None,
        external_url=None,
        file_path="C:/exports/local-seo.md",
        patch_id=patch_id,
        pr_id=None,
        title="Local SEO Guide",
        slug="local-seo-guide",
        created_at=now,
    )

    class FakeBlogPublishingService:
        def __init__(self, db):
            self.db = db

        async def create_connection(self, **kwargs):
            connection.project_id = kwargs["project_id"]
            connection.provider = kwargs["provider"]
            return connection

        async def list_connections(self, **kwargs):
            return [connection]

        async def test_connection(self, connection_id, tenant_id):
            return {
                "connection_id": connection_id,
                "provider": "markdown_export",
                "status": "connected",
                "ok": True,
                "message": "Markdown export folder is available.",
            }

        async def check_infrastructure(self, **kwargs):
            return check

        async def latest_infrastructure(self, project_id, tenant_id):
            return check

        async def export_markdown(self, **kwargs):
            return run, result

        async def create_wordpress_draft(self, **kwargs):
            run.provider = BlogPublishProvider.wordpress
            run.mode = BlogPublishMode.draft_upload
            result.provider = BlogPublishProvider.wordpress
            result.status = BlogPublishResultStatus.draft_created
            result.external_id = "123"
            result.external_url = "https://example.com/?p=123"
            return run, result

        async def create_nextjs_blog_patch(self, **kwargs):
            run.provider = BlogPublishProvider.nextjs_repo
            run.mode = BlogPublishMode.repo_patch
            result.provider = BlogPublishProvider.nextjs_repo
            result.status = BlogPublishResultStatus.patch_created
            return run, result

        async def create_blog_infrastructure_patch(self, **kwargs):
            run.provider = BlogPublishProvider.nextjs_repo
            run.mode = BlogPublishMode.infrastructure_patch
            result.provider = BlogPublishProvider.nextjs_repo
            result.status = BlogPublishResultStatus.infrastructure_patch_created
            return run, result

        async def get_run(self, run_id, tenant_id):
            return run

        async def get_result(self, run_id, tenant_id):
            return result

    monkeypatch.setattr(publishing_routes, "BlogPublishingService", FakeBlogPublishingService)

    app = FastAPI()
    app.include_router(publishing_routes.router, prefix="/blog-publishing")
    app.dependency_overrides[publishing_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[publishing_routes.get_db] = lambda: object()
    client = TestClient(app)

    create_response = client.post(
        "/blog-publishing/connections",
        json={
            "project_id": str(project_id),
            "provider": "markdown_export",
            "export_folder_path": "C:/exports",
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["status"] == "connected"

    list_response = client.get(f"/blog-publishing/connections/projects/{project_id}")
    assert list_response.status_code == 200
    assert list_response.json()["connections"][0]["id"] == str(connection_id)

    test_response = client.post(f"/blog-publishing/connections/{connection_id}/test")
    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True

    check_response = client.post(
        f"/blog-publishing/projects/{project_id}/check-infrastructure",
        json={"repo_connection_id": str(repo_connection_id)},
    )
    assert check_response.status_code == 200
    assert check_response.json()["recommended_strategy"] == "create_blog_infrastructure"

    latest_response = client.get(f"/blog-publishing/projects/{project_id}/infrastructure")
    assert latest_response.status_code == 200
    assert latest_response.json()["issues"][0]["code"] == "missing_blog_index"

    export_response = client.post(
        f"/blog-publishing/drafts/{draft_id}/export-markdown",
        json={"connection_id": str(connection_id), "overwrite": False},
    )
    assert export_response.status_code == 200
    assert export_response.json()["result"]["status"] == "file_exported"

    wordpress_response = client.post(
        f"/blog-publishing/drafts/{draft_id}/create-wordpress-draft",
        json={"connection_id": str(connection_id)},
    )
    assert wordpress_response.status_code == 200
    assert wordpress_response.json()["result"]["external_id"] == "123"

    patch_response = client.post(
        f"/blog-publishing/drafts/{draft_id}/create-nextjs-blog-patch",
        json={"repo_connection_id": str(repo_connection_id)},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["result"]["status"] == "patch_created"

    infra_patch_response = client.post(
        f"/blog-publishing/projects/{project_id}/create-blog-infrastructure-patch",
        json={"repo_connection_id": str(repo_connection_id), "strategy": "nextjs_markdown"},
    )
    assert infra_patch_response.status_code == 200
    assert infra_patch_response.json()["result"]["status"] == "infrastructure_patch_created"

    run_response = client.get(f"/blog-publishing/runs/{run_id}/status")
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"

    result_response = client.get(f"/blog-publishing/runs/{run_id}/result")
    assert result_response.status_code == 200
    assert result_response.json()["patch_id"] == str(patch_id)

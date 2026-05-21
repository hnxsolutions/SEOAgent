from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.encryption import decrypt_secret
from app.models.blog import BlogDraftStatus
from app.models.blog_publishing import (
    BlogInfrastructureStrategy,
    BlogPublishConnectionStatus,
    BlogPublishMode,
    BlogPublishProvider,
    BlogPublishResultStatus,
    BlogPublishRunStatus,
)
from app.models.repo_agent import RepoProvider, RepoScanRunStatus
from app.repo_agent.scanner import PathSafetyError
from app.services.blog_publishing import BlogPublishingError, BlogPublishingService, WordPressDraftResult


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_next_fixture(root: Path, *, with_blog: bool):
    write(root / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(root / "app" / "layout.tsx", "export default function Layout({ children }) { return children; }\n")
    write(root / "app" / "page.tsx", "export default function Page() { return <main><h1>Home</h1></main>; }\n")
    if with_blog:
        write(root / "app" / "blog" / "page.tsx", "export default function Blog() { return <main />; }\n")
        write(root / "app" / "blog" / "[slug]" / "page.tsx", "export default function Post() { return <main />; }\n")
        write(root / "content" / "blog" / "sample.md", "---\ntitle: Sample\n---\n")


def create_static_blogs_fixture(root: Path):
    write(root / "package.json", '{"dependencies":{"next":"14.0.0"}}')
    write(root / "app" / "layout.tsx", "export default function Layout({ children }) { return children; }\n")
    write(root / "app" / "blogs" / "page.tsx", "import { blogs } from '@/lib/blogs';\nexport default function Blogs() { return <main />; }\n")
    write(root / "app" / "blogs" / "[slug]" / "page.tsx", "import { getBlogBySlug } from '@/lib/blogs';\nexport default function Post() { return <main />; }\n")
    write(
        root / "lib" / "blogs.ts",
        "export type Blog = { id: string; slug: string; title: string; metaDescription: string; excerpt: string; category: string; readTime: string; publishedAt: string; updatedAt: string; author: \"Novakos Healthcare\"; tags: string[]; image: any; content: any[]; };\n"
        "function pexelsImage(value: any) { return value; }\n"
        "export const blogs: Blog[] = [\n"
        "  { id: \"blog-001\", slug: \"sample\", title: \"Sample\", metaDescription: \"Sample\", excerpt: \"Sample\", category: \"PCD Pharma\", readTime: \"4 min read\", publishedAt: \"2026-01-01\", updatedAt: \"2026-01-01\", author: \"Novakos Healthcare\", tags: [], image: pexelsImage({ id: \"1\", alt: \"Sample\", creditUrl: \"https://example.com\" }), content: [] },\n"
        "];\n"
        "export function getBlogBySlug(slug: string) { return blogs.find((blog) => blog.slug === slug); }\n",
    )


class FakeWordPressClient:
    async def test_connection(self, site_url, username, app_password):
        return site_url == "https://example.com" and username == "editor" and app_password == "app-pass"

    async def create_draft(self, site_url, username, app_password, draft):
        assert app_password == "app-pass"
        return WordPressDraftResult(external_id="123", external_url="https://example.com/?p=123")


class FakeBlogPublishingRepository:
    def __init__(self, tenant_id, project_id, draft, repo_connection=None):
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.draft = draft
        self.repo_connection = repo_connection
        self.connections = []
        self.checks = []
        self.runs = []
        self.results = []

    async def get_project(self, project_id, tenant_id):
        if project_id == self.project_id and tenant_id == self.tenant_id:
            return SimpleNamespace(id=project_id, tenant_id=tenant_id)
        return None

    async def create_connection(self, values):
        connection = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
        self.connections.append(connection)
        return connection

    async def list_connections(self, tenant_id, project_id, provider=None, limit=100, offset=0):
        items = [
            connection
            for connection in self.connections
            if connection.tenant_id == tenant_id
            and connection.project_id == project_id
            and (provider is None or connection.provider == provider)
        ]
        return items[offset : offset + limit]

    async def get_connection(self, connection_id, tenant_id):
        return next((connection for connection in self.connections if connection.id == connection_id and connection.tenant_id == tenant_id), None)

    async def set_connection_status(self, connection, status):
        connection.status = status
        connection.updated_at = datetime.utcnow()
        return connection

    async def get_repo_connection(self, repo_connection_id, tenant_id):
        if self.repo_connection and self.repo_connection.id == repo_connection_id and self.repo_connection.tenant_id == tenant_id:
            return self.repo_connection
        return None

    async def latest_repo_connection(self, project_id, tenant_id):
        if self.repo_connection and self.repo_connection.project_id == project_id and self.repo_connection.tenant_id == tenant_id:
            return self.repo_connection
        return None

    async def get_draft(self, draft_id, tenant_id):
        if self.draft and self.draft.id == draft_id and self.draft.tenant_id == tenant_id:
            return self.draft
        return None

    async def create_infrastructure_check(self, values):
        check = SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), **values)
        self.checks.append(check)
        return check

    async def latest_infrastructure_check(self, project_id, tenant_id):
        return self.checks[-1] if self.checks else None

    async def create_run(self, **kwargs):
        run = SimpleNamespace(
            id=uuid4(),
            status=BlogPublishRunStatus.queued,
            started_at=None,
            completed_at=None,
            error_message=None,
            created_at=datetime.utcnow(),
            **kwargs,
        )
        self.runs.append(run)
        return run

    async def set_run_status(self, run, status, error_message=None):
        run.status = status
        run.error_message = error_message
        if status == BlogPublishRunStatus.running:
            run.started_at = datetime.utcnow()
        if status in {BlogPublishRunStatus.completed, BlogPublishRunStatus.failed, BlogPublishRunStatus.rolled_back}:
            run.completed_at = datetime.utcnow()
        return run

    async def get_run(self, run_id, tenant_id):
        return next((run for run in self.runs if run.id == run_id and run.tenant_id == tenant_id), None)

    async def add_results(self, records):
        created = [SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), **record) for record in records]
        self.results.extend(created)
        return created

    async def get_result_for_run(self, run_id, tenant_id):
        return next((result for result in reversed(self.results) if result.publish_run_id == run_id and result.tenant_id == tenant_id), None)


class FakeRepoPatchRepository:
    def __init__(self):
        self.scans = []
        self.issues = []
        self.patches = []

    async def create_scan_run(self, connection):
        scan = SimpleNamespace(
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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.scans.append(scan)
        return scan

    async def set_scan_status(self, run, status, error_message=None, framework_detected=None):
        run.status = status
        return run

    async def add_issues(self, records):
        created = [SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **record) for record in records]
        self.issues.extend(created)
        return created

    async def add_patches(self, records):
        created = [SimpleNamespace(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **record) for record in records]
        self.patches.extend(created)
        return created

    async def finish_scan(self, run, framework_detected, files_scanned, issues_found, patches_created=None):
        run.status = RepoScanRunStatus.completed
        run.framework_detected = framework_detected
        run.files_scanned = files_scanned
        run.issues_found = issues_found
        run.patches_created = patches_created or 0
        return run


def make_draft(tenant_id, project_id, *, status=BlogDraftStatus.approved):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        blog_topic_id=uuid4(),
        title="Local SEO Planning Guide",
        slug="local-seo-planning-guide",
        meta_title="Local SEO Planning Guide",
        meta_description="Plan safer local SEO improvements with crawl and knowledge data.",
        outline={"h1": "Local SEO Planning Guide"},
        draft_markdown="# Local SEO Planning Guide\n\nUseful draft body.",
        faq_json=[{"question": "What is included?", "answer": "A safe plan."}],
        schema_json={"@context": "https://schema.org", "@type": "BlogPosting"},
        internal_link_plan=[],
        knowledge_sources_used=[{"title": "Business profile"}],
        status=status,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def make_repo_connection(tenant_id, project_id, root: Path):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        provider=RepoProvider.local,
        repo_url=None,
        local_path=str(root),
        default_branch="main",
        framework="nextjs_app_router",
        status="connected",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def make_service(tenant_id, project_id, draft, repo_connection=None):
    service = BlogPublishingService(FakeDB(), wordpress_client=FakeWordPressClient())
    service.repository = FakeBlogPublishingRepository(tenant_id, project_id, draft, repo_connection=repo_connection)
    service.repo_repository = FakeRepoPatchRepository()
    return service


@pytest.mark.asyncio
async def test_connection_creation_encrypts_wordpress_credentials():
    tenant_id = uuid4()
    project_id = uuid4()
    service = make_service(tenant_id, project_id, make_draft(tenant_id, project_id))

    connection = await service.create_connection(
        tenant_id=tenant_id,
        project_id=project_id,
        provider=BlogPublishProvider.wordpress,
        site_url="example.com",
        username="editor",
        app_password="app-pass",
    )

    assert connection.status == BlogPublishConnectionStatus.connected
    assert connection.site_url == "https://example.com"
    assert connection.encrypted_app_password != "app-pass"
    assert decrypt_secret(connection.encrypted_app_password) == "app-pass"
    assert connection.auto_publish_enabled is False


@pytest.mark.asyncio
async def test_wordpress_draft_creation_requires_approved_draft_and_uses_draft_status():
    tenant_id = uuid4()
    project_id = uuid4()
    draft = make_draft(tenant_id, project_id)
    service = make_service(tenant_id, project_id, draft)
    connection = await service.create_connection(
        tenant_id=tenant_id,
        project_id=project_id,
        provider=BlogPublishProvider.wordpress,
        site_url="https://example.com",
        username="editor",
        app_password="app-pass",
    )

    run, result = await service.create_wordpress_draft(draft_id=draft.id, tenant_id=tenant_id, connection_id=connection.id)

    assert run.status == BlogPublishRunStatus.completed
    assert result.status == BlogPublishResultStatus.draft_created
    assert result.external_id == "123"
    assert result.external_url == "https://example.com/?p=123"

    draft.status = BlogDraftStatus.draft
    with pytest.raises(ValueError, match="approved"):
        await service.create_wordpress_draft(draft_id=draft.id, tenant_id=tenant_id, connection_id=connection.id)


@pytest.mark.asyncio
async def test_markdown_export_writes_frontmatter_and_prevents_path_traversal(tmp_path):
    tenant_id = uuid4()
    project_id = uuid4()
    draft = make_draft(tenant_id, project_id)
    service = make_service(tenant_id, project_id, draft)

    run, result = await service.export_markdown(
        draft_id=draft.id,
        tenant_id=tenant_id,
        export_folder_path=str(tmp_path / "exports"),
    )

    exported = Path(result.file_path)
    assert run.mode == BlogPublishMode.markdown_export
    assert result.status == BlogPublishResultStatus.file_exported
    assert exported.exists()
    assert "status: \"draft\"" in exported.read_text(encoding="utf-8")

    with pytest.raises(PathSafetyError):
        await service.export_markdown(
            draft_id=draft.id,
            tenant_id=tenant_id,
            export_folder_path=str(tmp_path / "node_modules" / "exports"),
            overwrite=True,
        )


@pytest.mark.asyncio
async def test_infrastructure_detection_for_nextjs_with_and_without_blog(tmp_path):
    tenant_id = uuid4()
    project_id = uuid4()
    create_next_fixture(tmp_path / "with-blog", with_blog=True)
    repo = make_repo_connection(tenant_id, project_id, tmp_path / "with-blog")
    service = make_service(tenant_id, project_id, make_draft(tenant_id, project_id), repo_connection=repo)

    check = await service.check_infrastructure(tenant_id=tenant_id, project_id=project_id)

    assert check.has_blog_index is True
    assert check.has_blog_detail_route is True
    assert check.has_content_directory is True
    assert check.recommended_strategy == BlogInfrastructureStrategy.nextjs_markdown

    create_next_fixture(tmp_path / "no-blog", with_blog=False)
    repo.local_path = str(tmp_path / "no-blog")
    check = await service.check_infrastructure(tenant_id=tenant_id, project_id=project_id)

    assert check.has_blog_index is False
    assert check.recommended_strategy == BlogInfrastructureStrategy.create_blog_infrastructure
    assert any(issue["code"] == "missing_blog_index" for issue in check.issues)


@pytest.mark.asyncio
async def test_nextjs_blog_file_patch_generation_and_infrastructure_patch(tmp_path):
    tenant_id = uuid4()
    project_id = uuid4()
    create_next_fixture(tmp_path, with_blog=True)
    repo = make_repo_connection(tenant_id, project_id, tmp_path)
    draft = make_draft(tenant_id, project_id)
    service = make_service(tenant_id, project_id, draft, repo_connection=repo)

    run, result = await service.create_nextjs_blog_patch(draft_id=draft.id, tenant_id=tenant_id)

    assert run.status == BlogPublishRunStatus.completed
    assert result.status == BlogPublishResultStatus.patch_created
    assert result.file_path == "content/blog/local-seo-planning-guide.md"
    assert service.repo_repository.patches[-1].proposed_content.startswith("---")
    assert service.repo_repository.patches[-1].status.value == "proposed"

    no_blog_root = tmp_path / "no-blog-patch"
    create_next_fixture(no_blog_root, with_blog=False)
    repo.local_path = str(no_blog_root)

    infra_run, infra_result = await service.create_blog_infrastructure_patch(
        project_id=project_id,
        tenant_id=tenant_id,
        strategy=BlogInfrastructureStrategy.nextjs_markdown,
    )

    assert infra_run.status == BlogPublishRunStatus.completed
    assert infra_result.status == BlogPublishResultStatus.infrastructure_patch_created
    assert any(patch.file_path == "app/blog/page.tsx" for patch in service.repo_repository.patches)


@pytest.mark.asyncio
async def test_static_blogs_ts_infrastructure_detection_and_patch_generation(tmp_path):
    tenant_id = uuid4()
    project_id = uuid4()
    create_static_blogs_fixture(tmp_path)
    repo = make_repo_connection(tenant_id, project_id, tmp_path)
    draft = make_draft(tenant_id, project_id)
    service = make_service(tenant_id, project_id, draft, repo_connection=repo)

    check = await service.check_infrastructure(tenant_id=tenant_id, project_id=project_id)

    assert check.has_blog_index is True
    assert check.has_blog_detail_route is True
    assert check.has_content_directory is True
    assert check.blog_route_path == "/blogs"
    assert check.content_directory == "lib/blogs.ts"
    assert check.recommended_strategy == BlogInfrastructureStrategy.nextjs_markdown

    run, result = await service.create_nextjs_blog_patch(draft_id=draft.id, tenant_id=tenant_id)

    assert run.status == BlogPublishRunStatus.completed
    assert result.status == BlogPublishResultStatus.patch_created
    assert result.file_path == "lib/blogs.ts"
    patch = service.repo_repository.patches[-1]
    assert "seo-agent-local-seo-planning-guide" in patch.proposed_content
    assert "export const blogs" in patch.proposed_content


@pytest.mark.asyncio
async def test_markdown_export_does_not_overwrite_without_flag(tmp_path):
    tenant_id = uuid4()
    project_id = uuid4()
    draft = make_draft(tenant_id, project_id)
    service = make_service(tenant_id, project_id, draft)
    await service.export_markdown(draft_id=draft.id, tenant_id=tenant_id, export_folder_path=str(tmp_path))

    with pytest.raises(BlogPublishingError, match="already exists"):
        await service.export_markdown(draft_id=draft.id, tenant_id=tenant_id, export_folder_path=str(tmp_path))

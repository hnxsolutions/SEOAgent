"""Safe blog publishing, export, and infrastructure patch service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urljoin
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.blog import BlogDraft, BlogDraftStatus
from app.models.blog_publishing import (
    BlogInfrastructureCheck,
    BlogInfrastructureCheckStatus,
    BlogInfrastructureStrategy,
    BlogPublishConnection,
    BlogPublishConnectionStatus,
    BlogPublishMode,
    BlogPublishProvider,
    BlogPublishResult,
    BlogPublishResultStatus,
    BlogPublishRun,
    BlogPublishRunStatus,
)
from app.models.repo_agent import (
    RepoConnection,
    RepoScanRun,
    SeoCodeIssueSeverity,
    SeoCodeIssueSource,
    SeoCodeIssueStatus,
    SeoCodeIssueType,
    SeoCodePatchRisk,
    SeoCodePatchStatus,
    SeoCodePatchType,
)
from app.repo_agent.scanner import (
    IGNORE_DIRS,
    PathSafetyError,
    build_unified_diff,
    content_hash,
    read_repo_text,
    resolve_repo_root,
    safe_child_path,
)
from app.repositories.blog_publishing import BlogPublishingRepository
from app.repositories.repo_agent import RepoAgentRepository

logger = structlog.get_logger(__name__)


class BlogPublishingError(RuntimeError):
    """Raised for safe blog publishing workflow failures."""


@dataclass
class WordPressDraftResult:
    external_id: str
    external_url: Optional[str]


class WordPressClient:
    """Tiny WordPress REST API client using application password auth."""

    def __init__(self, timeout_seconds: float = 20.0):
        self.timeout_seconds = timeout_seconds

    async def test_connection(self, site_url: str, username: str, app_password: str) -> bool:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                self._endpoint(site_url, "/wp-json/wp/v2/users/me"),
                auth=(username, app_password),
            )
            return response.status_code < 400

    async def create_draft(self, site_url: str, username: str, app_password: str, draft: BlogDraft) -> WordPressDraftResult:
        payload = {
            "title": draft.title,
            "slug": draft.slug,
            "content": draft.draft_markdown,
            "status": "draft",
            "excerpt": draft.meta_description or "",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self._endpoint(site_url, "/wp-json/wp/v2/posts"),
                json=payload,
                auth=(username, app_password),
            )
            if response.status_code >= 400:
                raise BlogPublishingError(f"WordPress draft upload failed with HTTP {response.status_code}")
            data = response.json()
        external_id = str(data.get("id") or "")
        if not external_id:
            raise BlogPublishingError("WordPress did not return a post id")
        return WordPressDraftResult(
            external_id=external_id,
            external_url=data.get("link") or data.get("guid", {}).get("rendered"),
        )

    def _endpoint(self, site_url: str, path: str) -> str:
        return urljoin(self._site_url(site_url) + "/", path.lstrip("/"))

    def _site_url(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise BlogPublishingError("WordPress site_url is required")
        if not cleaned.startswith(("http://", "https://")):
            cleaned = f"https://{cleaned}"
        return cleaned.rstrip("/")


class BlogPublishingService:
    """Draft-only publishing/export and reviewable blog infrastructure patch service."""

    def __init__(
        self,
        db: AsyncSession,
        wordpress_client: Optional[WordPressClient] = None,
    ):
        self.db = db
        self.repository = BlogPublishingRepository(db)
        self.repo_repository = RepoAgentRepository(db)
        self.wordpress_client = wordpress_client or WordPressClient()

    async def create_connection(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        provider: BlogPublishProvider,
        site_url: Optional[str] = None,
        repo_connection_id: Optional[UUID] = None,
        export_folder_path: Optional[str] = None,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        auto_upload_drafts_enabled: bool = False,
        auto_publish_enabled: bool = False,
    ) -> BlogPublishConnection:
        if not await self.repository.get_project(project_id, tenant_id):
            raise ValueError("Project not found")
        clean_site_url = self._clean_site_url(site_url)
        encrypted_app_password = None
        status = BlogPublishConnectionStatus.unavailable

        if provider == BlogPublishProvider.wordpress:
            if not clean_site_url or not username or not app_password:
                raise ValueError("WordPress connections require site_url, username, and app_password")
            encrypted_app_password = encrypt_secret(app_password)
            status = BlogPublishConnectionStatus.connected
        elif provider == BlogPublishProvider.nextjs_repo:
            if not repo_connection_id:
                raise ValueError("Next.js repo publishing requires repo_connection_id")
            repo_connection = await self.repository.get_repo_connection(repo_connection_id, tenant_id)
            if not repo_connection:
                raise ValueError("Repository connection not found")
            status = BlogPublishConnectionStatus.connected if repo_connection.local_path else BlogPublishConnectionStatus.unavailable
        elif provider == BlogPublishProvider.markdown_export:
            if not export_folder_path:
                raise ValueError("Markdown export connections require export_folder_path")
            status = BlogPublishConnectionStatus.connected

        connection = await self.repository.create_connection(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "provider": provider,
                "site_url": clean_site_url,
                "repo_connection_id": repo_connection_id,
                "export_folder_path": export_folder_path,
                "username": username,
                "encrypted_app_password": encrypted_app_password,
                "status": status,
                "auto_upload_drafts_enabled": bool(auto_upload_drafts_enabled),
                "auto_publish_enabled": False if not auto_publish_enabled else False,
            }
        )
        await self.db.commit()
        await self.db.refresh(connection)
        return connection

    async def list_connections(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: Optional[BlogPublishProvider] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogPublishConnection]:
        return await self.repository.list_connections(
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
            limit=limit,
            offset=offset,
        )

    async def test_connection(self, connection_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        connection = await self.repository.get_connection(connection_id, tenant_id)
        if not connection:
            raise ValueError("Blog publish connection not found")
        ok = False
        message = "Connection is unavailable."
        try:
            if connection.provider == BlogPublishProvider.wordpress:
                if not connection.site_url or not connection.username or not connection.encrypted_app_password:
                    raise BlogPublishingError("WordPress credentials are incomplete")
                ok = await self.wordpress_client.test_connection(
                    connection.site_url,
                    connection.username,
                    decrypt_secret(connection.encrypted_app_password),
                )
                message = "WordPress connection verified." if ok else "WordPress rejected the credentials."
            elif connection.provider == BlogPublishProvider.markdown_export:
                folder = self._safe_export_folder(connection.export_folder_path)
                ok = folder.exists() or folder.parent.exists()
                message = "Markdown export folder is available." if ok else "Markdown export folder is unavailable."
            elif connection.provider == BlogPublishProvider.nextjs_repo:
                repo = await self._repo_connection_for(connection=connection, tenant_id=tenant_id)
                ok = bool(repo and repo.local_path and Path(repo.local_path).exists())
                message = "Next.js repository path is available." if ok else "Repository path is unavailable."
            await self.repository.set_connection_status(
                connection,
                BlogPublishConnectionStatus.connected if ok else BlogPublishConnectionStatus.failed,
            )
            await self.db.commit()
            return {
                "connection_id": connection.id,
                "provider": connection.provider.value,
                "status": connection.status.value,
                "ok": ok,
                "message": message,
            }
        except Exception as exc:
            await self.repository.set_connection_status(connection, BlogPublishConnectionStatus.failed)
            await self.db.commit()
            logger.warning("Blog publish connection test failed", connection_id=str(connection.id), error=str(exc))
            return {
                "connection_id": connection.id,
                "provider": connection.provider.value,
                "status": BlogPublishConnectionStatus.failed.value,
                "ok": False,
                "message": str(exc),
            }

    async def check_infrastructure(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        repo_connection_id: Optional[UUID] = None,
    ) -> BlogInfrastructureCheck:
        repo = await self._repo_connection_for_project(project_id, tenant_id, repo_connection_id)
        values = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "repo_connection_id": getattr(repo, "id", None),
            "status": BlogInfrastructureCheckStatus.failed,
            "framework_detected": None,
            "has_blog_index": False,
            "has_blog_detail_route": False,
            "has_content_directory": False,
            "blog_route_path": None,
            "content_directory": None,
            "recommended_strategy": BlogInfrastructureStrategy.markdown_export,
            "issues": [],
        }
        try:
            if not repo or not repo.local_path:
                values["issues"] = [{"code": "repo_missing", "message": "No local repository connection is available."}]
            else:
                values.update(self._detect_blog_infrastructure(resolve_repo_root(repo.local_path), repo))
                values["status"] = BlogInfrastructureCheckStatus.completed
        except Exception as exc:
            values["issues"] = [{"code": "detection_failed", "message": str(exc)}]
            values["status"] = BlogInfrastructureCheckStatus.failed
            values["recommended_strategy"] = BlogInfrastructureStrategy.markdown_export
        check = await self.repository.create_infrastructure_check(values)
        await self.db.commit()
        await self.db.refresh(check)
        return check

    async def latest_infrastructure(self, project_id: UUID, tenant_id: UUID) -> Optional[BlogInfrastructureCheck]:
        return await self.repository.latest_infrastructure_check(project_id, tenant_id)

    async def export_markdown(
        self,
        *,
        draft_id: UUID,
        tenant_id: UUID,
        connection_id: Optional[UUID] = None,
        export_folder_path: Optional[str] = None,
        overwrite: bool = False,
    ) -> tuple[BlogPublishRun, BlogPublishResult]:
        draft = await self._approved_draft(draft_id, tenant_id)
        connection = await self._optional_connection(connection_id, tenant_id)
        folder_path = export_folder_path or getattr(connection, "export_folder_path", None)
        if connection and connection.provider != BlogPublishProvider.markdown_export:
            raise ValueError("Connection must be a markdown_export provider")
        if not folder_path:
            raise ValueError("export_folder_path is required")
        run = await self.repository.create_run(
            tenant_id=tenant_id,
            project_id=draft.project_id,
            blog_draft_id=draft.id,
            connection_id=getattr(connection, "id", None),
            provider=BlogPublishProvider.markdown_export,
            mode=BlogPublishMode.markdown_export,
        )
        await self.repository.set_run_status(run, BlogPublishRunStatus.running)
        try:
            folder = self._safe_export_folder(folder_path)
            folder.mkdir(parents=True, exist_ok=True)
            file_path = self._safe_export_file(folder, draft.slug, "md")
            if file_path.exists() and not overwrite:
                raise BlogPublishingError("Markdown file already exists; pass overwrite=true to replace it")
            content = self._draft_markdown_with_frontmatter(draft)
            file_path.write_text(content, encoding="utf-8")
            await self.repository.set_run_status(run, BlogPublishRunStatus.completed)
            result = (
                await self.repository.add_results(
                    [
                        self._result_record(
                            run,
                            draft,
                            BlogPublishResultStatus.file_exported,
                            file_path=str(file_path),
                        )
                    ]
                )
            )[0]
            await self.db.commit()
            await self.db.refresh(run)
            await self.db.refresh(result)
            return run, result
        except Exception as exc:
            await self.repository.set_run_status(run, BlogPublishRunStatus.failed, str(exc))
            result = (
                await self.repository.add_results(
                    [self._result_record(run, draft, BlogPublishResultStatus.failed, file_path=None)]
                )
            )[0]
            await self.db.commit()
            if isinstance(exc, PathSafetyError):
                raise
            raise BlogPublishingError(str(exc)) from exc

    async def create_wordpress_draft(
        self,
        *,
        draft_id: UUID,
        tenant_id: UUID,
        connection_id: UUID,
    ) -> tuple[BlogPublishRun, BlogPublishResult]:
        draft = await self._approved_draft(draft_id, tenant_id)
        connection = await self.repository.get_connection(connection_id, tenant_id)
        if not connection:
            raise ValueError("Blog publish connection not found")
        if connection.provider != BlogPublishProvider.wordpress:
            raise ValueError("Connection must be a wordpress provider")
        if not connection.site_url or not connection.username or not connection.encrypted_app_password:
            raise ValueError("WordPress credentials are incomplete")
        run = await self.repository.create_run(
            tenant_id=tenant_id,
            project_id=draft.project_id,
            blog_draft_id=draft.id,
            connection_id=connection.id,
            provider=BlogPublishProvider.wordpress,
            mode=BlogPublishMode.draft_upload,
        )
        await self.repository.set_run_status(run, BlogPublishRunStatus.running)
        try:
            wp_result = await self.wordpress_client.create_draft(
                connection.site_url,
                connection.username,
                decrypt_secret(connection.encrypted_app_password),
                draft,
            )
            await self.repository.set_run_status(run, BlogPublishRunStatus.completed)
            result = (
                await self.repository.add_results(
                    [
                        self._result_record(
                            run,
                            draft,
                            BlogPublishResultStatus.draft_created,
                            external_id=wp_result.external_id,
                            external_url=wp_result.external_url,
                        )
                    ]
                )
            )[0]
            await self.db.commit()
            await self.db.refresh(run)
            await self.db.refresh(result)
            return run, result
        except Exception as exc:
            await self.repository.set_run_status(run, BlogPublishRunStatus.failed, str(exc))
            result = (
                await self.repository.add_results(
                    [self._result_record(run, draft, BlogPublishResultStatus.failed)]
                )
            )[0]
            await self.db.commit()
            raise BlogPublishingError(str(exc)) from exc

    async def create_nextjs_blog_patch(
        self,
        *,
        draft_id: UUID,
        tenant_id: UUID,
        connection_id: Optional[UUID] = None,
        repo_connection_id: Optional[UUID] = None,
        content_directory: Optional[str] = None,
        extension: str = "md",
        overwrite: bool = False,
    ) -> tuple[BlogPublishRun, BlogPublishResult]:
        draft = await self._approved_draft(draft_id, tenant_id)
        connection = await self._optional_connection(connection_id, tenant_id)
        repo = await self._repo_connection_for(
            connection=connection,
            tenant_id=tenant_id,
            repo_connection_id=repo_connection_id,
            project_id=draft.project_id,
        )
        if not repo or not repo.local_path:
            raise ValueError("Local repository connection is required")
        if connection and connection.provider != BlogPublishProvider.nextjs_repo:
            raise ValueError("Connection must be a nextjs_repo provider")
        run = await self.repository.create_run(
            tenant_id=tenant_id,
            project_id=draft.project_id,
            blog_draft_id=draft.id,
            connection_id=getattr(connection, "id", None),
            provider=BlogPublishProvider.nextjs_repo,
            mode=BlogPublishMode.repo_patch,
        )
        await self.repository.set_run_status(run, BlogPublishRunStatus.running)
        try:
            root = resolve_repo_root(repo.local_path)
            directory = self._content_directory(root, content_directory)
            if self._is_static_blog_data_file(directory):
                run, result = await self._create_static_blog_data_patch(
                    run=run,
                    repo=repo,
                    draft=draft,
                    tenant_id=tenant_id,
                    root=root,
                    data_file=directory,
                    overwrite=overwrite,
                )
                return run, result
            file_rel = f"{directory}/{draft.slug}.{extension}"
            target = safe_child_path(root, file_rel)
            if target.exists() and not overwrite:
                raise BlogPublishingError("Blog file already exists; pass overwrite=true to propose replacing it")
            original = read_repo_text(target) if target.exists() else ""
            proposed = self._draft_markdown_with_frontmatter(draft)
            patch = await self._create_repo_patch(
                repo=repo,
                tenant_id=tenant_id,
                title="Blog draft file proposal",
                description=f"Create a draft blog file for approved BlogDraft {draft.id}.",
                recommended_fix="Review and apply this markdown/MDX blog file through the existing patch workflow.",
                issue_type=SeoCodeIssueType.route_not_in_sitemap,
                severity=SeoCodeIssueSeverity.low,
                patch_type=SeoCodePatchType.semantic_html_safe_suggestion,
                file_path=file_rel,
                original=original,
                proposed=proposed,
                explanation=(
                    "Creates a draft blog content file only. It does not apply the patch, create a PR, "
                    "publish live content, alter layout, or deploy."
                ),
                risk_level=SeoCodePatchRisk.low,
            )
            await self.repository.set_run_status(run, BlogPublishRunStatus.completed)
            result = (
                await self.repository.add_results(
                    [
                        self._result_record(
                            run,
                            draft,
                            BlogPublishResultStatus.patch_created,
                            file_path=file_rel,
                            patch_id=patch.id,
                        )
                    ]
                )
            )[0]
            await self.db.commit()
            await self.db.refresh(run)
            await self.db.refresh(result)
            return run, result
        except Exception as exc:
            await self.repository.set_run_status(run, BlogPublishRunStatus.failed, str(exc))
            result = (
                await self.repository.add_results(
                    [self._result_record(run, draft, BlogPublishResultStatus.failed)]
                )
            )[0]
            await self.db.commit()
            if isinstance(exc, PathSafetyError):
                raise
            raise BlogPublishingError(str(exc)) from exc

    async def create_blog_infrastructure_patch(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        connection_id: Optional[UUID] = None,
        repo_connection_id: Optional[UUID] = None,
        strategy: BlogInfrastructureStrategy = BlogInfrastructureStrategy.nextjs_markdown,
    ) -> tuple[BlogPublishRun, BlogPublishResult]:
        connection = await self._optional_connection(connection_id, tenant_id)
        repo = await self._repo_connection_for(
            connection=connection,
            tenant_id=tenant_id,
            repo_connection_id=repo_connection_id,
            project_id=project_id,
        )
        if not repo or not repo.local_path:
            raise ValueError("Local repository connection is required")
        run = await self.repository.create_run(
            tenant_id=tenant_id,
            project_id=project_id,
            blog_draft_id=None,
            connection_id=getattr(connection, "id", None),
            provider=BlogPublishProvider.nextjs_repo,
            mode=BlogPublishMode.infrastructure_patch,
        )
        await self.repository.set_run_status(run, BlogPublishRunStatus.running)
        try:
            root = resolve_repo_root(repo.local_path)
            patch_records = await self._create_infrastructure_patches(repo, tenant_id, root, strategy)
            first_patch = patch_records[0] if patch_records else None
            await self.repository.set_run_status(run, BlogPublishRunStatus.completed)
            result = (
                await self.repository.add_results(
                    [
                        self._result_record(
                            run,
                            None,
                            BlogPublishResultStatus.infrastructure_patch_created,
                            file_path=getattr(first_patch, "file_path", None),
                            patch_id=getattr(first_patch, "id", None),
                            title="Blog infrastructure patch proposal",
                            slug="blog-infrastructure",
                        )
                    ]
                )
            )[0]
            await self.db.commit()
            await self.db.refresh(run)
            await self.db.refresh(result)
            return run, result
        except Exception as exc:
            await self.repository.set_run_status(run, BlogPublishRunStatus.failed, str(exc))
            result = (
                await self.repository.add_results(
                    [
                        self._result_record(
                            run,
                            None,
                            BlogPublishResultStatus.failed,
                            title="Blog infrastructure patch proposal",
                            slug="blog-infrastructure",
                        )
                    ]
                )
            )[0]
            await self.db.commit()
            if isinstance(exc, PathSafetyError):
                raise
            raise BlogPublishingError(str(exc)) from exc

    async def get_run(self, run_id: UUID, tenant_id: UUID) -> Optional[BlogPublishRun]:
        return await self.repository.get_run(run_id, tenant_id)

    async def get_result(self, run_id: UUID, tenant_id: UUID) -> Optional[BlogPublishResult]:
        return await self.repository.get_result_for_run(run_id, tenant_id)

    async def _approved_draft(self, draft_id: UUID, tenant_id: UUID) -> BlogDraft:
        draft = await self.repository.get_draft(draft_id, tenant_id)
        if not draft:
            raise ValueError("Blog draft not found")
        if self._enum_value(draft.status) != BlogDraftStatus.approved.value:
            raise ValueError("Blog draft must be approved before publishing/export")
        return draft

    async def _optional_connection(
        self,
        connection_id: Optional[UUID],
        tenant_id: UUID,
    ) -> Optional[BlogPublishConnection]:
        if not connection_id:
            return None
        connection = await self.repository.get_connection(connection_id, tenant_id)
        if not connection:
            raise ValueError("Blog publish connection not found")
        return connection

    async def _repo_connection_for(
        self,
        *,
        connection: Optional[BlogPublishConnection] = None,
        tenant_id: UUID,
        repo_connection_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
    ) -> Optional[RepoConnection]:
        target_id = repo_connection_id or getattr(connection, "repo_connection_id", None)
        if target_id:
            return await self.repository.get_repo_connection(target_id, tenant_id)
        if project_id:
            return await self.repository.latest_repo_connection(project_id, tenant_id)
        return None

    async def _repo_connection_for_project(
        self,
        project_id: UUID,
        tenant_id: UUID,
        repo_connection_id: Optional[UUID] = None,
    ) -> Optional[RepoConnection]:
        if repo_connection_id:
            repo = await self.repository.get_repo_connection(repo_connection_id, tenant_id)
            if not repo:
                raise ValueError("Repository connection not found")
            return repo
        return await self.repository.latest_repo_connection(project_id, tenant_id)

    def _detect_blog_infrastructure(self, root: Path, repo: RepoConnection) -> dict:
        blog_index_paths = ["app/blog/page.tsx", "app/blogs/page.tsx", "pages/blog/index.tsx", "pages/blogs/index.tsx"]
        blog_detail_paths = [
            "app/blog/[slug]/page.tsx",
            "app/blogs/[slug]/page.tsx",
            "pages/blog/[slug].tsx",
            "pages/blogs/[slug].tsx",
        ]
        content_sources = ["content/blog", "src/content/blog", "posts", "lib/blogs.ts", "src/lib/blogs.ts"]
        found_blog_index = next((path for path in blog_index_paths if safe_child_path(root, path).exists()), None)
        found_blog_detail = next((path for path in blog_detail_paths if safe_child_path(root, path).exists()), None)
        found_content_dir = next((path for path in content_sources if safe_child_path(root, path).exists()), None)
        has_blog_index = bool(found_blog_index)
        has_blog_detail_route = bool(found_blog_detail)
        if found_content_dir and found_content_dir.endswith(".ts"):
            content_file = safe_child_path(root, found_content_dir)
            content = read_repo_text(content_file)
            if not re.search(r"export\s+const\s+blogs\s*:", content) or "getBlogBySlug" not in content:
                found_content_dir = None
        mdx_detected = self._repo_has_mdx_support(root)
        sitemap_support = safe_child_path(root, "app/sitemap.ts").exists() or safe_child_path(root, "public/sitemap.xml").exists()
        issues = []
        if not has_blog_index:
            issues.append({"code": "missing_blog_index", "message": "No blog index route was found."})
        if not has_blog_detail_route:
            issues.append({"code": "missing_blog_detail", "message": "No blog detail route was found."})
        if not found_content_dir:
            issues.append({"code": "missing_content_directory", "message": "No blog content directory was found."})
        if not sitemap_support:
            issues.append({"code": "missing_sitemap_support", "message": "No sitemap file was found for route inclusion."})

        if has_blog_index and has_blog_detail_route and found_content_dir:
            strategy = BlogInfrastructureStrategy.nextjs_mdx if mdx_detected and not found_content_dir.endswith(".ts") else BlogInfrastructureStrategy.nextjs_markdown
        elif (repo.framework or "").startswith("nextjs") or safe_child_path(root, "package.json").exists():
            strategy = BlogInfrastructureStrategy.create_blog_infrastructure
        else:
            strategy = BlogInfrastructureStrategy.markdown_export

        return {
            "framework_detected": repo.framework or ("nextjs_app_router" if safe_child_path(root, "app").exists() else "unknown"),
            "has_blog_index": has_blog_index,
            "has_blog_detail_route": has_blog_detail_route,
            "has_content_directory": bool(found_content_dir),
            "blog_route_path": self._blog_route_from_path(found_blog_index) if found_blog_index else None,
            "content_directory": found_content_dir,
            "recommended_strategy": strategy,
            "issues": issues,
        }

    async def _create_static_blog_data_patch(
        self,
        *,
        run: BlogPublishRun,
        repo: RepoConnection,
        draft: BlogDraft,
        tenant_id: UUID,
        root: Path,
        data_file: str,
        overwrite: bool,
    ) -> tuple[BlogPublishRun, BlogPublishResult]:
        target = safe_child_path(root, data_file)
        original = read_repo_text(target)
        if f'slug: "{draft.slug}"' in original and not overwrite:
            raise BlogPublishingError("Blog slug already exists in the static blog data file")
        proposed = self._insert_static_blog_entry(original, draft)
        if proposed == original:
            raise BlogPublishingError("Static blog data file could not be patched safely")
        patch = await self._create_repo_patch(
            repo=repo,
            tenant_id=tenant_id,
            title="Static blog data draft proposal",
            description=f"Add approved BlogDraft {draft.id} to the existing static blog data source.",
            recommended_fix="Review and apply this static blog entry through the existing patch workflow.",
            issue_type=SeoCodeIssueType.route_not_in_sitemap,
            severity=SeoCodeIssueSeverity.low,
            patch_type=SeoCodePatchType.semantic_html_safe_suggestion,
            file_path=data_file,
            original=original,
            proposed=proposed,
            explanation=(
                "Adds one draft entry to the existing static blog data source. It does not apply the patch, "
                "create a PR, publish live content, alter layout, or deploy."
            ),
            risk_level=SeoCodePatchRisk.low,
        )
        await self.repository.set_run_status(run, BlogPublishRunStatus.completed)
        result = (
            await self.repository.add_results(
                [
                    self._result_record(
                        run,
                        draft,
                        BlogPublishResultStatus.patch_created,
                        file_path=data_file,
                        patch_id=patch.id,
                    )
                ]
            )
        )[0]
        await self.db.commit()
        await self.db.refresh(run)
        await self.db.refresh(result)
        return run, result

    def _insert_static_blog_entry(self, original: str, draft: BlogDraft) -> str:
        match = re.search(r"export\s+const\s+blogs\s*:\s*Blog\[\]\s*=\s*\[", original)
        if not match:
            return original
        array_open = original.rfind("[", 0, match.end())
        array_close = self._find_matching_delimiter(original, array_open, "[", "]") if array_open >= 0 else None
        if array_close is None:
            return original
        entry = self._static_blog_entry(draft)
        return original[:array_close] + entry + original[array_close:]

    def _static_blog_entry(self, draft: BlogDraft) -> str:
        today = datetime.utcnow().date().isoformat()
        content_blocks = self._markdown_to_blog_blocks(draft.draft_markdown or "")
        tags = self._tags_from_draft(draft)
        return (
            "  {\n"
            f"    id: \"seo-agent-{self._slugify(draft.slug)}\",\n"
            f"    slug: {json.dumps(self._slugify(draft.slug))},\n"
            f"    title: {json.dumps(draft.title or 'Draft Blog', ensure_ascii=False)},\n"
            f"    metaDescription: {json.dumps(draft.meta_description or '', ensure_ascii=False)},\n"
            f"    excerpt: {json.dumps(self._excerpt_from_markdown(draft.draft_markdown or draft.meta_description or ''), ensure_ascii=False)},\n"
            "    category: \"PCD Pharma\",\n"
            "    readTime: \"5 min read\",\n"
            f"    publishedAt: \"{today}\",\n"
            f"    updatedAt: \"{today}\",\n"
            "    author: \"Novakos Healthcare\",\n"
            f"    tags: {json.dumps(tags, ensure_ascii=False)},\n"
            "    image: pexelsImage({\n"
            "      id: \"8657294\",\n"
            "      alt: \"Organized pharmacy shelves for B2B pharmaceutical distribution\",\n"
            "      creditUrl:\n"
            "        \"https://www.pexels.com/photo/a-pharmacy-shelf-filled-with-lots-of-medicine-bottles-8657294/\",\n"
            "    }),\n"
            f"    content: {json.dumps(content_blocks, ensure_ascii=False, indent=6).replace(chr(10), chr(10) + '    ')},\n"
            "  },\n"
        )

    def _markdown_to_blog_blocks(self, markdown: str) -> List[dict]:
        blocks: List[dict] = []
        paragraphs: List[str] = []
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line:
                if paragraphs:
                    blocks.append({"type": "paragraph", "text": " ".join(paragraphs)})
                    paragraphs = []
                continue
            if line.startswith("## "):
                if paragraphs:
                    blocks.append({"type": "paragraph", "text": " ".join(paragraphs)})
                    paragraphs = []
                blocks.append({"type": "heading", "level": 2, "text": line[3:].strip()})
            elif line.startswith("### "):
                if paragraphs:
                    blocks.append({"type": "paragraph", "text": " ".join(paragraphs)})
                    paragraphs = []
                blocks.append({"type": "heading", "level": 3, "text": line[4:].strip()})
            elif not line.startswith("# "):
                paragraphs.append(line.lstrip("- ").strip())
        if paragraphs:
            blocks.append({"type": "paragraph", "text": " ".join(paragraphs)})
        return blocks[:12] or [{"type": "paragraph", "text": "Draft body requires editorial review before publishing."}]

    def _tags_from_draft(self, draft: BlogDraft) -> List[str]:
        text = f"{draft.title or ''} {draft.meta_description or ''}".lower()
        tags = ["PCD Pharma", "Pharma Distribution"]
        if "haryana" in text:
            tags.append("Haryana")
        if "wholesale" in text:
            tags.append("Wholesale Medicine")
        return tags[:5]

    def _excerpt_from_markdown(self, markdown: str) -> str:
        text = re.sub(r"#+\s*", "", markdown or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:220] or "Draft blog prepared for editorial review."

    def _is_static_blog_data_file(self, value: str) -> bool:
        return value.replace("\\", "/").endswith(".ts")

    def _blog_route_from_path(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        clean = value.replace("\\", "/")
        if "/blogs/" in f"/{clean}" or clean.startswith("app/blogs") or clean.startswith("pages/blogs"):
            return "/blogs"
        return "/blog"

    def _find_matching_delimiter(self, content: str, start: int, open_char: str, close_char: str) -> Optional[int]:
        depth = 0
        quote: Optional[str] = None
        escaped = False
        for index in range(start, len(content)):
            char = content[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in {"'", '"', "`"}:
                quote = char
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return index
        return None

    def _repo_has_mdx_support(self, root: Path) -> bool:
        for rel_path in ["next.config.mjs", "next.config.js", "next.config.ts", "package.json"]:
            path = safe_child_path(root, rel_path)
            if path.exists() and re.search(r"mdx|@next/mdx|next-mdx", read_repo_text(path), re.IGNORECASE):
                return True
        return any(path.suffix.lower() == ".mdx" for path in root.rglob("*") if not self._ignored(path, root))

    async def _create_repo_patch(
        self,
        *,
        repo: RepoConnection,
        tenant_id: UUID,
        title: str,
        description: str,
        recommended_fix: str,
        issue_type: SeoCodeIssueType,
        severity: SeoCodeIssueSeverity,
        patch_type: SeoCodePatchType,
        file_path: str,
        original: str,
        proposed: str,
        explanation: str,
        risk_level: SeoCodePatchRisk,
    ):
        run = await self._new_patch_scan(repo)
        issues = await self.repo_repository.add_issues(
            [
                {
                    "tenant_id": repo.tenant_id,
                    "project_id": repo.project_id,
                    "repo_connection_id": repo.id,
                    "scan_run_id": run.id,
                    "file_id": None,
                    "issue_type": issue_type,
                    "severity": severity,
                    "title": title[:255],
                    "description": description,
                    "recommended_fix": recommended_fix,
                    "source_reference_type": SeoCodeIssueSource.repo_scan,
                    "source_reference_id": None,
                    "status": SeoCodeIssueStatus.open,
                }
            ]
        )
        patch = (
            await self.repo_repository.add_patches(
                [
                    {
                        "tenant_id": repo.tenant_id,
                        "project_id": repo.project_id,
                        "repo_connection_id": repo.id,
                        "scan_run_id": run.id,
                        "issue_id": issues[0].id,
                        "file_path": file_path,
                        "patch_type": patch_type,
                        "original_content_hash": content_hash(original),
                        "diff_text": build_unified_diff(file_path, original, proposed),
                        "proposed_content": proposed,
                        "explanation": explanation,
                        "risk_level": risk_level,
                        "status": SeoCodePatchStatus.proposed,
                    }
                ]
            )
        )[0]
        await self.repo_repository.finish_scan(
            run,
            repo.framework or "nextjs_app_router",
            files_scanned=0,
            issues_found=len(issues),
            patches_created=1,
        )
        return patch

    async def _create_infrastructure_patches(
        self,
        repo: RepoConnection,
        tenant_id: UUID,
        root: Path,
        strategy: BlogInfrastructureStrategy,
    ) -> Sequence[Any]:
        run = await self._new_patch_scan(repo)
        records = []
        issue_records = []
        specs = self._infrastructure_patch_specs(root, strategy)
        for spec in specs:
            target = safe_child_path(root, spec["file_path"])
            original = read_repo_text(target) if target.exists() else ""
            if target.exists() and original.strip():
                continue
            issue_records.append(
                {
                    "tenant_id": repo.tenant_id,
                    "project_id": repo.project_id,
                    "repo_connection_id": repo.id,
                    "scan_run_id": run.id,
                    "file_id": None,
                    "issue_type": spec["issue_type"],
                    "severity": spec["severity"],
                    "title": spec["title"][:255],
                    "description": spec["description"],
                    "recommended_fix": "Review and apply the proposed blog infrastructure patch through the existing repo patch workflow.",
                    "source_reference_type": SeoCodeIssueSource.repo_scan,
                    "source_reference_id": None,
                    "status": SeoCodeIssueStatus.open,
                }
            )
            records.append((spec, original))
        issues = await self.repo_repository.add_issues(issue_records)
        patch_records = []
        for issue, (spec, original) in zip(issues, records):
            patch_records.append(
                {
                    "tenant_id": repo.tenant_id,
                    "project_id": repo.project_id,
                    "repo_connection_id": repo.id,
                    "scan_run_id": run.id,
                    "issue_id": issue.id,
                    "file_path": spec["file_path"],
                    "patch_type": spec["patch_type"],
                    "original_content_hash": content_hash(original),
                    "diff_text": build_unified_diff(spec["file_path"], original, spec["proposed"]),
                    "proposed_content": spec["proposed"],
                    "explanation": spec["explanation"],
                    "risk_level": spec["risk_level"],
                    "status": SeoCodePatchStatus.proposed,
                }
            )
        patches = await self.repo_repository.add_patches(patch_records)
        await self.repo_repository.finish_scan(
            run,
            repo.framework or "nextjs_app_router",
            files_scanned=0,
            issues_found=len(issues),
            patches_created=len(patches),
        )
        return patches

    async def _new_patch_scan(self, repo: RepoConnection) -> RepoScanRun:
        run = await self.repo_repository.create_scan_run(repo)
        await self.repo_repository.set_scan_status(run, status=run.status)
        return run

    def _infrastructure_patch_specs(self, root: Path, strategy: BlogInfrastructureStrategy) -> List[Dict[str, Any]]:
        extension = "mdx" if strategy == BlogInfrastructureStrategy.nextjs_mdx else "md"
        content_dir = "content/blog"
        loader = (
            "import fs from \"fs\";\n"
            "import path from \"path\";\n\n"
            "export type BlogPost = {\n"
            "  slug: string;\n"
            "  title: string;\n"
            "  metaTitle?: string;\n"
            "  metaDescription?: string;\n"
            "  content: string;\n"
            "};\n\n"
            "const blogDir = path.join(process.cwd(), \"content\", \"blog\");\n\n"
            "export function listBlogPosts(): BlogPost[] {\n"
            "  if (!fs.existsSync(blogDir)) return [];\n"
            "  return fs.readdirSync(blogDir)\n"
            f"    .filter((file) => file.endsWith(\".{extension}\"))\n"
            "    .map((file) => {\n"
            "      const slug = file.replace(/\\.(md|mdx)$/, \"\");\n"
            "      const content = fs.readFileSync(path.join(blogDir, file), \"utf8\");\n"
            "      const title = content.match(/^title: \"?([^\"\\n]+)\"?/m)?.[1] ?? slug.replace(/-/g, \" \");\n"
            "      return { slug, title, content };\n"
            "    });\n"
            "}\n\n"
            "export function getBlogPost(slug: string): BlogPost | null {\n"
            "  return listBlogPosts().find((post) => post.slug === slug) ?? null;\n"
            "}\n"
        )
        index_page = (
            "import Link from \"next/link\";\n"
            "import { listBlogPosts } from \"@/lib/blog\";\n\n"
            "export const metadata = {\n"
            "  title: \"Blog\",\n"
            "  description: \"Draft and published articles from the team.\",\n"
            "};\n\n"
            "export default function BlogIndexPage() {\n"
            "  const posts = listBlogPosts();\n"
            "  return (\n"
            "    <main>\n"
            "      <h1>Blog</h1>\n"
            "      <ul>\n"
            "        {posts.map((post) => (\n"
            "          <li key={post.slug}>\n"
            "            <Link href={`/blog/${post.slug}`}>{post.title}</Link>\n"
            "          </li>\n"
            "        ))}\n"
            "      </ul>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
        )
        detail_page = (
            "import { notFound } from \"next/navigation\";\n"
            "import { getBlogPost } from \"@/lib/blog\";\n\n"
            "export function generateMetadata({ params }: { params: { slug: string } }) {\n"
            "  const post = getBlogPost(params.slug);\n"
            "  if (!post) return {};\n"
            "  return { title: post.title };\n"
            "}\n\n"
            "export default function BlogDetailPage({ params }: { params: { slug: string } }) {\n"
            "  const post = getBlogPost(params.slug);\n"
            "  if (!post) notFound();\n"
            "  const jsonLd = {\n"
            "    \"@context\": \"https://schema.org\",\n"
            "    \"@type\": \"BlogPosting\",\n"
            "    headline: post.title,\n"
            "  };\n"
            "  return (\n"
            "    <main>\n"
            "      <script type=\"application/ld+json\" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />\n"
            "      <article>\n"
            "        <h1>{post.title}</h1>\n"
            "        <pre>{post.content}</pre>\n"
            "      </article>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
        )
        readme = "# Blog drafts\n\nApproved blog draft files generated by the SEO Agent are proposed here for review.\n"
        base = {
            "severity": SeoCodeIssueSeverity.medium,
            "patch_type": SeoCodePatchType.semantic_html_safe_suggestion,
            "risk_level": SeoCodePatchRisk.medium,
            "explanation": (
                "Proposes reviewable blog infrastructure. It does not apply patches, alter homepage/navigation, "
                "publish content, create a PR, deploy, or merge."
            ),
        }
        return [
            {
                **base,
                "file_path": "lib/blog.ts",
                "issue_type": SeoCodeIssueType.missing_schema,
                "title": "Missing blog content loader",
                "description": "No simple blog content loader was found.",
                "proposed": loader,
            },
            {
                **base,
                "file_path": "app/blog/page.tsx",
                "issue_type": SeoCodeIssueType.route_not_in_sitemap,
                "title": "Missing blog index route",
                "description": "No App Router blog index route was found.",
                "proposed": index_page,
            },
            {
                **base,
                "file_path": "app/blog/[slug]/page.tsx",
                "issue_type": SeoCodeIssueType.route_not_in_sitemap,
                "title": "Missing blog detail route",
                "description": "No App Router blog detail route was found.",
                "proposed": detail_page,
            },
            {
                **base,
                "file_path": f"{content_dir}/README.md",
                "issue_type": SeoCodeIssueType.route_not_in_sitemap,
                "title": "Missing blog content directory",
                "description": "No content/blog directory was found.",
                "proposed": readme,
            },
        ]

    def _draft_markdown_with_frontmatter(self, draft: BlogDraft) -> str:
        frontmatter = {
            "title": draft.title,
            "slug": draft.slug,
            "meta_title": draft.meta_title,
            "meta_description": draft.meta_description,
            "created_at": datetime.utcnow().isoformat(),
            "status": "draft",
            "faq_json": draft.faq_json or [],
            "schema_json": draft.schema_json or {},
            "knowledge_sources_used": draft.knowledge_sources_used or [],
        }
        lines = ["---"]
        for key, value in frontmatter.items():
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        lines.append("---")
        return "\n".join(lines) + "\n\n" + (draft.draft_markdown or "").strip() + "\n"

    def _result_record(
        self,
        run: BlogPublishRun,
        draft: Optional[BlogDraft],
        status: BlogPublishResultStatus,
        *,
        external_id: Optional[str] = None,
        external_url: Optional[str] = None,
        file_path: Optional[str] = None,
        patch_id: Optional[UUID] = None,
        title: Optional[str] = None,
        slug: Optional[str] = None,
    ) -> dict:
        return {
            "tenant_id": run.tenant_id,
            "project_id": run.project_id,
            "publish_run_id": run.id,
            "blog_draft_id": getattr(draft, "id", None),
            "provider": run.provider,
            "status": status,
            "external_id": external_id,
            "external_url": external_url,
            "file_path": file_path,
            "patch_id": patch_id,
            "pr_id": None,
            "title": title or getattr(draft, "title", None),
            "slug": slug or getattr(draft, "slug", None),
        }

    def _safe_export_folder(self, folder_path: Optional[str]) -> Path:
        if not folder_path:
            raise PathSafetyError("export_folder_path is required")
        raw = str(folder_path).strip().strip('"')
        if not raw:
            raise PathSafetyError("export_folder_path is required")
        folder = Path(raw).expanduser().resolve()
        parts = set(folder.parts)
        if parts.intersection(IGNORE_DIRS):
            raise PathSafetyError("Export folder cannot be inside an ignored build or dependency directory")
        return folder

    def _safe_export_file(self, folder: Path, slug: str, extension: str) -> Path:
        clean_slug = self._slugify(slug)
        file_path = (folder / f"{clean_slug}.{extension}").resolve()
        if not file_path.is_relative_to(folder):
            raise PathSafetyError("Export path escapes the configured folder")
        return file_path

    def _content_directory(self, root: Path, preferred: Optional[str]) -> str:
        candidates = [preferred, "content/blog", "src/content/blog", "posts", "lib/blogs.ts", "src/lib/blogs.ts"]
        for candidate in [item for item in candidates if item]:
            clean = str(candidate).replace("\\", "/").strip("/")
            path = safe_child_path(root, clean)
            if self._ignored(path, root):
                raise PathSafetyError("Blog content directory targets an ignored folder")
            if path.exists() or candidate == preferred:
                return clean
        return "content/blog"

    def _ignored(self, path: Path, root: Path) -> bool:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            return True
        return any(part in IGNORE_DIRS for part in parts)

    def _clean_site_url(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not cleaned.startswith(("http://", "https://")):
            cleaned = f"https://{cleaned}"
        return cleaned.rstrip("/")

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
        if not slug or slug in {".", ".."}:
            raise PathSafetyError("Blog draft slug is not safe")
        return slug[:120]

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)

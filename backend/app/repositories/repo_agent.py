"""Repository layer for SEO code-agent repository scanning and patches."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_optimization import ContentOptimizationSuggestion, ContentOptimizationSuggestionStatus
from app.models.geo_aeo import GeoAeoRecommendation
from app.models.planner import SeoTask, SeoTaskStatus, SeoTaskType
from app.models.project import Project
from app.models.repo_agent import (
    PatchApplyResult,
    PatchApplyResultStatus,
    PatchApplyRun,
    PatchApplyRunStatus,
    PatchValidationStatus,
    PullRequestProvider,
    PullRequestRecord,
    PullRequestStatus,
    RepoArchitectureProfile,
    RepoConnection,
    RepoConnectionStatus,
    RepoFile,
    RepoProvider,
    RepoScanRun,
    RepoScanRunStatus,
    SeoCodeIssue,
    SeoCodeIssueStatus,
    SeoCodePatch,
    SeoCodePatchStatus,
)
from app.models.search_console import SearchConsoleOpportunity, SearchConsoleOpportunityStatus

POSTGRES_TEXT_CODECS = {
    "UTF8": "utf-8",
    "UNICODE": "utf-8",
    "WIN1252": "cp1252",
    "LATIN1": "latin1",
}


class RepoAgentRepository:
    """Database access for repository SEO code-agent records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_connection(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        provider: RepoProvider,
        repo_url: Optional[str],
        local_path: Optional[str],
        default_branch: Optional[str],
        framework: Optional[str],
        status: RepoConnectionStatus,
    ) -> RepoConnection:
        encoding = await self._server_encoding()
        connection = RepoConnection(
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
            repo_url=self._sanitize_text(repo_url, encoding),
            local_path=self._sanitize_text(local_path, encoding),
            default_branch=self._sanitize_text(default_branch, encoding),
            framework=self._sanitize_text(framework, encoding),
            status=status,
        )
        self.db.add(connection)
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def list_connections(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[RepoConnection]:
        query = select(RepoConnection).where(RepoConnection.tenant_id == tenant_id)
        if project_id:
            query = query.where(RepoConnection.project_id == project_id)
        query = query.order_by(RepoConnection.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_connection(self, connection_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[RepoConnection]:
        query = select(RepoConnection).where(RepoConnection.id == connection_id)
        if tenant_id:
            query = query.where(RepoConnection.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_connection_status(
        self,
        connection: RepoConnection,
        status: RepoConnectionStatus,
        framework: Optional[str] = None,
    ) -> RepoConnection:
        connection.status = status
        if framework:
            connection.framework = framework
        connection.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def create_scan_run(self, connection: RepoConnection) -> RepoScanRun:
        run = RepoScanRun(
            tenant_id=connection.tenant_id,
            project_id=connection.project_id,
            repo_connection_id=connection.id,
            status=RepoScanRunStatus.queued,
            files_scanned=0,
            issues_found=0,
            patches_created=0,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_scan_run(self, scan_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[RepoScanRun]:
        query = select(RepoScanRun).where(RepoScanRun.id == scan_id)
        if tenant_id:
            query = query.where(RepoScanRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_scan_status(
        self,
        run: RepoScanRun,
        status: RepoScanRunStatus,
        error_message: Optional[str] = None,
        framework_detected: Optional[str] = None,
    ) -> RepoScanRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if framework_detected:
            run.framework_detected = framework_detected
        if status == RepoScanRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {RepoScanRunStatus.completed, RepoScanRunStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def finish_scan(
        self,
        run: RepoScanRun,
        framework_detected: str,
        files_scanned: int,
        issues_found: int,
        patches_created: Optional[int] = None,
    ) -> RepoScanRun:
        run.framework_detected = framework_detected
        run.files_scanned = files_scanned
        run.issues_found = issues_found
        if patches_created is not None:
            run.patches_created = patches_created
        run.status = RepoScanRunStatus.completed
        run.completed_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def add_files(self, records: Iterable[dict]) -> List[RepoFile]:
        files = []
        encoding = await self._server_encoding()
        for values in records:
            file = RepoFile(**self._sanitize_value(values, encoding))
            self.db.add(file)
            files.append(file)
        await self.db.flush()
        for file in files:
            await self.db.refresh(file)
        return files

    async def list_files(self, scan_id: UUID, tenant_id: UUID, limit: int = 500, offset: int = 0) -> List[RepoFile]:
        result = await self.db.execute(
            select(RepoFile)
            .where(RepoFile.scan_run_id == scan_id, RepoFile.tenant_id == tenant_id)
            .order_by(RepoFile.file_path.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_issues(self, records: Iterable[dict]) -> List[SeoCodeIssue]:
        issues = []
        encoding = await self._server_encoding()
        for values in records:
            issue = SeoCodeIssue(**self._sanitize_value(values, encoding))
            self.db.add(issue)
            issues.append(issue)
        await self.db.flush()
        for issue in issues:
            await self.db.refresh(issue)
        return issues

    async def list_issues(
        self,
        scan_id: UUID,
        tenant_id: UUID,
        status: Optional[SeoCodeIssueStatus] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[SeoCodeIssue]:
        query = select(SeoCodeIssue).where(SeoCodeIssue.scan_run_id == scan_id, SeoCodeIssue.tenant_id == tenant_id)
        if status:
            query = query.where(SeoCodeIssue.status == status)
        query = query.order_by(SeoCodeIssue.severity.desc(), SeoCodeIssue.created_at.asc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_issue(self, issue_id: UUID, tenant_id: UUID) -> Optional[SeoCodeIssue]:
        result = await self.db.execute(
            select(SeoCodeIssue).where(SeoCodeIssue.id == issue_id, SeoCodeIssue.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def existing_patch(
        self,
        issue_id: UUID,
        file_path: str,
        patch_type,
        original_content_hash: str,
    ) -> Optional[SeoCodePatch]:
        result = await self.db.execute(
            select(SeoCodePatch).where(
                SeoCodePatch.issue_id == issue_id,
                SeoCodePatch.file_path == file_path,
                SeoCodePatch.patch_type == patch_type,
                SeoCodePatch.original_content_hash == original_content_hash,
            )
        )
        return result.scalar_one_or_none()

    async def add_patches(self, records: Iterable[dict]) -> List[SeoCodePatch]:
        patches = []
        encoding = await self._server_encoding()
        for values in records:
            patch = SeoCodePatch(**self._sanitize_value(values, encoding))
            self.db.add(patch)
            patches.append(patch)
        await self.db.flush()
        for patch in patches:
            await self.db.refresh(patch)
        return patches

    async def create_architecture_profile(self, run: RepoScanRun, values: dict) -> RepoArchitectureProfile:
        encoding = await self._server_encoding()
        profile = RepoArchitectureProfile(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            repo_connection_id=run.repo_connection_id,
            scan_run_id=run.id,
            **self._sanitize_value(values, encoding),
        )
        self.db.add(profile)
        await self.db.flush()
        await self.db.refresh(profile)
        return profile

    async def get_architecture_profile(
        self,
        scan_id: UUID,
        tenant_id: UUID,
    ) -> Optional[RepoArchitectureProfile]:
        result = await self.db.execute(
            select(RepoArchitectureProfile)
            .where(RepoArchitectureProfile.scan_run_id == scan_id, RepoArchitectureProfile.tenant_id == tenant_id)
            .order_by(RepoArchitectureProfile.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_patches(
        self,
        scan_id: UUID,
        tenant_id: UUID,
        status: Optional[SeoCodePatchStatus] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[SeoCodePatch]:
        query = select(SeoCodePatch).where(SeoCodePatch.scan_run_id == scan_id, SeoCodePatch.tenant_id == tenant_id)
        if status:
            query = query.where(SeoCodePatch.status == status)
        query = query.order_by(SeoCodePatch.created_at.asc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_patch(self, patch_id: UUID, tenant_id: UUID) -> Optional[SeoCodePatch]:
        result = await self.db.execute(
            select(SeoCodePatch).where(SeoCodePatch.id == patch_id, SeoCodePatch.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def set_patch_status(self, patch: SeoCodePatch, status: SeoCodePatchStatus) -> SeoCodePatch:
        patch.status = status
        patch.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(patch)
        return patch

    async def update_scan_patch_count(self, run: RepoScanRun, patches_created: int) -> RepoScanRun:
        run.patches_created = patches_created
        run.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def _server_encoding(self) -> str:
        encoding = self.db.info.get("server_encoding")
        if encoding:
            return str(encoding)
        result = await self.db.execute(text("select current_setting('server_encoding')"))
        encoding = str(result.scalar_one_or_none() or "UTF8").upper()
        self.db.info["server_encoding"] = encoding
        return encoding

    def _sanitize_value(self, value, encoding: str):
        if isinstance(value, str):
            return self._sanitize_text(value, encoding)
        if isinstance(value, list):
            return [self._sanitize_value(item, encoding) for item in value]
        if isinstance(value, tuple):
            return tuple(self._sanitize_value(item, encoding) for item in value)
        if isinstance(value, dict):
            return {
                self._sanitize_value(key, encoding) if isinstance(key, str) else key:
                self._sanitize_value(item, encoding)
                for key, item in value.items()
            }
        return value

    def _sanitize_text(self, value: Optional[str], encoding: str) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.replace("\x00", "")
        if encoding.upper() in {"UTF8", "UNICODE"}:
            return cleaned
        codec = POSTGRES_TEXT_CODECS.get(encoding.upper(), encoding.lower())
        try:
            return cleaned.encode(codec, errors="ignore").decode(codec, errors="ignore")
        except LookupError:
            return cleaned.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")

    async def create_apply_run(self, run: RepoScanRun, branch_name: str, patches_requested: int) -> PatchApplyRun:
        apply_run = PatchApplyRun(
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
        )
        self.db.add(apply_run)
        await self.db.flush()
        await self.db.refresh(apply_run)
        return apply_run

    async def get_apply_run(self, apply_run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[PatchApplyRun]:
        query = select(PatchApplyRun).where(PatchApplyRun.id == apply_run_id)
        if tenant_id:
            query = query.where(PatchApplyRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_apply_run_status(
        self,
        apply_run: PatchApplyRun,
        status: PatchApplyRunStatus,
        error_message: Optional[str] = None,
    ) -> PatchApplyRun:
        now = datetime.utcnow()
        apply_run.status = status
        apply_run.error_message = error_message
        apply_run.updated_at = now
        if status == PatchApplyRunStatus.running and not apply_run.started_at:
            apply_run.started_at = now
        if status in {PatchApplyRunStatus.completed, PatchApplyRunStatus.failed, PatchApplyRunStatus.rolled_back}:
            apply_run.completed_at = now
        await self.db.flush()
        await self.db.refresh(apply_run)
        return apply_run

    async def finish_apply_run(
        self,
        apply_run: PatchApplyRun,
        *,
        status: PatchApplyRunStatus,
        patches_applied: int,
        patches_failed: int,
        validation_status: PatchValidationStatus,
        validation_output: Optional[str],
        git_diff_summary: Optional[str],
        error_message: Optional[str] = None,
    ) -> PatchApplyRun:
        now = datetime.utcnow()
        apply_run.status = status
        apply_run.patches_applied = patches_applied
        apply_run.patches_failed = patches_failed
        apply_run.validation_status = validation_status
        apply_run.validation_output = validation_output
        apply_run.git_diff_summary = git_diff_summary
        apply_run.error_message = error_message
        apply_run.completed_at = now if status != PatchApplyRunStatus.running else None
        apply_run.updated_at = now
        await self.db.flush()
        await self.db.refresh(apply_run)
        return apply_run

    async def add_apply_results(self, records: Iterable[dict]) -> List[PatchApplyResult]:
        results = []
        for values in records:
            result = PatchApplyResult(**values)
            self.db.add(result)
            results.append(result)
        await self.db.flush()
        for result in results:
            await self.db.refresh(result)
        return results

    async def list_apply_results(
        self,
        apply_run_id: UUID,
        tenant_id: UUID,
        limit: int = 500,
        offset: int = 0,
    ) -> List[PatchApplyResult]:
        result = await self.db.execute(
            select(PatchApplyResult)
            .where(PatchApplyResult.apply_run_id == apply_run_id, PatchApplyResult.tenant_id == tenant_id)
            .order_by(PatchApplyResult.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_apply_result_status(
        self,
        result: PatchApplyResult,
        status: PatchApplyResultStatus,
        reason: Optional[str] = None,
    ) -> PatchApplyResult:
        result.status = status
        if reason:
            result.reason = reason
        await self.db.flush()
        await self.db.refresh(result)
        return result

    async def create_pull_request_record(
        self,
        *,
        tenant_id: UUID,
        project_id: Optional[UUID],
        repo_connection_id: UUID,
        apply_run_id: UUID,
        branch_name: str,
        base_branch: str,
        title: str,
        description: str,
        status: PullRequestStatus,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        pr_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> PullRequestRecord:
        record = PullRequestRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            repo_connection_id=repo_connection_id,
            apply_run_id=apply_run_id,
            provider=PullRequestProvider.github,
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            pr_number=pr_number,
            pr_url=pr_url,
            status=status,
            title=title,
            description=description,
            error_message=error_message,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_pull_request(self, pr_id: UUID, tenant_id: UUID) -> Optional[PullRequestRecord]:
        result = await self.db.execute(
            select(PullRequestRecord).where(PullRequestRecord.id == pr_id, PullRequestRecord.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def list_content_suggestions(self, tenant_id: UUID, project_id: Optional[UUID]) -> List[ContentOptimizationSuggestion]:
        query = select(ContentOptimizationSuggestion).where(
            ContentOptimizationSuggestion.tenant_id == tenant_id,
            ContentOptimizationSuggestion.status.in_([
                ContentOptimizationSuggestionStatus.suggested,
                ContentOptimizationSuggestionStatus.approved,
            ]),
        )
        if project_id:
            query = query.where(ContentOptimizationSuggestion.project_id == project_id)
        result = await self.db.execute(query.limit(200))
        return list(result.scalars().all())

    async def list_search_console_opportunities(self, tenant_id: UUID, project_id: Optional[UUID]) -> List[SearchConsoleOpportunity]:
        query = select(SearchConsoleOpportunity).where(
            SearchConsoleOpportunity.tenant_id == tenant_id,
            SearchConsoleOpportunity.status.in_([
                SearchConsoleOpportunityStatus.suggested,
                SearchConsoleOpportunityStatus.approved,
            ]),
        )
        if project_id:
            query = query.where(SearchConsoleOpportunity.project_id == project_id)
        result = await self.db.execute(query.limit(200))
        return list(result.scalars().all())

    async def list_geo_aeo_recommendations(self, tenant_id: UUID, project_id: Optional[UUID]) -> List[GeoAeoRecommendation]:
        query = select(GeoAeoRecommendation).where(GeoAeoRecommendation.tenant_id == tenant_id)
        if project_id:
            query = query.where(GeoAeoRecommendation.project_id == project_id)
        result = await self.db.execute(query.limit(200))
        return list(result.scalars().all())

    # Task types the repository agent can turn into code changes. Content/topic
    # tasks (blogs, citations, backlinks) are excluded because they are not code.
    CODE_ADDRESSABLE_TASK_TYPES = (
        SeoTaskType.metadata_rewrite,
        SeoTaskType.schema_addition,
        SeoTaskType.geo_aeo_improvement,
        SeoTaskType.search_console_opportunity,
        SeoTaskType.sitemap_robots_fix,
    )

    async def list_open_planner_tasks(self, tenant_id: UUID, project_id: Optional[UUID]) -> List[SeoTask]:
        """Open planner tasks whose type maps to a concrete code change."""
        query = select(SeoTask).where(
            SeoTask.tenant_id == tenant_id,
            SeoTask.status.in_([
                SeoTaskStatus.todo,
                SeoTaskStatus.in_progress,
                SeoTaskStatus.approved,
            ]),
            SeoTask.task_type.in_(self.CODE_ADDRESSABLE_TASK_TYPES),
        )
        if project_id:
            query = query.where(SeoTask.project_id == project_id)
        result = await self.db.execute(
            query.order_by(SeoTask.priority_score.desc()).limit(200)
        )
        return list(result.scalars().all())

"""Repository layer for SEO code-agent repository scanning and patches."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_optimization import ContentOptimizationSuggestion, ContentOptimizationSuggestionStatus
from app.models.geo_aeo import GeoAeoRecommendation
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
        connection = RepoConnection(
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
            repo_url=repo_url,
            local_path=local_path,
            default_branch=default_branch,
            framework=framework,
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
        for values in records:
            file = RepoFile(**values)
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
        for values in records:
            issue = SeoCodeIssue(**values)
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
        for values in records:
            patch = SeoCodePatch(**values)
            self.db.add(patch)
            patches.append(patch)
        await self.db.flush()
        for patch in patches:
            await self.db.refresh(patch)
        return patches

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

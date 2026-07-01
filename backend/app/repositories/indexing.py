"""Repository layer for GSC indexing intelligence and validation."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOIssue, SEOIssueStatus
from app.models.crawl import CrawlJob, CrawlLink, CrawlPage, CrawlStatus, SitemapCache
from app.models.indexing import (
    GSCFixValidationResult,
    GSCFixValidationRun,
    GSCFixValidationRunStatus,
    GSCIndexingIssue,
    GSCIndexingIssueStatus,
    GSCIndexingIssueType,
    GSCUrlInspectionResult,
    GSCUrlInspectionRun,
    GSCUrlInspectionRunStatus,
)
from app.models.internal_linking import InternalLinkRecommendation, InternalLinkRecommendationStatus
from app.models.planner import SeoPlannerRun, SeoPlannerRunStatus, SeoPlannerRunType, SeoTask, SeoTaskStatus
from app.models.project import Project
from app.models.repo_agent import (
    PatchApplyResult,
    PullRequestRecord,
    PullRequestStatus,
    RepoConnection,
    RepoScanRun,
    RepoScanRunStatus,
    SeoCodeIssue,
    SeoCodePatch,
    SeoCodePatchStatus,
)
from app.models.search_console import (
    GSCConnection,
    GSCProperty,
    SearchConsoleOpportunity,
    SearchConsoleOpportunityStatus,
    SearchConsolePeriod,
    SearchConsoleRow,
)


OPEN_INDEXING_STATUSES = {
    GSCIndexingIssueStatus.open,
    GSCIndexingIssueStatus.in_progress,
    GSCIndexingIssueStatus.fix_proposed,
    GSCIndexingIssueStatus.fixed,
    GSCIndexingIssueStatus.still_failing,
    GSCIndexingIssueStatus.inconclusive,
}


class IndexingRepository:
    """Persistence and source-signal access for indexing intelligence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def selected_property(self, project_id: UUID, tenant_id: UUID) -> Optional[GSCProperty]:
        result = await self.db.execute(
            select(GSCProperty).where(
                GSCProperty.tenant_id == tenant_id,
                GSCProperty.project_id == project_id,
                GSCProperty.is_selected.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_property(self, property_id: UUID, tenant_id: UUID) -> Optional[GSCProperty]:
        result = await self.db.execute(
            select(GSCProperty).where(GSCProperty.id == property_id, GSCProperty.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_connection(self, connection_id: UUID, tenant_id: UUID) -> Optional[GSCConnection]:
        result = await self.db.execute(
            select(GSCConnection).where(GSCConnection.id == connection_id, GSCConnection.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_inspection_run(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gsc_property_id: UUID,
        requested_url_count: int,
    ) -> GSCUrlInspectionRun:
        run = GSCUrlInspectionRun(
            tenant_id=tenant_id,
            project_id=project_id,
            gsc_property_id=gsc_property_id,
            status=GSCUrlInspectionRunStatus.queued,
            requested_url_count=requested_url_count,
            inspected_url_count=0,
            failed_url_count=0,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_inspection_run(self, run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[GSCUrlInspectionRun]:
        query = select(GSCUrlInspectionRun).where(GSCUrlInspectionRun.id == run_id)
        if tenant_id:
            query = query.where(GSCUrlInspectionRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_inspection_runs(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GSCUrlInspectionRun]:
        result = await self.db.execute(
            select(GSCUrlInspectionRun)
            .where(GSCUrlInspectionRun.project_id == project_id, GSCUrlInspectionRun.tenant_id == tenant_id)
            .order_by(GSCUrlInspectionRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_inspection_run_status(
        self,
        run: GSCUrlInspectionRun,
        status: GSCUrlInspectionRunStatus,
        *,
        error_message: Optional[str] = None,
    ) -> GSCUrlInspectionRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        if status == GSCUrlInspectionRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {
            GSCUrlInspectionRunStatus.completed,
            GSCUrlInspectionRunStatus.failed,
            GSCUrlInspectionRunStatus.partial,
        }:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def update_inspection_counts(
        self,
        run: GSCUrlInspectionRun,
        *,
        inspected_url_count: int,
        failed_url_count: int,
    ) -> GSCUrlInspectionRun:
        run.inspected_url_count = inspected_url_count
        run.failed_url_count = failed_url_count
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def add_inspection_result(self, values: dict) -> GSCUrlInspectionResult:
        result = GSCUrlInspectionResult(**values)
        self.db.add(result)
        await self.db.flush()
        await self.db.refresh(result)
        return result

    async def list_run_results(
        self,
        run_id: UUID,
        tenant_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[GSCUrlInspectionResult]:
        result = await self.db.execute(
            select(GSCUrlInspectionResult)
            .where(GSCUrlInspectionResult.inspection_run_id == run_id, GSCUrlInspectionResult.tenant_id == tenant_id)
            .order_by(GSCUrlInspectionResult.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def latest_result_for_url(
        self,
        project_id: UUID,
        tenant_id: UUID,
        page_url: str,
    ) -> Optional[GSCUrlInspectionResult]:
        result = await self.db.execute(
            select(GSCUrlInspectionResult)
            .where(
                GSCUrlInspectionResult.project_id == project_id,
                GSCUrlInspectionResult.tenant_id == tenant_id,
                GSCUrlInspectionResult.page_url == page_url,
            )
            .order_by(GSCUrlInspectionResult.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_open_issue(
        self,
        project_id: UUID,
        tenant_id: UUID,
        page_url: str,
        issue_type: GSCIndexingIssueType,
    ) -> Optional[GSCIndexingIssue]:
        result = await self.db.execute(
            select(GSCIndexingIssue)
            .where(
                GSCIndexingIssue.project_id == project_id,
                GSCIndexingIssue.tenant_id == tenant_id,
                GSCIndexingIssue.page_url == page_url,
                GSCIndexingIssue.issue_type == issue_type,
                GSCIndexingIssue.status.in_(list(OPEN_INDEXING_STATUSES)),
            )
            .order_by(GSCIndexingIssue.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def open_issues_for_url(
        self,
        project_id: UUID,
        tenant_id: UUID,
        page_url: str,
    ) -> List[GSCIndexingIssue]:
        result = await self.db.execute(
            select(GSCIndexingIssue)
            .where(
                GSCIndexingIssue.project_id == project_id,
                GSCIndexingIssue.tenant_id == tenant_id,
                GSCIndexingIssue.page_url == page_url,
                GSCIndexingIssue.status.in_(list(OPEN_INDEXING_STATUSES)),
            )
            .order_by(GSCIndexingIssue.created_at.desc())
        )
        return list(result.scalars().all())

    async def upsert_issue(self, values: dict) -> GSCIndexingIssue:
        existing = await self.find_open_issue(
            values["project_id"],
            values["tenant_id"],
            values["page_url"],
            values["issue_type"],
        )
        if existing:
            existing.inspection_result_id = values["inspection_result_id"]
            existing.severity = values["severity"]
            existing.likely_cause = values["likely_cause"]
            existing.recommended_fix = values["recommended_fix"]
            if existing.status in {
                GSCIndexingIssueStatus.validated,
                GSCIndexingIssueStatus.ignored,
            }:
                existing.status = GSCIndexingIssueStatus.open
            existing.updated_at = datetime.utcnow()
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        issue = GSCIndexingIssue(**values)
        self.db.add(issue)
        await self.db.flush()
        await self.db.refresh(issue)
        return issue

    async def list_issues(
        self,
        project_id: UUID,
        tenant_id: UUID,
        status: Optional[GSCIndexingIssueStatus] = None,
        issue_type: Optional[GSCIndexingIssueType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GSCIndexingIssue]:
        query = select(GSCIndexingIssue).where(
            GSCIndexingIssue.project_id == project_id,
            GSCIndexingIssue.tenant_id == tenant_id,
        )
        if status:
            query = query.where(GSCIndexingIssue.status == status)
        if issue_type:
            query = query.where(GSCIndexingIssue.issue_type == issue_type)
        query = query.order_by(GSCIndexingIssue.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_issue(self, issue_id: UUID, tenant_id: UUID) -> Optional[GSCIndexingIssue]:
        result = await self.db.execute(
            select(GSCIndexingIssue).where(GSCIndexingIssue.id == issue_id, GSCIndexingIssue.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def set_issue_status(
        self,
        issue: GSCIndexingIssue,
        status: GSCIndexingIssueStatus,
    ) -> GSCIndexingIssue:
        issue.status = status
        issue.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(issue)
        return issue

    async def update_issue_links(
        self,
        issue: GSCIndexingIssue,
        *,
        linked_repo_issue_id: Optional[UUID] = None,
        linked_patch_id: Optional[UUID] = None,
        status: Optional[GSCIndexingIssueStatus] = None,
    ) -> GSCIndexingIssue:
        if linked_repo_issue_id:
            issue.linked_repo_issue_id = linked_repo_issue_id
        if linked_patch_id:
            issue.linked_patch_id = linked_patch_id
        if status:
            issue.status = status
        issue.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(issue)
        return issue

    async def create_validation_run(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        issue_id: Optional[UUID] = None,
        patch_id: Optional[UUID] = None,
        pull_request_id: Optional[UUID] = None,
        validation_after_days: int = 7,
    ) -> GSCFixValidationRun:
        run = GSCFixValidationRun(
            tenant_id=tenant_id,
            project_id=project_id,
            issue_id=issue_id,
            patch_id=patch_id,
            pull_request_id=pull_request_id,
            status=GSCFixValidationRunStatus.queued,
            validation_after_days=validation_after_days,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def set_validation_run_status(
        self,
        run: GSCFixValidationRun,
        status: GSCFixValidationRunStatus,
    ) -> GSCFixValidationRun:
        now = datetime.utcnow()
        run.status = status
        if status == GSCFixValidationRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {GSCFixValidationRunStatus.completed, GSCFixValidationRunStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def add_validation_result(self, values: dict) -> GSCFixValidationResult:
        result = GSCFixValidationResult(**values)
        self.db.add(result)
        await self.db.flush()
        await self.db.refresh(result)
        return result

    async def latest_crawl(self, project_id: UUID, tenant_id: UUID) -> Optional[CrawlJob]:
        result = await self.db.execute(
            select(CrawlJob)
            .where(CrawlJob.project_id == project_id, CrawlJob.tenant_id == tenant_id, CrawlJob.status == CrawlStatus.completed)
            .order_by(CrawlJob.completed_at.desc().nullslast(), CrawlJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_crawl_pages(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 500,
    ) -> List[CrawlPage]:
        latest = await self.latest_crawl(project_id, tenant_id)
        if not latest:
            return []
        result = await self.db.execute(
            select(CrawlPage)
            .where(CrawlPage.crawl_job_id == latest.id)
            .order_by(CrawlPage.depth.asc(), CrawlPage.crawled_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def crawl_page_for_url(
        self,
        project_id: UUID,
        tenant_id: UUID,
        page_url: str,
    ) -> Optional[CrawlPage]:
        latest = await self.latest_crawl(project_id, tenant_id)
        if not latest:
            return None
        keys = {page_url, page_url.rstrip("/")}
        result = await self.db.execute(
            select(CrawlPage)
            .where(
                CrawlPage.crawl_job_id == latest.id,
                or_(
                    CrawlPage.url.in_(keys),
                    CrawlPage.normalized_url.in_(keys),
                    CrawlPage.final_url.in_(keys),
                    CrawlPage.canonical_url.in_(keys),
                    CrawlPage.canonical_url_normalized.in_(keys),
                ),
            )
            .order_by(CrawlPage.crawled_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def open_audit_issues_for_url(
        self,
        project_id: UUID,
        tenant_id: UUID,
        page_url: str,
        crawl_page_id: Optional[UUID] = None,
    ) -> List[SEOIssue]:
        query = select(SEOIssue).where(
            SEOIssue.project_id == project_id,
            SEOIssue.tenant_id == tenant_id,
            SEOIssue.status == SEOIssueStatus.open,
        )
        if crawl_page_id:
            query = query.where(or_(SEOIssue.crawl_page_id == crawl_page_id, SEOIssue.url == page_url))
        else:
            query = query.where(SEOIssue.url == page_url)
        result = await self.db.execute(query.limit(100))
        return list(result.scalars().all())

    async def inbound_internal_link_count(
        self,
        project_id: UUID,
        tenant_id: UUID,
        page_url: str,
    ) -> int:
        latest = await self.latest_crawl(project_id, tenant_id)
        if not latest:
            return 0
        keys = {page_url, page_url.rstrip("/")}
        count = await self.db.scalar(
            select(func.count(CrawlLink.id)).where(
                CrawlLink.crawl_job_id == latest.id,
                CrawlLink.link_type == "internal",
                or_(CrawlLink.url.in_(keys), CrawlLink.normalized_url.in_(keys)),
            )
        )
        return int(count or 0)

    async def pages_with_internal_link_support(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
    ) -> List[str]:
        result = await self.db.execute(
            select(InternalLinkRecommendation.target_url)
            .where(
                InternalLinkRecommendation.project_id == project_id,
                InternalLinkRecommendation.tenant_id == tenant_id,
                InternalLinkRecommendation.status.in_([
                    InternalLinkRecommendationStatus.suggested,
                    InternalLinkRecommendationStatus.approved,
                ]),
            )
            .order_by(InternalLinkRecommendation.priority_score.desc())
            .limit(limit)
        )
        return [url for url in result.scalars().all() if url]

    async def gsc_page_metrics(self, project_id: UUID, tenant_id: UUID, limit: int = 500) -> List[dict]:
        result = await self.db.execute(
            select(
                SearchConsoleRow.page_url,
                func.sum(SearchConsoleRow.impressions),
                func.sum(SearchConsoleRow.clicks),
                func.max(SearchConsoleRow.created_at),
            )
            .where(
                SearchConsoleRow.project_id == project_id,
                SearchConsoleRow.tenant_id == tenant_id,
                SearchConsoleRow.period == SearchConsolePeriod.current,
            )
            .group_by(SearchConsoleRow.page_url)
            .order_by(func.sum(SearchConsoleRow.impressions).desc())
            .limit(limit)
        )
        return [
            {"page_url": row[0], "impressions": int(row[1] or 0), "clicks": int(row[2] or 0), "last_seen_at": row[3]}
            for row in result.all()
            if row[0]
        ]

    async def gsc_opportunity_urls(self, project_id: UUID, tenant_id: UUID, limit: int = 100) -> List[str]:
        result = await self.db.execute(
            select(SearchConsoleOpportunity.page_url)
            .where(
                SearchConsoleOpportunity.project_id == project_id,
                SearchConsoleOpportunity.tenant_id == tenant_id,
                SearchConsoleOpportunity.status.in_([
                    SearchConsoleOpportunityStatus.suggested,
                    SearchConsoleOpportunityStatus.approved,
                ]),
            )
            .order_by(SearchConsoleOpportunity.priority_score.desc())
            .limit(limit)
        )
        return [url for url in result.scalars().all() if url]

    async def planner_task_urls(self, project_id: UUID, tenant_id: UUID, limit: int = 100) -> List[str]:
        result = await self.db.execute(
            select(SeoTask.target_page_url)
            .where(
                SeoTask.project_id == project_id,
                SeoTask.tenant_id == tenant_id,
                SeoTask.target_page_url.is_not(None),
                SeoTask.status.in_([SeoTaskStatus.todo, SeoTaskStatus.in_progress, SeoTaskStatus.approved]),
            )
            .order_by(SeoTask.priority_score.desc(), SeoTask.updated_at.desc())
            .limit(limit)
        )
        return [url for url in result.scalars().all() if url]

    async def previous_issue_urls(self, project_id: UUID, tenant_id: UUID, limit: int = 100) -> List[str]:
        result = await self.db.execute(
            select(GSCIndexingIssue.page_url)
            .where(
                GSCIndexingIssue.project_id == project_id,
                GSCIndexingIssue.tenant_id == tenant_id,
                GSCIndexingIssue.status.in_(list(OPEN_INDEXING_STATUSES)),
            )
            .order_by(GSCIndexingIssue.updated_at.desc())
            .limit(limit)
        )
        return [url for url in result.scalars().all() if url]

    async def sitemap_entries_for_project(self, project: Project) -> List[str]:
        domain = (project.domain or "").lower().replace("https://", "").replace("http://", "").strip("/")
        if not domain:
            return []
        result = await self.db.execute(
            select(SitemapCache).where(SitemapCache.is_valid.is_(True)).order_by(SitemapCache.fetched_at.desc()).limit(50)
        )
        urls: list[str] = []
        for cache in result.scalars().all():
            entries = cache.urls or []
            for item in entries:
                loc = item.get("loc") if isinstance(item, dict) else str(item)
                if loc and domain in loc.lower():
                    urls.append(loc)
        return urls

    async def recent_patches(self, project_id: UUID, tenant_id: UUID, limit: int = 100) -> List[SeoCodePatch]:
        result = await self.db.execute(
            select(SeoCodePatch)
            .where(
                SeoCodePatch.project_id == project_id,
                SeoCodePatch.tenant_id == tenant_id,
                SeoCodePatch.status.in_([SeoCodePatchStatus.approved, SeoCodePatchStatus.applied, SeoCodePatchStatus.proposed]),
            )
            .order_by(SeoCodePatch.updated_at.desc(), SeoCodePatch.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def recently_merged_pull_requests(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 25,
    ) -> List[PullRequestRecord]:
        result = await self.db.execute(
            select(PullRequestRecord)
            .where(
                PullRequestRecord.project_id == project_id,
                PullRequestRecord.tenant_id == tenant_id,
                PullRequestRecord.status == PullRequestStatus.merged,
            )
            .order_by(PullRequestRecord.updated_at.desc(), PullRequestRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def patches_for_pull_requests(self, pull_request_ids: Iterable[UUID], tenant_id: UUID) -> List[SeoCodePatch]:
        ids = list(pull_request_ids)
        if not ids:
            return []
        result = await self.db.execute(
            select(SeoCodePatch)
            .join(PatchApplyResult, PatchApplyResult.patch_id == SeoCodePatch.id)
            .join(PullRequestRecord, PullRequestRecord.apply_run_id == PatchApplyResult.apply_run_id)
            .where(PullRequestRecord.id.in_(ids), PullRequestRecord.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def latest_repo_scan(self, project_id: UUID, tenant_id: UUID) -> Optional[RepoScanRun]:
        result = await self.db.execute(
            select(RepoScanRun)
            .where(
                RepoScanRun.project_id == project_id,
                RepoScanRun.tenant_id == tenant_id,
                RepoScanRun.status == RepoScanRunStatus.completed,
            )
            .order_by(RepoScanRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def first_repo_connection(self, project_id: UUID, tenant_id: UUID) -> Optional[RepoConnection]:
        result = await self.db.execute(
            select(RepoConnection)
            .where(RepoConnection.project_id == project_id, RepoConnection.tenant_id == tenant_id)
            .order_by(RepoConnection.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_repo_issue(self, values: dict) -> SeoCodeIssue:
        issue = SeoCodeIssue(**values)
        self.db.add(issue)
        await self.db.flush()
        await self.db.refresh(issue)
        return issue

    async def latest_patch_for_repo_issue(self, repo_issue_id: UUID, tenant_id: UUID) -> Optional[SeoCodePatch]:
        result = await self.db.execute(
            select(SeoCodePatch)
            .where(SeoCodePatch.issue_id == repo_issue_id, SeoCodePatch.tenant_id == tenant_id)
            .order_by(SeoCodePatch.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_planner_run_for_fix(self, project_id: UUID, tenant_id: UUID) -> SeoPlannerRun:
        now = datetime.utcnow()
        week_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        run = SeoPlannerRun(
            tenant_id=tenant_id,
            project_id=project_id,
            status=SeoPlannerRunStatus.completed,
            run_type=SeoPlannerRunType.manual,
            target_week_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
            target_week_end=week_end,
            tasks_created=0,
            high_priority_tasks=0,
            started_at=now,
            completed_at=now,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def upsert_fix_task(self, values: dict) -> tuple[SeoTask, bool]:
        query = select(SeoTask).where(
            SeoTask.tenant_id == values["tenant_id"],
            SeoTask.project_id == values["project_id"],
            SeoTask.task_type == values["task_type"],
            SeoTask.source_type == values["source_type"],
            SeoTask.source_reference_id == values["source_reference_id"],
            SeoTask.target_page_url == values["target_page_url"],
            SeoTask.status.in_([SeoTaskStatus.todo, SeoTaskStatus.in_progress, SeoTaskStatus.approved]),
        )
        result = await self.db.execute(query.order_by(SeoTask.updated_at.desc()).limit(1))
        existing = result.scalar_one_or_none()
        if existing:
            existing.planner_run_id = values["planner_run_id"]
            existing.title = values["title"]
            existing.description = values["description"]
            existing.priority = values["priority"]
            existing.priority_score = values["priority_score"]
            existing.estimated_impact = values["estimated_impact"]
            existing.effort = values["effort"]
            existing.due_date = values.get("due_date")
            existing.updated_at = datetime.utcnow()
            await self.db.flush()
            await self.db.refresh(existing)
            return existing, False
        task = SeoTask(**values)
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task, True

    async def indexing_summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        issues = await self.list_issues(project_id, tenant_id, limit=1000)
        latest_run_result = await self.db.execute(
            select(GSCUrlInspectionRun)
            .where(GSCUrlInspectionRun.project_id == project_id, GSCUrlInspectionRun.tenant_id == tenant_id)
            .order_by(GSCUrlInspectionRun.created_at.desc())
            .limit(1)
        )
        latest_run = latest_run_result.scalar_one_or_none()
        indexed_count = await self.db.scalar(
            select(func.count(GSCUrlInspectionResult.id)).where(
                GSCUrlInspectionResult.project_id == project_id,
                GSCUrlInspectionResult.tenant_id == tenant_id,
                GSCUrlInspectionResult.verdict == "PASS",
            )
        )
        result_count = await self.db.scalar(
            select(func.count(GSCUrlInspectionResult.id)).where(
                GSCUrlInspectionResult.project_id == project_id,
                GSCUrlInspectionResult.tenant_id == tenant_id,
            )
        )
        by_type = Counter(self._enum_value(issue.issue_type) for issue in issues)
        by_status = Counter(self._enum_value(issue.status) for issue in issues)
        return {
            "project_id": project_id,
            "indexed_urls": int(indexed_count or 0),
            "not_indexed_urls": max(int(result_count or 0) - int(indexed_count or 0), 0),
            "issues_count": len(issues),
            "issues_by_type": dict(by_type),
            "issues_by_status": dict(by_status),
            "latest_run": latest_run,
            "top_issues": issues[:10],
        }

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)

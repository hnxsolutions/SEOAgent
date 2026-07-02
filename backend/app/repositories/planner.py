"""Repository layer for weekly autonomous SEO planner."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOAuditRun, SEOIssue, SEOIssueStatus
from app.models.blog import BlogPlan, BlogTopic, BlogTopicStatus
from app.models.content_optimization import ContentOptimizationRun, ContentOptimizationSuggestion, ContentOptimizationSuggestionStatus
from app.models.crawl import CrawlJob, CrawlStatus
from app.models.geo_aeo import GeoAeoRecommendation, GeoAeoRecommendationStatus, GeoAeoRun
from app.models.internal_linking import InternalLinkRecommendation, InternalLinkRecommendationStatus
from app.models.keyword_baseline import KeywordBaseline
from app.models.knowledge import KnowledgeSource
from app.models.planner import (
    SeoPlannerRun,
    SeoPlannerRunStatus,
    SeoPlannerRunType,
    SeoTask,
    SeoTaskStatus,
    SeoWeeklyReport,
)
from app.models.project import Project
from app.models.repo_agent import RepoConnection, RepoScanRun, SeoCodeIssue, SeoCodeIssueStatus, SeoCodePatch, SeoCodePatchStatus
from app.models.search_console import (
    GSCSyncJob,
    SearchConsoleImport,
    SearchConsoleOpportunity,
    SearchConsoleOpportunityStatus,
)
from app.models.semantic import SemanticIndexRun


OPEN_TASK_STATUSES = {
    SeoTaskStatus.todo,
    SeoTaskStatus.in_progress,
    SeoTaskStatus.approved,
}


class PlannerRepository:
    """Persistence and source-signal access for planner runs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_run(
        self,
        tenant_id: UUID,
        project_id: UUID,
        run_type: SeoPlannerRunType,
        target_week_start: datetime,
        target_week_end: datetime,
    ) -> SeoPlannerRun:
        run = SeoPlannerRun(
            tenant_id=tenant_id,
            project_id=project_id,
            run_type=run_type,
            target_week_start=target_week_start,
            target_week_end=target_week_end,
            status=SeoPlannerRunStatus.queued,
            tasks_created=0,
            high_priority_tasks=0,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[SeoPlannerRun]:
        query = select(SeoPlannerRun).where(SeoPlannerRun.id == run_id)
        if tenant_id:
            query = query.where(SeoPlannerRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SeoPlannerRun]:
        result = await self.db.execute(
            select(SeoPlannerRun)
            .where(SeoPlannerRun.project_id == project_id, SeoPlannerRun.tenant_id == tenant_id)
            .order_by(SeoPlannerRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_run_status(
        self,
        run: SeoPlannerRun,
        status: SeoPlannerRunStatus,
        error_message: Optional[str] = None,
    ) -> SeoPlannerRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if status == SeoPlannerRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {SeoPlannerRunStatus.completed, SeoPlannerRunStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def finish_run(
        self,
        run: SeoPlannerRun,
        *,
        tasks_created: int,
        high_priority_tasks: int,
        signal_ids: dict,
    ) -> SeoPlannerRun:
        now = datetime.utcnow()
        run.crawl_id = signal_ids.get("crawl_id")
        run.audit_id = signal_ids.get("audit_id")
        run.semantic_run_id = signal_ids.get("semantic_run_id")
        run.internal_link_run_id = signal_ids.get("internal_link_run_id")
        run.content_optimization_run_id = signal_ids.get("content_optimization_run_id")
        run.geo_aeo_run_id = signal_ids.get("geo_aeo_run_id")
        run.gsc_sync_job_id = signal_ids.get("gsc_sync_job_id")
        run.blog_plan_id = signal_ids.get("blog_plan_id")
        run.repo_scan_run_id = signal_ids.get("repo_scan_run_id")
        run.tasks_created = tasks_created
        run.high_priority_tasks = high_priority_tasks
        run.status = SeoPlannerRunStatus.completed
        run.completed_at = now
        run.updated_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def find_open_task(self, values: dict) -> Optional[SeoTask]:
        query = select(SeoTask).where(
            SeoTask.tenant_id == values["tenant_id"],
            SeoTask.project_id == values["project_id"],
            SeoTask.task_type == values["task_type"],
            SeoTask.source_type == values["source_type"],
            SeoTask.status.in_(list(OPEN_TASK_STATUSES)),
        )
        if values.get("target_page_url"):
            query = query.where(SeoTask.target_page_url == values["target_page_url"])
        else:
            query = query.where(SeoTask.target_page_url.is_(None))
        if values.get("target_keyword"):
            query = query.where(SeoTask.target_keyword == values["target_keyword"])
        else:
            query = query.where(SeoTask.target_keyword.is_(None))
        if values.get("source_reference_id"):
            query = query.where(SeoTask.source_reference_id == values["source_reference_id"])
        else:
            query = query.where(SeoTask.source_reference_id.is_(None))
        result = await self.db.execute(query.order_by(SeoTask.updated_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def upsert_task(self, values: dict) -> tuple[SeoTask, bool]:
        existing = await self.find_open_task(values)
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

    async def list_tasks(
        self,
        project_id: UUID,
        tenant_id: UUID,
        status: Optional[SeoTaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SeoTask]:
        query = select(SeoTask).where(SeoTask.project_id == project_id, SeoTask.tenant_id == tenant_id)
        if status:
            query = query.where(SeoTask.status == status)
        query = query.order_by(SeoTask.priority_score.desc(), SeoTask.updated_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_task(self, task_id: UUID, tenant_id: UUID) -> Optional[SeoTask]:
        result = await self.db.execute(select(SeoTask).where(SeoTask.id == task_id, SeoTask.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def set_task_status(self, task: SeoTask, status: SeoTaskStatus) -> SeoTask:
        task.status = status
        task.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def list_tasks_for_dedupe(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 5000,
    ) -> List[SeoTask]:
        result = await self.db.execute(
            select(SeoTask)
            .where(
                SeoTask.project_id == project_id,
                SeoTask.tenant_id == tenant_id,
                SeoTask.status.in_(list(OPEN_TASK_STATUSES)),
            )
            .order_by(SeoTask.updated_at.desc(), SeoTask.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_report(self, values: dict) -> SeoWeeklyReport:
        existing = await self.get_report(values["planner_run_id"], values["tenant_id"])
        if existing:
            for key, value in values.items():
                if key not in {"id", "tenant_id", "project_id", "planner_run_id", "created_at"}:
                    setattr(existing, key, value)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        report = SeoWeeklyReport(**values)
        self.db.add(report)
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def get_report(self, run_id: UUID, tenant_id: UUID) -> Optional[SeoWeeklyReport]:
        result = await self.db.execute(
            select(SeoWeeklyReport).where(
                SeoWeeklyReport.planner_run_id == run_id,
                SeoWeeklyReport.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def latest_crawl(self, project_id: UUID, tenant_id: UUID) -> Optional[CrawlJob]:
        result = await self.db.execute(
            select(CrawlJob)
            .where(
                CrawlJob.project_id == project_id,
                CrawlJob.tenant_id == tenant_id,
                CrawlJob.status == CrawlStatus.completed,
            )
            .order_by(CrawlJob.completed_at.desc().nullslast(), CrawlJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_audit(self, crawl_id: Optional[UUID], project_id: UUID, tenant_id: UUID) -> Optional[SEOAuditRun]:
        query = select(SEOAuditRun).where(SEOAuditRun.project_id == project_id, SEOAuditRun.tenant_id == tenant_id)
        if crawl_id:
            query = query.where(SEOAuditRun.crawl_job_id == crawl_id)
        result = await self.db.execute(query.order_by(SEOAuditRun.created_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def latest_semantic_run(self, crawl_id: Optional[UUID], project_id: UUID, tenant_id: UUID) -> Optional[SemanticIndexRun]:
        query = select(SemanticIndexRun).where(SemanticIndexRun.project_id == project_id, SemanticIndexRun.tenant_id == tenant_id)
        if crawl_id:
            query = query.where(SemanticIndexRun.crawl_job_id == crawl_id)
        result = await self.db.execute(query.order_by(SemanticIndexRun.created_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def latest_content_run(self, crawl_id: Optional[UUID], project_id: UUID, tenant_id: UUID) -> Optional[ContentOptimizationRun]:
        query = select(ContentOptimizationRun).where(ContentOptimizationRun.project_id == project_id, ContentOptimizationRun.tenant_id == tenant_id)
        if crawl_id:
            query = query.where(ContentOptimizationRun.crawl_id == crawl_id)
        result = await self.db.execute(query.order_by(ContentOptimizationRun.created_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def latest_geo_run(self, crawl_id: Optional[UUID], project_id: UUID, tenant_id: UUID) -> Optional[GeoAeoRun]:
        query = select(GeoAeoRun).where(GeoAeoRun.project_id == project_id, GeoAeoRun.tenant_id == tenant_id)
        if crawl_id:
            query = query.where(GeoAeoRun.crawl_id == crawl_id)
        result = await self.db.execute(query.order_by(GeoAeoRun.created_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def latest_gsc_sync(self, project_id: UUID, tenant_id: UUID) -> Optional[GSCSyncJob]:
        result = await self.db.execute(
            select(GSCSyncJob)
            .where(GSCSyncJob.project_id == project_id, GSCSyncJob.tenant_id == tenant_id)
            .order_by(GSCSyncJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_search_console_import(self, project_id: UUID, tenant_id: UUID) -> Optional[SearchConsoleImport]:
        result = await self.db.execute(
            select(SearchConsoleImport)
            .where(SearchConsoleImport.project_id == project_id, SearchConsoleImport.tenant_id == tenant_id)
            .order_by(SearchConsoleImport.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_blog_plan(self, project_id: UUID, tenant_id: UUID) -> Optional[BlogPlan]:
        result = await self.db.execute(
            select(BlogPlan)
            .where(BlogPlan.project_id == project_id, BlogPlan.tenant_id == tenant_id)
            .order_by(BlogPlan.updated_at.desc(), BlogPlan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_repo_scan(self, project_id: UUID, tenant_id: UUID) -> Optional[RepoScanRun]:
        result = await self.db.execute(
            select(RepoScanRun)
            .where(RepoScanRun.project_id == project_id, RepoScanRun.tenant_id == tenant_id)
            .order_by(RepoScanRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_repo_connection(self, project_id: UUID, tenant_id: UUID) -> bool:
        count = await self.db.scalar(
            select(func.count(RepoConnection.id)).where(
                RepoConnection.project_id == project_id,
                RepoConnection.tenant_id == tenant_id,
            )
        )
        return bool(count)

    async def has_knowledge(self, project_id: UUID, tenant_id: UUID) -> bool:
        count = await self.db.scalar(
            select(func.count(KnowledgeSource.id)).where(
                KnowledgeSource.project_id == project_id,
                KnowledgeSource.tenant_id == tenant_id,
            )
        )
        return bool(count)

    async def list_audit_issues(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[SEOIssue]:
        result = await self.db.execute(
            select(SEOIssue)
            .where(SEOIssue.project_id == project_id, SEOIssue.tenant_id == tenant_id, SEOIssue.status == SEOIssueStatus.open)
            .order_by(SEOIssue.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_gsc_opportunities(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[SearchConsoleOpportunity]:
        result = await self.db.execute(
            select(SearchConsoleOpportunity)
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
        return list(result.scalars().all())

    async def list_keyword_baselines(self, project_id: UUID, tenant_id: UUID, limit: int = 500) -> List[KeywordBaseline]:
        result = await self.db.execute(
            select(KeywordBaseline)
            .where(KeywordBaseline.project_id == project_id, KeywordBaseline.tenant_id == tenant_id)
            .order_by(KeywordBaseline.captured_at.desc(), KeywordBaseline.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_content_suggestions(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[ContentOptimizationSuggestion]:
        result = await self.db.execute(
            select(ContentOptimizationSuggestion)
            .where(
                ContentOptimizationSuggestion.project_id == project_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
                ContentOptimizationSuggestion.status.in_([
                    ContentOptimizationSuggestionStatus.suggested,
                    ContentOptimizationSuggestionStatus.approved,
                ]),
            )
            .order_by(ContentOptimizationSuggestion.priority_score.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_geo_recommendations(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[GeoAeoRecommendation]:
        result = await self.db.execute(
            select(GeoAeoRecommendation)
            .where(
                GeoAeoRecommendation.project_id == project_id,
                GeoAeoRecommendation.tenant_id == tenant_id,
                GeoAeoRecommendation.status.in_([
                    GeoAeoRecommendationStatus.suggested,
                    GeoAeoRecommendationStatus.approved,
                ]),
            )
            .order_by(GeoAeoRecommendation.priority_score.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_internal_link_recommendations(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[InternalLinkRecommendation]:
        result = await self.db.execute(
            select(InternalLinkRecommendation)
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
        return list(result.scalars().all())

    async def list_blog_topics(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[BlogTopic]:
        result = await self.db.execute(
            select(BlogTopic)
            .where(
                BlogTopic.project_id == project_id,
                BlogTopic.tenant_id == tenant_id,
                BlogTopic.status.in_([BlogTopicStatus.suggested, BlogTopicStatus.approved]),
            )
            .order_by(BlogTopic.priority_score.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_repo_patches(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[SeoCodePatch]:
        result = await self.db.execute(
            select(SeoCodePatch)
            .where(
                SeoCodePatch.project_id == project_id,
                SeoCodePatch.tenant_id == tenant_id,
                SeoCodePatch.status.in_([SeoCodePatchStatus.proposed, SeoCodePatchStatus.approved]),
            )
            .order_by(SeoCodePatch.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_repo_issues(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> List[SeoCodeIssue]:
        result = await self.db.execute(
            select(SeoCodeIssue)
            .where(
                SeoCodeIssue.project_id == project_id,
                SeoCodeIssue.tenant_id == tenant_id,
                SeoCodeIssue.status == SeoCodeIssueStatus.open,
            )
            .order_by(SeoCodeIssue.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

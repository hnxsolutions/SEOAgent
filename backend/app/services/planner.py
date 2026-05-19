"""Weekly autonomous SEO planner orchestration service."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.audit import SEOIssueCategory, SEOIssueSeverity
from app.models.blog import BlogTopicStatus
from app.models.content_optimization import ContentOptimizationSuggestionType
from app.models.geo_aeo import GeoAeoRecommendationType
from app.models.planner import (
    SeoPlannerRun,
    SeoPlannerRunStatus,
    SeoPlannerRunType,
    SeoTask,
    SeoTaskEffort,
    SeoTaskImpact,
    SeoTaskPriority,
    SeoTaskSourceType,
    SeoTaskStatus,
    SeoTaskType,
    SeoWeeklyReport,
)
from app.models.repo_agent import SeoCodeIssueType, SeoCodePatchType
from app.models.search_console import SearchConsoleOpportunityType
from app.repositories.planner import PlannerRepository

logger = structlog.get_logger(__name__)


class PlannerError(RuntimeError):
    """Base planner service error."""


@dataclass
class TaskCandidate:
    task_type: SeoTaskType
    title: str
    description: str
    source_type: SeoTaskSourceType
    source_reference_id: Optional[UUID] = None
    target_page_url: Optional[str] = None
    target_keyword: Optional[str] = None
    priority_score: float = 50
    priority: Optional[SeoTaskPriority] = None
    estimated_impact: SeoTaskImpact = SeoTaskImpact.medium
    effort: SeoTaskEffort = SeoTaskEffort.medium


class PlannerService:
    """Turns existing SEO intelligence into a weekly task plan and report."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = PlannerRepository(db)

    async def start_run(
        self,
        project_id: UUID,
        tenant_id: UUID,
        run_type: SeoPlannerRunType = SeoPlannerRunType.manual,
        target_week_start: Optional[datetime] = None,
    ) -> SeoPlannerRun:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        week_start = target_week_start or self._week_start(datetime.utcnow())
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        run = await self.repository.create_run(
            tenant_id=tenant_id,
            project_id=project_id,
            run_type=run_type,
            target_week_start=week_start,
            target_week_end=week_end,
        )
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def run_project(
        self,
        project_id: UUID,
        tenant_id: UUID,
        run_type: SeoPlannerRunType = SeoPlannerRunType.manual,
        target_week_start: Optional[datetime] = None,
    ) -> SeoPlannerRun:
        run = await self.start_run(project_id, tenant_id, run_type=run_type, target_week_start=target_week_start)
        return await self.execute_run(run.id, tenant_id)

    async def execute_run(self, run_id: UUID, tenant_id: UUID) -> SeoPlannerRun:
        run = await self.repository.get_run(run_id, tenant_id)
        if not run:
            raise ValueError("Planner run not found")
        await self.repository.set_run_status(run, SeoPlannerRunStatus.running)
        await self.db.commit()
        try:
            signals = await self._collect_signals(run)
            candidates = self._task_candidates(signals)
            created_count = 0
            touched_tasks: List[SeoTask] = []
            for candidate in candidates:
                task, created = await self.repository.upsert_task(self._task_values(run, candidate))
                touched_tasks.append(task)
                if created:
                    created_count += 1
            high_priority_count = len([
                task for task in touched_tasks
                if self._enum_value(task.priority) in {SeoTaskPriority.high.value, SeoTaskPriority.critical.value}
            ])
            report = self._report_values(run, signals, touched_tasks, created_count)
            await self.repository.create_report(report)
            run = await self.repository.finish_run(
                run,
                tasks_created=created_count,
                high_priority_tasks=high_priority_count,
                signal_ids=signals["ids"],
            )
            await self.db.commit()
            await self.db.refresh(run)
            logger.info(
                "Completed weekly SEO planner run",
                run_id=str(run.id),
                tasks_created=created_count,
                high_priority_tasks=high_priority_count,
            )
            return run
        except Exception as exc:
            await self.repository.set_run_status(run, SeoPlannerRunStatus.failed, error_message=str(exc))
            await self.db.commit()
            logger.error("Weekly SEO planner run failed", run_id=str(run.id), error=str(exc), exc_info=True)
            if isinstance(exc, PlannerError):
                raise
            raise PlannerError(str(exc)) from exc

    async def get_run_status(self, run_id: UUID, tenant_id: UUID) -> Optional[SeoPlannerRun]:
        return await self.repository.get_run(run_id, tenant_id)

    async def list_runs(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0) -> List[SeoPlannerRun]:
        return await self.repository.list_runs(project_id, tenant_id, limit=limit, offset=offset)

    async def list_tasks(
        self,
        project_id: UUID,
        tenant_id: UUID,
        status: Optional[SeoTaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SeoTask]:
        return await self.repository.list_tasks(project_id, tenant_id, status=status, limit=limit, offset=offset)

    async def get_task(self, task_id: UUID, tenant_id: UUID) -> Optional[SeoTask]:
        return await self.repository.get_task(task_id, tenant_id)

    async def update_task_status(self, task_id: UUID, tenant_id: UUID, status: SeoTaskStatus) -> SeoTask:
        task = await self.repository.get_task(task_id, tenant_id)
        if not task:
            raise ValueError("SEO task not found")
        task = await self.repository.set_task_status(task, status)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def get_report(self, run_id: UUID, tenant_id: UUID) -> Optional[SeoWeeklyReport]:
        return await self.repository.get_report(run_id, tenant_id)

    async def project_summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        tasks = await self.repository.list_tasks(project_id, tenant_id, limit=1000)
        runs = await self.repository.list_runs(project_id, tenant_id, limit=1)
        by_status = Counter(self._enum_value(task.status) for task in tasks)
        by_priority = Counter(self._enum_value(task.priority) for task in tasks)
        open_tasks = [
            task for task in tasks
            if self._enum_value(task.status) in {
                SeoTaskStatus.todo.value,
                SeoTaskStatus.in_progress.value,
                SeoTaskStatus.approved.value,
            }
        ]
        return {
            "project_id": project_id,
            "open_tasks": len(open_tasks),
            "total_tasks": len(tasks),
            "tasks_by_status": dict(by_status),
            "tasks_by_priority": dict(by_priority),
            "latest_run_id": runs[0].id if runs else None,
            "latest_run_status": runs[0].status if runs else None,
            "top_tasks": tasks[:10],
        }

    async def _collect_signals(self, run: SeoPlannerRun) -> dict:
        crawl = await self.repository.latest_crawl(run.project_id, run.tenant_id)
        crawl_id = getattr(crawl, "id", None)
        audit = await self.repository.latest_audit(crawl_id, run.project_id, run.tenant_id)
        semantic_run = await self.repository.latest_semantic_run(crawl_id, run.project_id, run.tenant_id)
        content_run = await self.repository.latest_content_run(crawl_id, run.project_id, run.tenant_id)
        geo_run = await self.repository.latest_geo_run(crawl_id, run.project_id, run.tenant_id)
        gsc_sync = await self.repository.latest_gsc_sync(run.project_id, run.tenant_id)
        gsc_import = await self.repository.latest_search_console_import(run.project_id, run.tenant_id)
        blog_plan = await self.repository.latest_blog_plan(run.project_id, run.tenant_id)
        repo_scan = await self.repository.latest_repo_scan(run.project_id, run.tenant_id)

        return {
            "ids": {
                "crawl_id": crawl_id,
                "audit_id": getattr(audit, "id", None),
                "semantic_run_id": getattr(semantic_run, "id", None),
                "internal_link_run_id": None,
                "content_optimization_run_id": getattr(content_run, "id", None),
                "geo_aeo_run_id": getattr(geo_run, "id", None),
                "gsc_sync_job_id": getattr(gsc_sync, "id", None),
                "blog_plan_id": getattr(blog_plan, "id", None),
                "repo_scan_run_id": getattr(repo_scan, "id", None),
            },
            "crawl": crawl,
            "audit": audit,
            "semantic_run": semantic_run,
            "content_run": content_run,
            "geo_run": geo_run,
            "gsc_sync": gsc_sync,
            "gsc_import": gsc_import,
            "blog_plan": blog_plan,
            "repo_scan": repo_scan,
            "has_repo_connection": await self.repository.has_repo_connection(run.project_id, run.tenant_id),
            "has_knowledge": await self.repository.has_knowledge(run.project_id, run.tenant_id),
            "audit_issues": await self.repository.list_audit_issues(run.project_id, run.tenant_id),
            "gsc_opportunities": await self.repository.list_gsc_opportunities(run.project_id, run.tenant_id),
            "content_suggestions": await self.repository.list_content_suggestions(run.project_id, run.tenant_id),
            "geo_recommendations": await self.repository.list_geo_recommendations(run.project_id, run.tenant_id),
            "internal_link_recommendations": await self.repository.list_internal_link_recommendations(run.project_id, run.tenant_id),
            "blog_topics": await self.repository.list_blog_topics(run.project_id, run.tenant_id),
            "repo_patches": await self.repository.list_repo_patches(run.project_id, run.tenant_id),
            "repo_issues": await self.repository.list_repo_issues(run.project_id, run.tenant_id),
        }

    def _task_candidates(self, signals: dict) -> List[TaskCandidate]:
        candidates: List[TaskCandidate] = []
        candidates.extend(self._tasks_from_gsc(signals["gsc_opportunities"]))
        candidates.extend(self._tasks_from_audit(signals["audit_issues"]))
        candidates.extend(self._tasks_from_content(signals["content_suggestions"]))
        candidates.extend(self._tasks_from_geo(signals["geo_recommendations"]))
        candidates.extend(self._tasks_from_internal_links(signals["internal_link_recommendations"]))
        candidates.extend(self._tasks_from_blogs(signals["blog_topics"], has_knowledge=signals["has_knowledge"]))
        candidates.extend(self._tasks_from_repo(signals["repo_patches"], signals["repo_issues"]))
        if not candidates:
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.manual_review,
                    title="Review SEO operating system inputs",
                    description="No active crawl, audit, GSC, content, blog, or repo signals were available. Connect data sources or run a crawl to populate the weekly planner.",
                    source_type=SeoTaskSourceType.planner,
                    priority_score=30,
                    estimated_impact=SeoTaskImpact.medium,
                    effort=SeoTaskEffort.low,
                )
            )
        return candidates

    def _tasks_from_gsc(self, opportunities) -> List[TaskCandidate]:
        candidates = []
        for opp in opportunities:
            opp_type = self._enum_value(opp.opportunity_type)
            query = getattr(opp, "query", None)
            page_url = getattr(opp, "page_url", None)
            if opp_type in {
                SearchConsoleOpportunityType.high_impressions_low_ctr.value,
                SearchConsoleOpportunityType.ctr_drop.value,
                SearchConsoleOpportunityType.metadata_rewrite.value,
            }:
                task_type = SeoTaskType.metadata_rewrite
                title = f"Rewrite metadata for {query or page_url or 'ranking page'}"
                effort = SeoTaskEffort.low
            elif opp_type == SearchConsoleOpportunityType.internal_link_support.value:
                task_type = SeoTaskType.internal_link
                title = f"Add internal link support for {query or page_url or 'ranking page'}"
                effort = SeoTaskEffort.medium
            elif opp_type == SearchConsoleOpportunityType.blog_support.value:
                task_type = SeoTaskType.blog_topic
                title = f"Plan supporting blog for {query or 'Search Console opportunity'}"
                effort = SeoTaskEffort.medium
            else:
                task_type = SeoTaskType.content_refresh
                title = f"Refresh content for {query or page_url or 'Search Console opportunity'}"
                effort = SeoTaskEffort.medium
            candidates.append(
                TaskCandidate(
                    task_type=task_type,
                    title=title[:255],
                    description=getattr(opp, "recommended_action", None) or getattr(opp, "reason", "") or "Review this Search Console opportunity.",
                    source_type=SeoTaskSourceType.search_console,
                    source_reference_id=opp.id,
                    target_page_url=page_url,
                    target_keyword=query,
                    priority_score=float(getattr(opp, "priority_score", 60) or 60),
                    estimated_impact=SeoTaskImpact.high,
                    effort=effort,
                )
            )
        return candidates

    def _tasks_from_audit(self, issues) -> List[TaskCandidate]:
        candidates = []
        for issue in issues:
            issue_type = str(getattr(issue, "issue_type", "") or "")
            category = self._enum_value(getattr(issue, "category", ""))
            if "schema" in issue_type or category == SEOIssueCategory.schema.value:
                task_type = SeoTaskType.schema_addition
            elif "sitemap" in issue_type or "robots" in issue_type:
                task_type = SeoTaskType.sitemap_robots_fix
            elif "title" in issue_type or "meta_description" in issue_type or category == SEOIssueCategory.metadata.value:
                task_type = SeoTaskType.metadata_rewrite
            elif category == SEOIssueCategory.content.value:
                task_type = SeoTaskType.content_refresh
            else:
                task_type = SeoTaskType.technical_seo_fix
            candidates.append(
                TaskCandidate(
                    task_type=task_type,
                    title=getattr(issue, "title", None) or f"Fix {issue_type.replace('_', ' ')}",
                    description=getattr(issue, "recommendation", None) or getattr(issue, "message", "") or "Resolve this technical SEO issue.",
                    source_type=SeoTaskSourceType.audit_issue,
                    source_reference_id=issue.id,
                    target_page_url=getattr(issue, "url", None),
                    priority_score=self._score_from_severity(getattr(issue, "severity", None), getattr(issue, "score_impact", 0)),
                    estimated_impact=self._impact_from_severity(getattr(issue, "severity", None)),
                    effort=SeoTaskEffort.low if task_type in {SeoTaskType.metadata_rewrite, SeoTaskType.schema_addition} else SeoTaskEffort.medium,
                )
            )
        return candidates

    def _tasks_from_content(self, suggestions) -> List[TaskCandidate]:
        type_map = {
            ContentOptimizationSuggestionType.seo_title.value: SeoTaskType.metadata_rewrite,
            ContentOptimizationSuggestionType.meta_description.value: SeoTaskType.metadata_rewrite,
            ContentOptimizationSuggestionType.schema.value: SeoTaskType.schema_addition,
            ContentOptimizationSuggestionType.content_refresh.value: SeoTaskType.content_refresh,
            ContentOptimizationSuggestionType.internal_link_context.value: SeoTaskType.internal_link,
            ContentOptimizationSuggestionType.answer_block.value: SeoTaskType.geo_aeo_improvement,
            ContentOptimizationSuggestionType.faq.value: SeoTaskType.geo_aeo_improvement,
            ContentOptimizationSuggestionType.h1.value: SeoTaskType.content_refresh,
            ContentOptimizationSuggestionType.headings.value: SeoTaskType.content_refresh,
        }
        candidates = []
        for suggestion in suggestions:
            suggestion_type = self._enum_value(suggestion.suggestion_type)
            task_type = type_map.get(suggestion_type, SeoTaskType.content_refresh)
            evidence = getattr(suggestion, "evidence", None) or {}
            candidates.append(
                TaskCandidate(
                    task_type=task_type,
                    title=f"Review {suggestion_type.replace('_', ' ')} suggestion",
                    description=getattr(suggestion, "reason", None) or "Review this content optimization suggestion.",
                    source_type=SeoTaskSourceType.content_optimization,
                    source_reference_id=suggestion.id,
                    target_page_url=evidence.get("url") if isinstance(evidence, dict) else None,
                    priority_score=float(getattr(suggestion, "priority_score", 55) or 55),
                    estimated_impact=SeoTaskImpact.high if float(getattr(suggestion, "priority_score", 0) or 0) >= 75 else SeoTaskImpact.medium,
                    effort=SeoTaskEffort.low if task_type in {SeoTaskType.metadata_rewrite, SeoTaskType.schema_addition} else SeoTaskEffort.medium,
                )
            )
        return candidates

    def _tasks_from_geo(self, recommendations) -> List[TaskCandidate]:
        candidates = []
        for rec in recommendations:
            rec_type = self._enum_value(rec.recommendation_type)
            task_type = SeoTaskType.schema_addition if rec_type == GeoAeoRecommendationType.schema.value else SeoTaskType.geo_aeo_improvement
            evidence = getattr(rec, "evidence", None) or {}
            candidates.append(
                TaskCandidate(
                    task_type=task_type,
                    title=f"Improve AI-search readiness: {rec_type.replace('_', ' ')}",
                    description=getattr(rec, "recommendation_text", None) or getattr(rec, "reason", "") or "Review GEO/AEO recommendation.",
                    source_type=SeoTaskSourceType.geo_aeo,
                    source_reference_id=rec.id,
                    target_page_url=evidence.get("url") if isinstance(evidence, dict) else None,
                    priority_score=float(getattr(rec, "priority_score", 55) or 55),
                    estimated_impact=SeoTaskImpact.high if float(getattr(rec, "priority_score", 0) or 0) >= 75 else SeoTaskImpact.medium,
                    effort=SeoTaskEffort.medium,
                )
            )
        return candidates

    def _tasks_from_internal_links(self, recommendations) -> List[TaskCandidate]:
        return [
            TaskCandidate(
                task_type=SeoTaskType.internal_link,
                title=f"Add internal link to {getattr(rec, 'target_url', 'target page')}",
                description=getattr(rec, "reason", None) or "Review this internal linking recommendation.",
                source_type=SeoTaskSourceType.internal_linking,
                source_reference_id=rec.id,
                target_page_url=getattr(rec, "target_url", None),
                priority_score=float(getattr(rec, "priority_score", 50) or 50),
                estimated_impact=SeoTaskImpact.medium,
                effort=SeoTaskEffort.low,
            )
            for rec in recommendations
        ]

    def _tasks_from_blogs(self, topics, has_knowledge: bool) -> List[TaskCandidate]:
        candidates = []
        for topic in topics:
            status = self._enum_value(topic.status)
            task_type = SeoTaskType.blog_draft if status == BlogTopicStatus.approved.value else SeoTaskType.blog_topic
            quality_note = "" if has_knowledge else " Knowledge base is empty, so draft quality may be limited until business context is added."
            candidates.append(
                TaskCandidate(
                    task_type=task_type,
                    title=(getattr(topic, "title", None) or getattr(topic, "target_keyword", "Blog topic"))[:255],
                    description=(getattr(topic, "reason", None) or "Review this blog engine topic.") + quality_note,
                    source_type=SeoTaskSourceType.blog_engine,
                    source_reference_id=topic.id,
                    target_keyword=getattr(topic, "target_keyword", None),
                    priority_score=float(getattr(topic, "priority_score", 50) or 50),
                    estimated_impact=SeoTaskImpact.high if float(getattr(topic, "priority_score", 0) or 0) >= 75 else SeoTaskImpact.medium,
                    effort=SeoTaskEffort.medium if task_type == SeoTaskType.blog_topic else SeoTaskEffort.high,
                )
            )
        return candidates

    def _tasks_from_repo(self, patches, issues) -> List[TaskCandidate]:
        candidates = []
        for patch in patches:
            patch_type = self._enum_value(patch.patch_type)
            task_type = SeoTaskType.sitemap_robots_fix if patch_type in {
                SeoCodePatchType.sitemap_update.value,
                SeoCodePatchType.robots_update.value,
            } else SeoTaskType.repo_patch_review
            candidates.append(
                TaskCandidate(
                    task_type=task_type,
                    title=f"Review SEO code patch for {getattr(patch, 'file_path', 'repository file')}",
                    description=getattr(patch, "explanation", None) or "Review this SEO-only code patch before applying.",
                    source_type=SeoTaskSourceType.repo_agent,
                    source_reference_id=patch.id,
                    target_page_url=getattr(patch, "file_path", None),
                    priority_score=75 if self._enum_value(getattr(patch, "status", "")) == "approved" else 60,
                    estimated_impact=SeoTaskImpact.medium,
                    effort=SeoTaskEffort.low,
                )
            )
        for issue in issues:
            issue_type = self._enum_value(issue.issue_type)
            if issue_type not in {
                SeoCodeIssueType.missing_metadata.value,
                SeoCodeIssueType.weak_metadata.value,
                SeoCodeIssueType.missing_sitemap.value,
                SeoCodeIssueType.missing_robots.value,
            }:
                continue
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.technical_seo_fix,
                    title=getattr(issue, "title", None) or "Review repository SEO issue",
                    description=getattr(issue, "recommended_fix", None) or getattr(issue, "description", "") or "Review this repository SEO issue.",
                    source_type=SeoTaskSourceType.repo_agent,
                    source_reference_id=issue.id,
                    priority_score=self._score_from_severity(getattr(issue, "severity", None), 0),
                    estimated_impact=self._impact_from_severity(getattr(issue, "severity", None)),
                    effort=SeoTaskEffort.low,
                )
            )
        return candidates

    def _task_values(self, run: SeoPlannerRun, candidate: TaskCandidate) -> dict:
        priority = candidate.priority or self._priority_from_score(candidate.priority_score)
        return {
            "tenant_id": run.tenant_id,
            "project_id": run.project_id,
            "planner_run_id": run.id,
            "task_type": candidate.task_type,
            "title": candidate.title[:255],
            "description": candidate.description,
            "source_type": candidate.source_type,
            "source_reference_id": candidate.source_reference_id,
            "target_page_url": candidate.target_page_url,
            "target_keyword": candidate.target_keyword[:255] if candidate.target_keyword else None,
            "priority": priority,
            "priority_score": max(0, min(100, float(candidate.priority_score or 0))),
            "estimated_impact": candidate.estimated_impact,
            "effort": candidate.effort,
            "status": SeoTaskStatus.todo,
            "due_date": run.target_week_end,
        }

    def _report_values(self, run: SeoPlannerRun, signals: dict, tasks: List[SeoTask], created_count: int) -> dict:
        by_type = Counter(self._enum_value(task.task_type) for task in tasks)
        by_priority = Counter(self._enum_value(task.priority) for task in tasks)
        high = int(by_priority.get("high", 0) + by_priority.get("critical", 0))
        summary = (
            f"Weekly SEO plan created {created_count} new tasks and refreshed {max(len(tasks) - created_count, 0)} existing tasks. "
            f"{high} high-priority tasks need attention across technical SEO, content, Search Console, internal links, blogs, and repository review."
        )
        if not signals["gsc_sync"] and not signals["gsc_import"]:
            summary += " Search Console data is not connected, so GSC opportunities were skipped."
        if not signals["has_repo_connection"]:
            summary += " No repository connection is available, so code patch planning was skipped."
        if not signals["has_knowledge"]:
            summary += " Knowledge base content is empty, so blog/content planning should be reviewed carefully."
        top_tasks = [
            {
                "task_id": str(task.id),
                "title": task.title,
                "task_type": self._enum_value(task.task_type),
                "priority": self._enum_value(task.priority),
                "priority_score": task.priority_score,
            }
            for task in sorted(tasks, key=lambda item: item.priority_score or 0, reverse=True)[:8]
        ]
        return {
            "tenant_id": run.tenant_id,
            "project_id": run.project_id,
            "planner_run_id": run.id,
            "summary": summary,
            "wins": [
                {"label": "Planner completed", "value": True},
                {"label": "Signals converted", "value": len(tasks)},
            ],
            "risks": self._report_risks(signals),
            "technical_seo_summary": {
                "audit_issues": len(signals["audit_issues"]),
                "repo_issues": len(signals["repo_issues"]),
                "technical_tasks": by_type.get(SeoTaskType.technical_seo_fix.value, 0),
                "schema_tasks": by_type.get(SeoTaskType.schema_addition.value, 0),
            },
            "search_console_summary": {
                "opportunities": len(signals["gsc_opportunities"]),
                "metadata_tasks": by_type.get(SeoTaskType.metadata_rewrite.value, 0),
                "content_refresh_tasks": by_type.get(SeoTaskType.content_refresh.value, 0),
                "latest_sync_job_id": str(signals["ids"].get("gsc_sync_job_id")) if signals["ids"].get("gsc_sync_job_id") else None,
            },
            "content_summary": {
                "content_suggestions": len(signals["content_suggestions"]),
                "content_refresh_tasks": by_type.get(SeoTaskType.content_refresh.value, 0),
                "metadata_tasks": by_type.get(SeoTaskType.metadata_rewrite.value, 0),
            },
            "geo_aeo_summary": {
                "recommendations": len(signals["geo_recommendations"]),
                "tasks": by_type.get(SeoTaskType.geo_aeo_improvement.value, 0),
            },
            "blog_summary": {
                "topics": len(signals["blog_topics"]),
                "blog_topic_tasks": by_type.get(SeoTaskType.blog_topic.value, 0),
                "blog_draft_tasks": by_type.get(SeoTaskType.blog_draft.value, 0),
                "knowledge_available": signals["has_knowledge"],
            },
            "repo_patch_summary": {
                "repo_connected": signals["has_repo_connection"],
                "patches": len(signals["repo_patches"]),
                "patch_review_tasks": by_type.get(SeoTaskType.repo_patch_review.value, 0),
            },
            "next_week_priorities": top_tasks,
        }

    def _report_risks(self, signals: dict) -> list[dict]:
        risks = []
        if not signals["crawl"]:
            risks.append({"type": "crawl_missing", "message": "No completed crawl is available."})
        if not signals["gsc_sync"] and not signals["gsc_import"]:
            risks.append({"type": "gsc_missing", "message": "Search Console is not connected or imported."})
        if not signals["has_knowledge"]:
            risks.append({"type": "knowledge_missing", "message": "Knowledge base is empty."})
        if not signals["has_repo_connection"]:
            risks.append({"type": "repo_missing", "message": "No repository connection is configured."})
        return risks

    def _score_from_severity(self, severity, score_impact: int = 0) -> float:
        severity_value = self._enum_value(severity)
        base = {
            SEOIssueSeverity.critical.value: 95,
            SEOIssueSeverity.high.value: 80,
            SEOIssueSeverity.medium.value: 60,
            SEOIssueSeverity.low.value: 35,
        }.get(severity_value, 50)
        return max(base, min(100, base + abs(int(score_impact or 0))))

    def _impact_from_severity(self, severity) -> SeoTaskImpact:
        severity_value = self._enum_value(severity)
        if severity_value in {SEOIssueSeverity.critical.value, SEOIssueSeverity.high.value}:
            return SeoTaskImpact.high
        if severity_value == SEOIssueSeverity.low.value:
            return SeoTaskImpact.low
        return SeoTaskImpact.medium

    def _priority_from_score(self, score: float) -> SeoTaskPriority:
        if score >= 90:
            return SeoTaskPriority.critical
        if score >= 70:
            return SeoTaskPriority.high
        if score >= 40:
            return SeoTaskPriority.medium
        return SeoTaskPriority.low

    def _week_start(self, now: datetime) -> datetime:
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)

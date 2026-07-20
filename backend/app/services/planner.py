"""Weekly autonomous SEO planner orchestration service."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
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
from app.services.project_context import project_business_context

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
            await self.db.rollback()
            run = await self.repository.get_run(run_id, tenant_id)
            if not run:
                raise
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

    async def list_duplicate_tasks(self, project_id: UUID, tenant_id: UUID) -> dict:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        tasks = await self.repository.list_tasks_for_dedupe(project_id, tenant_id)
        groups = self._duplicate_groups(tasks)
        return self._dedupe_response(project_id, groups, dry_run=True, skipped_count=0)

    async def dedupe_preview(self, project_id: UUID, tenant_id: UUID) -> dict:
        return await self.list_duplicate_tasks(project_id, tenant_id)

    async def dedupe_apply(self, project_id: UUID, tenant_id: UUID) -> dict:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        tasks = await self.repository.list_tasks_for_dedupe(project_id, tenant_id)
        groups = self._duplicate_groups(tasks)
        duplicate_tasks = [task for group in groups for task in group["duplicates"]]
        skipped_count = 0
        for task in duplicate_tasks:
            if self._enum_value(task.status) in {
                SeoTaskStatus.todo.value,
                SeoTaskStatus.in_progress.value,
                SeoTaskStatus.approved.value,
            }:
                await self.repository.set_task_status(task, SeoTaskStatus.skipped)
                skipped_count += 1
        await self.db.commit()
        return self._dedupe_response(project_id, groups, dry_run=False, skipped_count=skipped_count)

    async def _collect_signals(self, run: SeoPlannerRun) -> dict:
        project = await self.repository.get_project(run.project_id, run.tenant_id)
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
            "project": project,
            "project_context": project_business_context(project),
            "has_repo_connection": await self.repository.has_repo_connection(run.project_id, run.tenant_id),
            "has_knowledge": await self.repository.has_knowledge(run.project_id, run.tenant_id),
            "audit_issues": await self.repository.list_audit_issues(run.project_id, run.tenant_id),
            "pagespeed_opportunities": await self.repository.list_pagespeed_opportunities(run.project_id, run.tenant_id),
            "gsc_opportunities": await self.repository.list_gsc_opportunities(run.project_id, run.tenant_id),
            "keyword_baselines": await self.repository.list_keyword_baselines(run.project_id, run.tenant_id),
            "content_suggestions": await self.repository.list_content_suggestions(run.project_id, run.tenant_id),
            "geo_recommendations": await self.repository.list_geo_recommendations(run.project_id, run.tenant_id),
            "internal_link_recommendations": await self.repository.list_internal_link_recommendations(run.project_id, run.tenant_id),
            "blog_topics": await self.repository.list_blog_topics(run.project_id, run.tenant_id),
            "repo_patches": await self.repository.list_repo_patches(run.project_id, run.tenant_id),
            "repo_issues": await self.repository.list_repo_issues(run.project_id, run.tenant_id),
            "rank_summary": await self._rank_summary(run.project_id, run.tenant_id),
            "impact_summary": await self._impact_summary(run.project_id, run.tenant_id),
            "framework": await self._detected_framework(run.project_id, run.tenant_id),
        }

    async def _detected_framework(self, project_id: UUID, tenant_id: UUID) -> Optional[str]:
        """The project's detected framework/CMS from the Technology Fingerprint,
        used to turn generic tasks into framework-specific ones (never hardcoded
        here — the Knowledge Base is queried during enrichment)."""
        try:
            from app.models.fingerprint import TechnologyFingerprint

            fp = (await self.db.execute(
                select(TechnologyFingerprint).where(
                    TechnologyFingerprint.project_id == project_id,
                    TechnologyFingerprint.tenant_id == tenant_id,
                )
            )).scalars().first()
            if not fp:
                return None
            return fp.primary_cms or fp.primary_framework
        except Exception:
            return None

    def _task_candidates(self, signals: dict) -> List[TaskCandidate]:
        candidates: List[TaskCandidate] = []
        candidates.extend(self._tasks_from_gsc(signals["gsc_opportunities"]))
        candidates.extend(self._tasks_from_serp_snapshots(signals["gsc_opportunities"]))
        candidates.extend(self._tasks_from_keyword_baselines(signals["keyword_baselines"]))
        candidates.extend(self._tasks_from_audit(signals["audit_issues"]))
        candidates.extend(self._tasks_from_pagespeed(signals["pagespeed_opportunities"]))
        candidates.extend(self._tasks_from_content(signals["content_suggestions"]))
        candidates.extend(self._tasks_from_geo(signals["geo_recommendations"]))
        candidates.extend(self._tasks_from_internal_links(signals["internal_link_recommendations"]))
        candidates.extend(self._tasks_from_blogs(signals["blog_topics"], has_knowledge=signals["has_knowledge"]))
        candidates.extend(self._tasks_from_repo(signals["repo_patches"], signals["repo_issues"]))
        candidates.extend(self._tasks_from_project_context(signals["project_context"]))
        candidates = self._apply_framework_strategy(candidates, signals.get("framework"))
        if not candidates:
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.manual_review,
                    title="Review project context and SEO operating system inputs",
                    description=(
                        "No active crawl, audit, GSC, content, blog, or repo signals were available. "
                        "Review the project context, connect data sources, or run a crawl to populate the weekly planner."
                    ),
                    source_type=SeoTaskSourceType.planner,
                    priority_score=30,
                    estimated_impact=SeoTaskImpact.medium,
                    effort=SeoTaskEffort.low,
                )
            )
        return candidates

    def _apply_framework_strategy(self, candidates: List[TaskCandidate], framework: Optional[str]) -> List[TaskCandidate]:
        """Turn generic tasks into framework-specific ones by querying the
        Framework Knowledge Base (e.g. "Improve Metadata" -> Next.js
        generateMetadata() / WordPress Yoast). No framework rules are hardcoded
        here; the KB is the single source of truth."""
        if not framework:
            return candidates
        from app.framework_kb import get_framework_profile, task_action_for

        profile = get_framework_profile(framework)
        if not profile:
            return candidates
        for c in candidates:
            action = task_action_for(framework, self._enum_value(c.task_type))
            if not action:
                continue
            # Prefix the framework action so the task is unmistakably specific,
            # and append the "how" to the description. Titles stay <=255 chars.
            tag = f"[{profile.display_name}] {action.action}: "
            if not c.title.startswith(f"[{profile.display_name}]"):
                c.title = (tag + c.title)[:255]
            c.description = f"{c.description}\n\nFramework strategy ({profile.display_name}): {action.detail}"
            if action.safe_files:
                c.description += f" SEO-safe targets: {', '.join(action.safe_files[:3])}."
        return candidates

    def _tasks_from_project_context(self, context: dict) -> List[TaskCandidate]:
        candidates: List[TaskCandidate] = []
        target_keywords = self._context_list(context.get("target_keywords"))
        primary_services = self._context_list(context.get("primary_services"))
        seo_goal = self._context_text(context.get("seo_goal"))
        audience = self._context_text(context.get("target_audience"))
        location = self._context_text(context.get("target_location"))

        if seo_goal:
            detail_parts = [f"SEO goal: {seo_goal}"]
            if audience:
                detail_parts.append(f"Audience: {audience}")
            if location:
                detail_parts.append(f"Location: {location}")
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.manual_review,
                    title="Review SEO goal alignment",
                    description="Use the onboarding context to align this week's SEO work. " + " ".join(detail_parts),
                    source_type=SeoTaskSourceType.planner,
                    priority_score=45,
                    estimated_impact=SeoTaskImpact.medium,
                    effort=SeoTaskEffort.low,
                )
            )

        for keyword in target_keywords[:3]:
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.content_refresh,
                    title=f"Map target keyword: {keyword}"[:255],
                    description=(
                        "Review crawl and content outputs against this manually provided target keyword. "
                        "Use real page and Search Console data before claiming ranking movement."
                    ),
                    source_type=SeoTaskSourceType.planner,
                    target_keyword=keyword,
                    priority_score=42,
                    estimated_impact=SeoTaskImpact.medium,
                    effort=SeoTaskEffort.low,
                )
            )

        for service in primary_services[:2]:
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.content_refresh,
                    title=f"Review service page coverage for {service}"[:255],
                    description=(
                        "Use the project services from onboarding as content context. "
                        "Verify an existing page or create a brief before adding new copy."
                    ),
                    source_type=SeoTaskSourceType.planner,
                    target_keyword=service,
                    priority_score=40,
                    estimated_impact=SeoTaskImpact.medium,
                    effort=SeoTaskEffort.medium,
                )
            )
        return candidates

    def _tasks_from_keyword_baselines(self, baselines) -> List[TaskCandidate]:
        candidates: List[TaskCandidate] = []
        for baseline in baselines[:50]:
            keyword = self._context_text(getattr(baseline, "keyword", None))
            if not keyword:
                continue
            position = getattr(baseline, "current_position", None)
            current_url = self._context_text(getattr(baseline, "current_url", None))
            location = self._context_text(getattr(baseline, "target_location", None))
            device = self._enum_value(getattr(baseline, "device", "desktop"))
            context_bits = [f"Keyword: {keyword}", f"Device: {device}"]
            if location:
                context_bits.append(f"Location: {location}")

            if position is None:
                description = (
                    "Manually check the current search position for this baseline keyword. "
                    "Do not use automated Google scraping; record the observed position or real imported data. "
                    + " ".join(context_bits)
                )
                if not current_url:
                    description += " Also map this keyword to the best target page before planning content edits."
                candidates.append(
                    TaskCandidate(
                        task_type=SeoTaskType.manual_review,
                        title=f"Manually check keyword position: {keyword}"[:255],
                        description=description,
                        source_type=SeoTaskSourceType.planner,
                        source_reference_id=getattr(baseline, "id", None),
                        target_keyword=keyword,
                        priority_score=50,
                        estimated_impact=SeoTaskImpact.medium,
                        effort=SeoTaskEffort.low,
                    )
                )
                continue

            if int(position) > 20:
                description = (
                    f"Manual baseline shows position {position}, outside the top 20. "
                    "Review the mapped page and improve the content, metadata, internal links, or page intent alignment using real crawl, content, or manually entered data only. "
                    + " ".join(context_bits)
                )
                if not current_url:
                    description += " No current URL is mapped, so choose a target page before editing."
                candidates.append(
                    TaskCandidate(
                        task_type=SeoTaskType.content_refresh,
                        title=f"Improve content for keyword outside top 20: {keyword}"[:255],
                        description=description,
                        source_type=SeoTaskSourceType.planner,
                        source_reference_id=getattr(baseline, "id", None),
                        target_page_url=current_url or None,
                        target_keyword=keyword,
                        priority_score=72 if int(position) > 50 else 62,
                        estimated_impact=SeoTaskImpact.medium,
                        effort=SeoTaskEffort.medium,
                    )
                )
                continue

            if not current_url:
                candidates.append(
                    TaskCandidate(
                        task_type=SeoTaskType.manual_review,
                        title=f"Map keyword to target page: {keyword}"[:255],
                        description=(
                            "This manual keyword baseline has a position but no current URL. "
                            "Map it to the page that should own the query before making optimization recommendations; do not scrape search results automatically. "
                            + " ".join(context_bits)
                        ),
                        source_type=SeoTaskSourceType.planner,
                        source_reference_id=getattr(baseline, "id", None),
                        target_keyword=keyword,
                        priority_score=45,
                        estimated_impact=SeoTaskImpact.medium,
                        effort=SeoTaskEffort.low,
                    )
                )
        return candidates

    async def _rank_summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        try:
            from app.services.rank_tracking import RankTrackingService

            return await RankTrackingService(self.db).summary(project_id, tenant_id)
        except Exception as exc:
            return {"error": str(exc)}

    async def _impact_summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        try:
            from app.services.impact import SeoImpactService

            return await SeoImpactService(self.db).summary(project_id, tenant_id)
        except Exception as exc:
            return {"error": str(exc)}

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

    def _tasks_from_serp_snapshots(self, opportunities) -> List[TaskCandidate]:
        candidates = []
        seen_queries = set()
        for opp in opportunities[:10]:
            query = getattr(opp, "query", None)
            if not query or query.lower() in seen_queries:
                continue
            seen_queries.add(query.lower())
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.manual_review,
                    title=f"Capture manual SERP screenshot for keyword {query}"[:255],
                    description=(
                        "Capture manual SERP screenshot for keyword "
                        f"{query}. SERP snapshots are manual evidence; official rank tracking uses GSC average position."
                    ),
                    source_type=SeoTaskSourceType.search_console,
                    source_reference_id=getattr(opp, "id", None),
                    target_page_url=getattr(opp, "page_url", None),
                    target_keyword=query,
                    priority_score=max(35, float(getattr(opp, "priority_score", 50) or 50) - 10),
                    estimated_impact=SeoTaskImpact.medium,
                    effort=SeoTaskEffort.low,
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

    # Lighthouse opportunity id -> (human action, code-fixable-ish, effort).
    _PAGESPEED_ACTIONS = {
        "modern-image-formats": ("Convert images to WebP/AVIF", SeoTaskEffort.medium),
        "uses-webp-images": ("Convert images to WebP/AVIF", SeoTaskEffort.medium),
        "offscreen-images": ("Lazy-load offscreen images", SeoTaskEffort.low),
        "unused-javascript": ("Remove or split unused JavaScript", SeoTaskEffort.high),
        "unused-css-rules": ("Remove unused CSS", SeoTaskEffort.medium),
        "render-blocking-resources": ("Defer render-blocking CSS/JS", SeoTaskEffort.medium),
        "uses-text-compression": ("Enable Brotli/Gzip compression", SeoTaskEffort.low),
        "uses-long-cache-ttl": ("Improve static asset cache headers", SeoTaskEffort.low),
        "uses-responsive-images": ("Serve appropriately sized images", SeoTaskEffort.medium),
        "efficient-animated-content": ("Replace GIFs with video", SeoTaskEffort.medium),
        "unminified-javascript": ("Minify JavaScript", SeoTaskEffort.low),
        "unminified-css": ("Minify CSS", SeoTaskEffort.low),
        "server-response-time": ("Reduce server response time (TTFB)", SeoTaskEffort.high),
        "uses-rel-preload": ("Preload key requests (e.g. fonts)", SeoTaskEffort.low),
        "font-display": ("Set font-display: swap", SeoTaskEffort.low),
        "layout-shift-elements": ("Reduce layout shift (reserve space)", SeoTaskEffort.medium),
    }

    def _tasks_from_pagespeed(self, opportunities) -> List[TaskCandidate]:
        """Turn Core Web Vitals (PageSpeed) opportunities into planner tasks that
        sit alongside audit/robots/sitemap/GSC tasks."""
        import uuid as _uuid

        candidates = []
        for opp in opportunities or []:
            opp_id = opp.get("id") if isinstance(opp, dict) else getattr(opp, "id", "")
            savings = (opp.get("savings_ms") if isinstance(opp, dict) else getattr(opp, "savings_ms", None)) or 0
            action, effort = self._PAGESPEED_ACTIONS.get(opp_id, (None, SeoTaskEffort.medium))
            title = opp.get("title") if isinstance(opp, dict) else getattr(opp, "title", None)
            title = action or title or f"Improve performance: {str(opp_id).replace('-', ' ')}"
            # Larger savings -> higher priority / impact.
            if savings >= 1000:
                priority_score, impact = 78, SeoTaskImpact.high
            elif savings >= 400:
                priority_score, impact = 62, SeoTaskImpact.medium
            else:
                priority_score, impact = 45, SeoTaskImpact.low
            candidates.append(
                TaskCandidate(
                    task_type=SeoTaskType.technical_seo_fix,
                    title=title,
                    description=(opp.get("description") if isinstance(opp, dict) else getattr(opp, "description", None))
                    or "Resolve this Core Web Vitals / PageSpeed opportunity to improve performance.",
                    source_type=SeoTaskSourceType.core_web_vitals,
                    # Stable per-opportunity id (not the run id) so each distinct
                    # opportunity is its own task and re-analysis updates it in place
                    # instead of collapsing every opportunity onto one task.
                    source_reference_id=_uuid.uuid5(_uuid.NAMESPACE_URL, f"cwv:{opp_id}") if opp_id else None,
                    target_page_url=opp.get("url") if isinstance(opp, dict) else getattr(opp, "url", None),
                    priority_score=priority_score,
                    estimated_impact=impact,
                    effort=effort,
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

    def _duplicate_groups(self, tasks: List[SeoTask]) -> List[dict]:
        exact_groups = self._groups_by_key(tasks, include_source_reference=True)
        exact_duplicate_ids = {
            str(task.id)
            for group in exact_groups
            for task in group["duplicates"]
        }
        near_candidates = [task for task in tasks if str(task.id) not in exact_duplicate_ids]
        near_groups = self._groups_by_key(near_candidates, include_source_reference=False)
        groups = exact_groups + [
            group for group in near_groups
            if not any(str(group["keep"].id) == str(existing["keep"].id) for existing in exact_groups)
        ]
        return sorted(
            groups,
            key=lambda group: (len(group["duplicates"]), float(getattr(group["keep"], "priority_score", 0) or 0)),
            reverse=True,
        )

    def _groups_by_key(self, tasks: List[SeoTask], *, include_source_reference: bool) -> List[dict]:
        buckets: Dict[tuple, List[SeoTask]] = {}
        for task in tasks:
            key = self._dedupe_key(task, include_source_reference=include_source_reference)
            buckets.setdefault(key, []).append(task)
        groups = []
        for key, items in buckets.items():
            if len(items) < 2:
                continue
            ordered = sorted(items, key=self._task_keep_sort_key, reverse=True)
            groups.append(
                {
                    "key": key,
                    "group_type": "exact" if include_source_reference else "near_duplicate",
                    "keep": ordered[0],
                    "duplicates": ordered[1:],
                }
            )
        return groups

    def _dedupe_key(self, task: SeoTask, *, include_source_reference: bool) -> tuple:
        return (
            str(getattr(task, "project_id", "")),
            self._enum_value(task.task_type),
            self._normalize_url(getattr(task, "target_page_url", None)),
            self._normalize_text(getattr(task, "target_keyword", None)),
            self._enum_value(task.source_type),
            str(getattr(task, "source_reference_id", "") or "") if include_source_reference else "",
            self._normalize_title(getattr(task, "title", "")),
        )

    def _task_keep_sort_key(self, task: SeoTask) -> tuple:
        updated_at = getattr(task, "updated_at", None) or getattr(task, "created_at", None) or datetime.min
        return (float(getattr(task, "priority_score", 0) or 0), updated_at)

    def _dedupe_response(self, project_id: UUID, groups: List[dict], *, dry_run: bool, skipped_count: int) -> dict:
        duplicate_task_count = sum(len(group["duplicates"]) for group in groups)
        return {
            "project_id": project_id,
            "dry_run": dry_run,
            "duplicate_groups": [self._duplicate_group_payload(group) for group in groups],
            "duplicate_group_count": len(groups),
            "duplicate_task_count": duplicate_task_count,
            "skipped_task_count": skipped_count,
        }

    def _duplicate_group_payload(self, group: dict) -> dict:
        keep = group["keep"]
        key = group["key"]
        return {
            "group_key": "|".join(str(part) for part in key),
            "group_type": group["group_type"],
            "task_type": keep.task_type,
            "source_type": keep.source_type,
            "target_page_url": getattr(keep, "target_page_url", None),
            "target_keyword": getattr(keep, "target_keyword", None),
            "normalized_title": self._normalize_title(getattr(keep, "title", "")),
            "keep_task": self._task_ref(keep),
            "duplicate_tasks": [self._task_ref(task) for task in group["duplicates"]],
        }

    def _task_ref(self, task: SeoTask) -> dict:
        return {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "priority_score": float(task.priority_score or 0),
            "updated_at": getattr(task, "updated_at", None),
            "source_reference_id": getattr(task, "source_reference_id", None),
        }

    def _normalize_url(self, value: Optional[str]) -> str:
        text = (value or "").strip().lower()
        if text.endswith("/") and text.count("/") > 2:
            text = text.rstrip("/")
        return text

    def _normalize_title(self, value: str) -> str:
        text = self._normalize_text(value)
        text = re.sub(r"https?://www\.", "https://", text)
        return text

    def _normalize_text(self, value: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    def _report_values(self, run: SeoPlannerRun, signals: dict, tasks: List[SeoTask], created_count: int) -> dict:
        by_type = Counter(self._enum_value(task.task_type) for task in tasks)
        by_priority = Counter(self._enum_value(task.priority) for task in tasks)
        keyword_baselines = signals.get("keyword_baselines") or []
        positioned_baselines = [
            baseline for baseline in keyword_baselines
            if getattr(baseline, "current_position", None) is not None
        ]
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
        report = {
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
                "manual_serp_snapshot_tasks": by_type.get(SeoTaskType.manual_review.value, 0),
                "keyword_baseline_summary": {
                    "total_keywords": len(keyword_baselines),
                    "top_10_count": len([
                        baseline for baseline in positioned_baselines
                        if int(getattr(baseline, "current_position", 101) or 101) <= 10
                    ]),
                    "top_20_count": len([
                        baseline for baseline in positioned_baselines
                        if int(getattr(baseline, "current_position", 101) or 101) <= 20
                    ]),
                    "missing_position_count": len(keyword_baselines) - len(positioned_baselines),
                },
                "rank_summary": signals.get("rank_summary") or {},
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
                "impact_summary": signals.get("impact_summary") or {},
            },
            "next_week_priorities": top_tasks,
        }
        for key in (
            "wins",
            "risks",
            "technical_seo_summary",
            "search_console_summary",
            "content_summary",
            "geo_aeo_summary",
            "blog_summary",
            "repo_patch_summary",
            "next_week_priorities",
        ):
            report[key] = self._json_safe(report[key])
        return report

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

    def _context_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item or "").strip()]
        if isinstance(value, str) and value != "Not provided":
            return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
        return []

    def _context_text(self, value: Any) -> str:
        text = str(value or "").strip()
        return "" if text == "Not provided" else text

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)

    def _json_safe(self, value):
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "model_dump"):
            return self._json_safe(value.model_dump(mode="json"))
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        if hasattr(value, "value"):
            return value.value
        return value

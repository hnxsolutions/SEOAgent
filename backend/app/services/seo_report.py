"""Client-facing report generation for completed one-click SEO runs."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOAuditRun, SEOIssue
from app.models.content_optimization import ContentOptimizationRun, ContentOptimizationSuggestion
from app.models.crawl import CrawlJob, CrawlPage
from app.models.planner import SeoPlannerRun, SeoTask
from app.models.project import Project
from app.models.search_console import GSCProperty, SearchConsoleImport, SearchConsoleImportStatus
from app.models.semantic import SemanticIndexedContent, SemanticIndexRun
from app.models.seo_run import SeoRun
from app.models.serp import SerpSnapshot
from app.schemas.seo_run import SeoReportActionItem, SeoReportSection, SeoRunReportResponse
from app.services.project_context import business_context_items, has_business_context, project_business_context


class SeoReportService:
    """Builds deterministic, client-facing SEO reports from persisted run data."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_report(self, run_id: UUID, tenant_id: UUID) -> Optional[SeoRunReportResponse]:
        run = await self._get_run(run_id, tenant_id)
        if not run:
            return None

        project = await self._get_project(run.project_id, tenant_id)
        crawl = await self._get_crawl(getattr(run, "crawl_id", None), tenant_id)
        audit = await self._get_audit(getattr(run, "audit_id", None), tenant_id)
        semantic = await self._get_semantic_run(getattr(run, "semantic_index_run_id", None), tenant_id)
        content_run = await self._get_content_run(getattr(run, "content_optimization_run_id", None), tenant_id)
        planner_run = await self._get_planner_run(getattr(run, "planner_run_id", None), tenant_id)

        top_issues = await self._list_top_audit_issues(getattr(run, "audit_id", None), tenant_id)
        semantic_summaries = await self._list_semantic_summaries(
            getattr(run, "semantic_index_run_id", None),
            tenant_id,
        )
        content_suggestions = await self._list_content_suggestions(
            getattr(run, "content_optimization_run_id", None),
            tenant_id,
        )
        planner_tasks = await self._list_planner_tasks(getattr(run, "planner_run_id", None), tenant_id)
        data_availability = await self._data_availability(getattr(run, "project_id"), tenant_id)
        business_context = project_business_context(project)
        competitor_urls = self._list_values(getattr(project, "competitor_urls", None))

        issue_counts_by_severity = self._count_dict(getattr(audit, "issue_counts_by_severity", None))
        issue_counts_by_category = self._count_dict(getattr(audit, "issue_counts_by_category", None))
        if audit and not issue_counts_by_severity:
            issue_counts_by_severity = await self._count_issues_by(getattr(audit, "id"), tenant_id, SEOIssue.severity)
        if audit and not issue_counts_by_category:
            issue_counts_by_category = await self._count_issues_by(getattr(audit, "id"), tenant_id, SEOIssue.category)

        crawl_pages_processed = int(
            getattr(crawl, "total_pages_crawled", 0)
            or getattr(audit, "total_pages", 0)
            or getattr(semantic, "total_pages", 0)
            or 0
        )
        audit_score = getattr(audit, "site_score", None)
        total_issues = int(getattr(audit, "total_issues", 0) or sum(issue_counts_by_severity.values()) or 0)
        semantic_vector_count = int(getattr(semantic, "indexed_vectors", 0) or getattr(semantic, "total_vectors", 0) or 0)
        content_suggestions_count = int(getattr(content_run, "total_suggestions", 0) or len(content_suggestions))
        planner_tasks_count = int(getattr(planner_run, "tasks_created", 0) or len(planner_tasks))

        project_name = getattr(project, "name", None) or "SEO project"
        website_url = self._website_url(getattr(project, "domain", None) or getattr(crawl, "url", None) or "")
        executive_summary = self._executive_summary(
            project_name=project_name,
            run_status=self._enum_value(getattr(run, "status", "unknown")),
            crawl_pages_processed=crawl_pages_processed,
            audit_score=audit_score,
            total_issues=total_issues,
            semantic_vector_count=semantic_vector_count,
            content_suggestions_count=content_suggestions_count,
            planner_tasks_count=planner_tasks_count,
        )
        next_actions = self._next_actions(top_issues, content_suggestions, planner_tasks, data_availability)
        sections = self._sections(
            executive_summary=executive_summary,
            crawl_pages_processed=crawl_pages_processed,
            audit_score=audit_score,
            total_issues=total_issues,
            issue_counts_by_severity=issue_counts_by_severity,
            issue_counts_by_category=issue_counts_by_category,
            top_issues=top_issues,
            semantic_vector_count=semantic_vector_count,
            semantic_summaries=semantic_summaries,
            content_suggestions_count=content_suggestions_count,
            content_suggestions=content_suggestions,
            planner_tasks_count=planner_tasks_count,
            planner_tasks=planner_tasks,
            data_availability=data_availability,
            business_context=business_context,
            competitor_urls=competitor_urls,
            next_actions=next_actions,
        )

        return SeoRunReportResponse(
            run_id=getattr(run, "id"),
            tenant_id=getattr(run, "tenant_id"),
            project_id=getattr(run, "project_id"),
            project_name=project_name,
            website_url=website_url,
            run_status=self._enum_value(getattr(run, "status", "unknown")),
            completed_at=getattr(run, "completed_at", None),
            generated_at=datetime.utcnow(),
            crawl_pages_processed=crawl_pages_processed,
            audit_score=audit_score,
            total_issues=total_issues,
            issue_counts_by_severity=issue_counts_by_severity,
            issue_counts_by_category=issue_counts_by_category,
            semantic_vector_count=semantic_vector_count,
            content_suggestions_count=content_suggestions_count,
            planner_tasks_count=planner_tasks_count,
            data_availability=data_availability,
            executive_summary=executive_summary,
            sections=sections,
            top_audit_issues=top_issues,
            semantic_summaries=semantic_summaries,
            content_suggestions=content_suggestions,
            weekly_planner_tasks=planner_tasks,
            next_actions=next_actions,
        )

    def render_html(self, report: SeoRunReportResponse) -> str:
        """Render a standalone, print-friendly HTML report."""
        score = str(report.audit_score) if report.audit_score is not None else "N/A"
        completed = self._format_datetime(report.completed_at) if report.completed_at else "Not completed"
        generated = self._format_datetime(report.generated_at)
        sections_html = "\n".join(self._section_html(section) for section in report.sections)

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(report.project_name)} SEO Report</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; background: #f8fafc; color: #0f172a; font-family: Arial, sans-serif; line-height: 1.45; }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 32px 20px; }}
    header {{ border-bottom: 1px solid #e2e8f0; padding-bottom: 18px; margin-bottom: 22px; }}
    h1 {{ font-size: 30px; margin: 0 0 6px; }}
    h2 {{ font-size: 18px; margin: 0 0 10px; }}
    p {{ margin: 0; }}
    .meta {{ color: #475569; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .card, section {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }}
    .label {{ color: #64748b; font-size: 12px; font-weight: 700; text-transform: uppercase; }}
    .value {{ font-size: 26px; font-weight: 700; margin-top: 5px; }}
    section {{ margin-top: 14px; break-inside: avoid; }}
    ul {{ margin: 10px 0 0; padding-left: 18px; }}
    li {{ margin: 7px 0; }}
    .muted {{ color: #64748b; }}
    .badge {{ display: inline-block; border: 1px solid #cbd5e1; border-radius: 999px; padding: 2px 8px; font-size: 12px; color: #334155; }}
    @media (max-width: 760px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media print {{
      body {{ background: #fff; }}
      main {{ max-width: none; padding: 0; }}
      .card, section {{ box-shadow: none; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{escape(report.project_name)} SEO Report</h1>
      <p class="meta">{escape(report.website_url)} | Status: {escape(report.run_status)} | Completed: {escape(completed)} | Generated: {escape(generated)}</p>
    </header>
    <p>{escape(report.executive_summary)}</p>
    <div class="grid">
      {self._metric_html("Audit Score", score)}
      {self._metric_html("Pages Processed", report.crawl_pages_processed)}
      {self._metric_html("Audit Issues", report.total_issues)}
      {self._metric_html("Semantic Vectors", report.semantic_vector_count)}
    </div>
    {sections_html}
  </main>
</body>
</html>"""

    async def _get_run(self, run_id: UUID, tenant_id: UUID) -> Optional[SeoRun]:
        result = await self.db.execute(select(SeoRun).where(SeoRun.id == run_id, SeoRun.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def _get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def _get_crawl(self, crawl_id: Optional[UUID], tenant_id: UUID) -> Optional[CrawlJob]:
        if not crawl_id:
            return None
        result = await self.db.execute(select(CrawlJob).where(CrawlJob.id == crawl_id, CrawlJob.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def _get_audit(self, audit_id: Optional[UUID], tenant_id: UUID) -> Optional[SEOAuditRun]:
        if not audit_id:
            return None
        result = await self.db.execute(select(SEOAuditRun).where(SEOAuditRun.id == audit_id, SEOAuditRun.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def _get_semantic_run(self, run_id: Optional[UUID], tenant_id: UUID) -> Optional[SemanticIndexRun]:
        if not run_id:
            return None
        result = await self.db.execute(select(SemanticIndexRun).where(SemanticIndexRun.id == run_id, SemanticIndexRun.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def _get_content_run(self, run_id: Optional[UUID], tenant_id: UUID) -> Optional[ContentOptimizationRun]:
        if not run_id:
            return None
        result = await self.db.execute(
            select(ContentOptimizationRun).where(
                ContentOptimizationRun.id == run_id,
                ContentOptimizationRun.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_planner_run(self, run_id: Optional[UUID], tenant_id: UUID) -> Optional[SeoPlannerRun]:
        if not run_id:
            return None
        result = await self.db.execute(select(SeoPlannerRun).where(SeoPlannerRun.id == run_id, SeoPlannerRun.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def _list_top_audit_issues(self, audit_id: Optional[UUID], tenant_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
        if not audit_id:
            return []
        result = await self.db.execute(
            select(SEOIssue).where(SEOIssue.audit_run_id == audit_id, SEOIssue.tenant_id == tenant_id).limit(200)
        )
        issues = list(result.scalars().all())
        issues.sort(key=self._issue_sort_key)
        return [self._issue_item(issue) for issue in issues[:limit]]

    async def _list_semantic_summaries(self, run_id: Optional[UUID], tenant_id: UUID, limit: int = 8) -> list[dict[str, Any]]:
        if not run_id:
            return []
        result = await self.db.execute(
            select(SemanticIndexedContent)
            .where(SemanticIndexedContent.index_run_id == run_id, SemanticIndexedContent.tenant_id == tenant_id)
            .order_by(SemanticIndexedContent.indexed_at.desc())
            .limit(50)
        )
        items: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for content in result.scalars().all():
            url = getattr(content, "url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            items.append(
                {
                    "id": str(getattr(content, "id")),
                    "url": url,
                    "content_type": self._enum_value(getattr(content, "content_type", "")),
                    "heading_context": getattr(content, "heading_context", None),
                    "text_preview": getattr(content, "text_preview", None),
                }
            )
            if len(items) >= limit:
                break
        return items

    async def _list_content_suggestions(self, run_id: Optional[UUID], tenant_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
        if not run_id:
            return []
        result = await self.db.execute(
            select(ContentOptimizationSuggestion, CrawlPage.url)
            .outerjoin(CrawlPage, CrawlPage.id == ContentOptimizationSuggestion.page_id)
            .where(
                ContentOptimizationSuggestion.run_id == run_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
            )
            .order_by(
                ContentOptimizationSuggestion.priority_score.desc(),
                ContentOptimizationSuggestion.confidence_score.desc(),
                ContentOptimizationSuggestion.created_at.desc(),
            )
            .limit(limit)
        )
        return [self._content_suggestion_item(suggestion, page_url) for suggestion, page_url in result.all()]

    async def _list_planner_tasks(self, run_id: Optional[UUID], tenant_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
        if not run_id:
            return []
        result = await self.db.execute(
            select(SeoTask)
            .where(SeoTask.planner_run_id == run_id, SeoTask.tenant_id == tenant_id)
            .order_by(SeoTask.priority_score.desc(), SeoTask.updated_at.desc())
            .limit(limit)
        )
        return [self._planner_task_item(task) for task in result.scalars().all()]

    async def _count_issues_by(self, audit_id: UUID, tenant_id: UUID, column: Any) -> dict[str, int]:
        result = await self.db.execute(
            select(column, func.count(SEOIssue.id))
            .where(SEOIssue.audit_run_id == audit_id, SEOIssue.tenant_id == tenant_id)
            .group_by(column)
        )
        return {self._enum_value(key): int(count) for key, count in result.all()}

    async def _data_availability(self, project_id: UUID, tenant_id: UUID) -> dict[str, str]:
        property_result = await self.db.execute(
            select(GSCProperty)
            .where(
                GSCProperty.project_id == project_id,
                GSCProperty.tenant_id == tenant_id,
                GSCProperty.is_selected.is_(True),
            )
            .order_by(GSCProperty.updated_at.desc())
            .limit(1)
        )
        selected_property = property_result.scalar_one_or_none()

        import_result = await self.db.execute(
            select(SearchConsoleImport)
            .where(
                SearchConsoleImport.project_id == project_id,
                SearchConsoleImport.tenant_id == tenant_id,
                SearchConsoleImport.status == SearchConsoleImportStatus.completed,
                SearchConsoleImport.rows_imported > 0,
            )
            .order_by(SearchConsoleImport.created_at.desc())
            .limit(1)
        )
        latest_import = import_result.scalar_one_or_none()

        snapshot_count = await self.db.scalar(
            select(func.count(SerpSnapshot.id)).where(
                SerpSnapshot.project_id == project_id,
                SerpSnapshot.tenant_id == tenant_id,
            )
        )

        return {
            "search_console": "Connected" if selected_property else "Not connected",
            "ranking_data": "Real Search Console data available" if latest_import else "No real ranking data available",
            "serp": "Manual SERP snapshots available" if int(snapshot_count or 0) else "No real ranking data available",
        }

    def _sections(
        self,
        *,
        executive_summary: str,
        crawl_pages_processed: int,
        audit_score: Optional[int],
        total_issues: int,
        issue_counts_by_severity: dict[str, int],
        issue_counts_by_category: dict[str, int],
        top_issues: list[dict[str, Any]],
        semantic_vector_count: int,
        semantic_summaries: list[dict[str, Any]],
        content_suggestions_count: int,
        content_suggestions: list[dict[str, Any]],
        planner_tasks_count: int,
        planner_tasks: list[dict[str, Any]],
        data_availability: dict[str, str],
        business_context: dict[str, Any],
        competitor_urls: list[str],
        next_actions: list[SeoReportActionItem],
    ) -> list[SeoReportSection]:
        business_items = business_context_items(business_context)
        if competitor_urls:
            business_items.append(
                {
                    "label": "Competitor URLs",
                    "value": competitor_urls,
                    "note": "Manual context only; not crawled or analyzed.",
                }
            )
        return [
            SeoReportSection(
                key="executive_summary",
                title="Executive Summary",
                summary=executive_summary,
                metrics={
                    "crawl_pages_processed": crawl_pages_processed,
                    "audit_score": audit_score,
                    "total_issues": total_issues,
                    "semantic_vectors": semantic_vector_count,
                    "content_suggestions": content_suggestions_count,
                    "planner_tasks": planner_tasks_count,
                },
            ),
            SeoReportSection(
                key="business_context",
                title="Business Context",
                summary=(
                    "Project onboarding context is available for this report. "
                    "Competitor URLs, when present, are manual context only and were not crawled or analyzed."
                    if has_business_context(business_context)
                    else "No project onboarding context was provided. Existing projects still run normally."
                ),
                status="available" if has_business_context(business_context) else "no_data",
                metrics={
                    "fields_provided": sum(
                        1
                        for value in business_context.values()
                        if (isinstance(value, list) and value) or (isinstance(value, str) and value != "Not provided")
                    ),
                    "competitor_context": "Manual only" if competitor_urls else "Not provided",
                },
                items=business_items,
            ),
            SeoReportSection(
                key="audit",
                title="Technical SEO Audit",
                summary=(
                    f"Audit score is {audit_score} with {total_issues} total issues."
                    if audit_score is not None
                    else "No audit data is available for this run."
                ),
                status="available" if audit_score is not None else "no_data",
                metrics={
                    "score": audit_score,
                    "total_issues": total_issues,
                    "by_severity": issue_counts_by_severity,
                    "by_category": issue_counts_by_category,
                },
                items=top_issues,
            ),
            SeoReportSection(
                key="semantic_index",
                title="Semantic Index",
                summary=(
                    f"{semantic_vector_count} semantic vectors were indexed."
                    if semantic_vector_count
                    else "No semantic vectors were indexed for this run."
                ),
                status="available" if semantic_vector_count else "no_data",
                metrics={"semantic_vectors": semantic_vector_count},
                items=semantic_summaries,
            ),
            SeoReportSection(
                key="content_optimization",
                title="AI Content Suggestions",
                summary=(
                    f"{content_suggestions_count} content optimization suggestions are available."
                    if content_suggestions_count
                    else "No content optimization suggestions were generated for this run."
                ),
                status="available" if content_suggestions_count else "no_data",
                metrics={"suggestions": content_suggestions_count},
                items=content_suggestions,
            ),
            SeoReportSection(
                key="weekly_planner",
                title="Weekly Action Plan",
                summary=(
                    f"{planner_tasks_count} planner tasks were created."
                    if planner_tasks_count
                    else "No weekly planner tasks were created for this run."
                ),
                status="available" if planner_tasks_count else "no_data",
                metrics={"tasks": planner_tasks_count},
                items=planner_tasks,
            ),
            SeoReportSection(
                key="real_search_data",
                title="Real Ranking Data",
                summary=(
                    f"Search Console: {data_availability.get('search_console', 'Not connected')}. "
                    f"Ranking data: {data_availability.get('ranking_data', 'No real ranking data available')}. "
                    f"SERP: {data_availability.get('serp', 'No real ranking data available')}."
                ),
                status="available"
                if data_availability.get("ranking_data") == "Real Search Console data available"
                or data_availability.get("serp") == "Manual SERP snapshots available"
                else "not_connected",
                metrics=data_availability,
                items=[],
            ),
            SeoReportSection(
                key="next_actions",
                title="Next Actions",
                summary=f"{len(next_actions)} prioritized next actions are ready.",
                status="available",
                metrics={"actions": len(next_actions)},
                items=[action.model_dump(mode="json") for action in next_actions],
            ),
        ]

    def _next_actions(
        self,
        top_issues: list[dict[str, Any]],
        content_suggestions: list[dict[str, Any]],
        planner_tasks: list[dict[str, Any]],
        data_availability: dict[str, str],
    ) -> list[SeoReportActionItem]:
        actions: list[SeoReportActionItem] = []

        for task in planner_tasks[:4]:
            actions.append(
                SeoReportActionItem(
                    title=task.get("title", "Review planner task"),
                    description=task.get("description", "Review and prioritize this planner task."),
                    priority=task.get("priority", "medium"),
                    source_section="weekly_planner",
                    target_url=task.get("target_page_url"),
                    status=task.get("status"),
                    due_date=task.get("due_date"),
                )
            )

        for issue in top_issues:
            if len(actions) >= 7:
                break
            actions.append(
                SeoReportActionItem(
                    title=f"Fix {issue.get('title', 'audit issue')}",
                    description=issue.get("recommendation") or issue.get("message") or "Review this audit issue.",
                    priority=self._issue_priority(issue.get("severity")),
                    source_section="audit",
                    target_url=issue.get("url"),
                    status=issue.get("status"),
                )
            )

        for suggestion in content_suggestions:
            if len(actions) >= 9:
                break
            actions.append(
                SeoReportActionItem(
                    title=f"Review {self._label(suggestion.get('suggestion_type', 'content suggestion'))}",
                    description=suggestion.get("reason") or suggestion.get("suggested_value") or "Review this content suggestion.",
                    priority=self._score_priority(suggestion.get("priority_score")),
                    source_section="content_optimization",
                    target_url=suggestion.get("page_url"),
                    status=suggestion.get("status"),
                )
            )

        if data_availability.get("search_console") == "Not connected":
            actions.append(
                SeoReportActionItem(
                    title="Connect Search Console",
                    description="Connect Google Search Console or upload a real export before reporting ranking changes.",
                    priority="medium",
                    source_section="real_search_data",
                )
            )
        if data_availability.get("serp") == "No real ranking data available":
            actions.append(
                SeoReportActionItem(
                    title="Add manual SERP evidence",
                    description="Capture manual SERP snapshots for priority keywords before discussing ranking movement.",
                    priority="low",
                    source_section="real_search_data",
                )
            )

        if not actions:
            actions.append(
                SeoReportActionItem(
                    title="Review completed report",
                    description="Review the run summary and decide which SEO workflow should run next.",
                    priority="low",
                    source_section="executive_summary",
                )
            )
        return actions[:10]

    def _executive_summary(
        self,
        *,
        project_name: str,
        run_status: str,
        crawl_pages_processed: int,
        audit_score: Optional[int],
        total_issues: int,
        semantic_vector_count: int,
        content_suggestions_count: int,
        planner_tasks_count: int,
    ) -> str:
        score_text = f"an audit score of {audit_score}" if audit_score is not None else "no audit score"
        return (
            f"{project_name} SEO run is {run_status}. The run processed {crawl_pages_processed} pages, "
            f"recorded {score_text}, found {total_issues} audit issues, indexed {semantic_vector_count} "
            f"semantic vectors, generated {content_suggestions_count} content suggestions, and created "
            f"{planner_tasks_count} planner tasks."
        )

    def _issue_item(self, issue: SEOIssue) -> dict[str, Any]:
        return {
            "id": str(getattr(issue, "id")),
            "title": getattr(issue, "title", ""),
            "message": getattr(issue, "message", ""),
            "recommendation": getattr(issue, "recommendation", None),
            "severity": self._enum_value(getattr(issue, "severity", "")),
            "category": self._enum_value(getattr(issue, "category", "")),
            "status": self._enum_value(getattr(issue, "status", "")),
            "url": getattr(issue, "url", None),
            "score_impact": int(getattr(issue, "score_impact", 0) or 0),
        }

    def _content_suggestion_item(self, suggestion: ContentOptimizationSuggestion, page_url: Optional[str]) -> dict[str, Any]:
        return {
            "id": str(getattr(suggestion, "id")),
            "suggestion_type": self._enum_value(getattr(suggestion, "suggestion_type", "")),
            "suggested_value": getattr(suggestion, "suggested_value", ""),
            "reason": getattr(suggestion, "reason", ""),
            "priority_score": float(getattr(suggestion, "priority_score", 0) or 0),
            "confidence_score": float(getattr(suggestion, "confidence_score", 0) or 0),
            "status": self._enum_value(getattr(suggestion, "status", "")),
            "page_url": page_url,
        }

    def _planner_task_item(self, task: SeoTask) -> dict[str, Any]:
        return {
            "id": str(getattr(task, "id")),
            "title": getattr(task, "title", ""),
            "description": getattr(task, "description", ""),
            "task_type": self._enum_value(getattr(task, "task_type", "")),
            "source_type": self._enum_value(getattr(task, "source_type", "")),
            "target_page_url": getattr(task, "target_page_url", None),
            "target_keyword": getattr(task, "target_keyword", None),
            "priority": self._enum_value(getattr(task, "priority", "medium")),
            "priority_score": float(getattr(task, "priority_score", 0) or 0),
            "estimated_impact": self._enum_value(getattr(task, "estimated_impact", "")),
            "effort": self._enum_value(getattr(task, "effort", "")),
            "status": self._enum_value(getattr(task, "status", "")),
            "due_date": getattr(task, "due_date", None),
        }

    def _issue_sort_key(self, issue: SEOIssue) -> tuple[int, int, float, str]:
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        created_at = getattr(issue, "created_at", None)
        created_sort = -created_at.timestamp() if isinstance(created_at, datetime) else 0.0
        return (
            severity_rank.get(self._enum_value(getattr(issue, "severity", "")).lower(), 99),
            -int(getattr(issue, "score_impact", 0) or 0),
            created_sort,
            str(getattr(issue, "id", "")),
        )

    def _section_html(self, section: SeoReportSection) -> str:
        items = "\n".join(f"<li>{escape(self._item_text(item))}</li>" for item in section.items[:10])
        item_html = f"<ul>{items}</ul>" if items else '<p class="muted">No items available.</p>'
        return f"""<section>
  <h2>{escape(section.title)} <span class="badge">{escape(section.status)}</span></h2>
  <p>{escape(section.summary)}</p>
  {item_html}
</section>"""

    def _metric_html(self, label: str, value: Any) -> str:
        return f"""<div class="card">
  <div class="label">{escape(label)}</div>
  <div class="value">{escape(str(value))}</div>
</div>"""

    def _item_text(self, item: dict[str, Any]) -> str:
        for fields in (
            ("title", "severity", "url"),
            ("title", "priority", "target_page_url"),
            ("suggestion_type", "reason", "page_url"),
            ("url", "text_preview"),
        ):
            values = [str(item.get(field)) for field in fields if item.get(field)]
            if values:
                return " | ".join(values)
        return ", ".join(f"{key}: {value}" for key, value in item.items() if value is not None)

    def _count_dict(self, value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        return {str(key): int(count or 0) for key, count in value.items()}

    def _list_values(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_values = value.replace("\n", ",").split(",")
        elif isinstance(value, (list, tuple, set)):
            raw_values = list(value)
        else:
            raw_values = [value]
        return [str(item).strip() for item in raw_values if str(item or "").strip()]

    def _website_url(self, value: str) -> str:
        domain = (value or "").strip()
        if not domain:
            return "Not connected"
        if domain.startswith(("http://", "https://")):
            return domain
        if domain.startswith(("localhost", "127.")) or ":" in domain:
            return f"http://{domain}"
        return f"https://{domain}"

    def _format_datetime(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M UTC")

    def _issue_priority(self, severity: Any) -> str:
        severity_value = str(severity or "").lower()
        if severity_value == "critical":
            return "critical"
        if severity_value == "high":
            return "high"
        if severity_value == "medium":
            return "medium"
        return "low"

    def _score_priority(self, score: Any) -> str:
        value = float(score or 0)
        if value >= 85:
            return "critical"
        if value >= 70:
            return "high"
        if value >= 40:
            return "medium"
        return "low"

    def _label(self, value: Any) -> str:
        return str(value or "").replace("_", " ")

    def _enum_value(self, value: Any) -> str:
        return str(getattr(value, "value", value))

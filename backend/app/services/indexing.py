"""GSC URL Inspection indexing intelligence and fix validation service."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.core.encryption import decrypt_secret
from app.models.crawl import CrawlPage
from app.models.indexing import (
    GSCFixValidationRunStatus,
    GSCIndexingIssue,
    GSCIndexingIssueSeverity,
    GSCIndexingIssueStatus,
    GSCIndexingIssueType,
    GSCUrlInspectionRun,
    GSCUrlInspectionRunStatus,
)
from app.models.planner import (
    SeoTaskEffort,
    SeoTaskImpact,
    SeoTaskPriority,
    SeoTaskSourceType,
    SeoTaskStatus,
    SeoTaskType,
)
from app.models.repo_agent import (
    SeoCodeIssueSeverity,
    SeoCodeIssueSource,
    SeoCodeIssueStatus,
    SeoCodeIssueType,
)
from app.models.search_console import GSCConnectionStatus, GSCSyncType
from app.repositories.indexing import IndexingRepository
from app.services.search_console import (
    GoogleSearchConsoleClient,
    SearchConsoleGoogleAPIError,
    SearchConsoleService,
    normalize_url,
)

logger = structlog.get_logger(__name__)


class IndexingServiceError(RuntimeError):
    """Base indexing service error."""


@dataclass
class IndexingIssueDiagnosis:
    issue_type: GSCIndexingIssueType
    severity: GSCIndexingIssueSeverity
    likely_cause: str
    recommended_fix: str


@dataclass
class UrlCandidate:
    url: str
    priority: int
    reason: str


class GSCIndexingIssueClassifier:
    """Deterministic indexing diagnosis rules using API and local audit signals."""

    def classify(self, result: Any, context: Optional[dict] = None) -> Optional[IndexingIssueDiagnosis]:
        context = context or {}
        if self.is_indexed(result):
            return None

        coverage = self._text(self._get(result, "coverage_state"))
        indexing_state = self._enum_text(self._get(result, "indexing_state"))
        robots_state = self._enum_text(self._get(result, "robots_txt_state"))
        fetch_state = self._enum_text(self._get(result, "page_fetch_state"))
        rich_verdict = self._enum_text(self._get(result, "rich_results_verdict"))
        page = context.get("crawl_page")
        audit_types = " ".join(str(item).lower() for item in context.get("audit_issue_types", []))

        if robots_state in {"DISALLOWED", "BLOCKED"} or ("robots" in coverage and "blocked" in coverage) or "ROBOTS" in fetch_state:
            return self._diagnosis(
                GSCIndexingIssueType.blocked_by_robots,
                GSCIndexingIssueSeverity.critical,
                "Google reports that robots.txt blocks crawling for this URL.",
                "Review robots.txt and allow Googlebot for the affected route only after confirming the page should be indexable.",
            )

        if indexing_state in {"BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER"} or bool(getattr(page, "noindex", False)) or "noindex" in audit_types:
            return self._diagnosis(
                GSCIndexingIssueType.noindex_detected,
                GSCIndexingIssueSeverity.critical,
                "A noindex directive is present in the URL Inspection result or latest crawl/audit data.",
                "Remove the noindex meta tag or X-Robots-Tag for this URL if it is intended to rank.",
            )

        if "SERVER_ERROR" in fetch_state or "server error" in coverage or "5xx" in coverage or "500" in coverage:
            return self._diagnosis(
                GSCIndexingIssueType.server_error,
                GSCIndexingIssueSeverity.critical,
                "Google could not fetch the page because the server returned an error.",
                "Fix server rendering, routing, or upstream availability, then validate after the deployed fix has been live.",
            )

        if "REDIRECT_ERROR" in fetch_state or "redirect error" in coverage:
            return self._diagnosis(
                GSCIndexingIssueType.redirect_error,
                GSCIndexingIssueSeverity.high,
                "Google encountered a redirect error when trying to inspect or crawl the URL.",
                "Review redirect chains and ensure the final canonical URL returns a stable 200 response.",
            )

        if "SOFT_404" in fetch_state or "soft 404" in coverage:
            return self._diagnosis(
                GSCIndexingIssueType.soft_404,
                GSCIndexingIssueSeverity.high,
                "Google considers this URL a soft 404 or low-value placeholder.",
                "Strengthen the page content and response intent, or redirect/remove it if it should not be indexed.",
            )

        if self._canonical_differs(result):
            issue_type = GSCIndexingIssueType.duplicate_canonical if "duplicate" in coverage else GSCIndexingIssueType.canonical_mismatch
            return self._diagnosis(
                issue_type,
                GSCIndexingIssueSeverity.high,
                "Google selected a different canonical URL than the user-declared canonical.",
                "Align canonical tags, internal links, sitemap entries, and redirects around the preferred indexable URL.",
            )

        if self._page_redirects(page) and (context.get("url_in_sitemap") or context.get("internal_links_use_old_url")):
            return self._diagnosis(
                GSCIndexingIssueType.page_with_redirect,
                GSCIndexingIssueSeverity.medium,
                "The inspected URL redirects while sitemap or internal-link signals still reference the old URL.",
                "Update sitemap and internal links to point directly at the final canonical URL.",
            )

        sitemap_urls = self._get(result, "sitemap_urls") or []
        if context.get("important_route") and not context.get("url_in_sitemap") and not sitemap_urls:
            return self._diagnosis(
                GSCIndexingIssueType.sitemap_missing,
                GSCIndexingIssueSeverity.medium,
                "This important route is missing from both local sitemap data and the URL Inspection sitemap list.",
                "Add the canonical URL to the sitemap through the existing sitemap generation path.",
            )

        if self._thin_content(page, audit_types) and (context.get("url_in_sitemap") or context.get("important_route")):
            return self._diagnosis(
                GSCIndexingIssueType.thin_content,
                GSCIndexingIssueSeverity.medium,
                "The latest crawl/audit signals suggest the page has thin content for an indexable sitemap URL.",
                "Expand useful page sections, FAQs, proof points, and entity coverage before requesting validation.",
            )

        inbound_links = int(context.get("inbound_internal_links") or 0)
        if context.get("important_route") and inbound_links <= 0:
            return self._diagnosis(
                GSCIndexingIssueType.orphan_page,
                GSCIndexingIssueSeverity.medium,
                "The page has weak or missing inbound internal links in the latest crawl graph.",
                "Add relevant internal links from crawlable supporting pages using descriptive anchor text.",
            )

        if rich_verdict == "FAIL" or "structured" in audit_types or "schema" in audit_types:
            return self._diagnosis(
                GSCIndexingIssueType.structured_data_issue,
                GSCIndexingIssueSeverity.low,
                "Structured data or rich result validation appears to need review.",
                "Review JSON-LD/schema output for the route and keep any patch review-only.",
            )

        if "crawled" in coverage and "not indexed" in coverage:
            return self._diagnosis(
                GSCIndexingIssueType.crawled_not_indexed,
                GSCIndexingIssueSeverity.medium,
                "Google crawled the URL but has not selected it for indexing.",
                "Improve content depth, uniqueness, canonical consistency, and internal-link support.",
            )

        if "discovered" in coverage and "not indexed" in coverage:
            return self._diagnosis(
                GSCIndexingIssueType.discovered_not_indexed,
                GSCIndexingIssueSeverity.medium,
                "Google discovered the URL but has not crawled or indexed it yet.",
                "Confirm sitemap inclusion, crawlability, server stability, and internal-link paths.",
            )

        if "not indexed" in coverage or self._enum_text(self._get(result, "verdict")) in {"FAIL", "NEUTRAL"}:
            return self._diagnosis(
                GSCIndexingIssueType.not_indexed,
                GSCIndexingIssueSeverity.medium,
                "The URL Inspection verdict indicates the page is not currently indexed.",
                "Review crawlability, canonical, sitemap, content quality, and internal-link support before validating.",
            )

        return self._diagnosis(
            GSCIndexingIssueType.unknown,
            GSCIndexingIssueSeverity.low,
            "The URL Inspection response did not match a more specific indexing rule.",
            "Manually review the raw inspection result and local crawl/audit context.",
        )

    def is_indexed(self, result: Any) -> bool:
        verdict = self._enum_text(self._get(result, "verdict"))
        coverage = self._text(self._get(result, "coverage_state"))
        if verdict == "PASS":
            return True
        return "indexed" in coverage and "not indexed" not in coverage and "excluded" not in coverage

    def _diagnosis(
        self,
        issue_type: GSCIndexingIssueType,
        severity: GSCIndexingIssueSeverity,
        likely_cause: str,
        recommended_fix: str,
    ) -> IndexingIssueDiagnosis:
        return IndexingIssueDiagnosis(issue_type, severity, likely_cause, recommended_fix)

    def _canonical_differs(self, result: Any) -> bool:
        google = normalize_url(str(self._get(result, "google_canonical") or ""))
        user = normalize_url(str(self._get(result, "user_canonical") or ""))
        return bool(google and user and google != user)

    def _page_redirects(self, page: Optional[CrawlPage]) -> bool:
        if not page:
            return False
        status = int(getattr(page, "status_code", 0) or 0)
        return status in range(300, 400) or int(getattr(page, "redirect_count", 0) or 0) > 0

    def _thin_content(self, page: Optional[CrawlPage], audit_types: str) -> bool:
        if page and int(getattr(page, "word_count", 0) or 0) and int(getattr(page, "word_count", 0) or 0) < 300:
            return True
        return "thin" in audit_types or "low_content" in audit_types

    def _get(self, result: Any, key: str) -> Any:
        if isinstance(result, dict):
            return result.get(key)
        return getattr(result, key, None)

    def _text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _enum_text(self, value: Any) -> str:
        return str(getattr(value, "value", value) or "").strip().upper()


class IndexingService:
    """URL Inspection orchestration, diagnosis, fix planning, and validation."""

    search_console_service_class = SearchConsoleService

    def __init__(
        self,
        db: AsyncSession,
        google_client: Optional[GoogleSearchConsoleClient] = None,
        classifier: Optional[GSCIndexingIssueClassifier] = None,
        request_delay_seconds: Optional[float] = None,
    ):
        self.db = db
        self.repository = IndexingRepository(db)
        self.google_client = google_client or GoogleSearchConsoleClient()
        self.classifier = classifier or GSCIndexingIssueClassifier()
        self.request_delay_seconds = (
            settings.GSC_URL_INSPECTION_REQUEST_DELAY_SECONDS
            if request_delay_seconds is None
            else request_delay_seconds
        )

    async def inspect_project(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        urls: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
        language_code: Optional[str] = None,
    ) -> GSCUrlInspectionRun:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        prop = await self.repository.selected_property(project_id, tenant_id)
        if not prop:
            raise ValueError("No selected Search Console property for this project")
        if not prop.connection_id:
            raise ValueError("OAuth connection required for URL Inspection API. Manual GSC properties only support CSV/performance fallback.")
        connection = await self.repository.get_connection(prop.connection_id, tenant_id)
        if not connection:
            raise ValueError("Search Console OAuth connection not found")

        selected_urls = await self.select_urls_for_inspection(
            tenant_id=tenant_id,
            project_id=project_id,
            requested_urls=urls,
            limit=limit,
        )
        run = await self.repository.create_inspection_run(
            tenant_id=tenant_id,
            project_id=project_id,
            gsc_property_id=prop.id,
            requested_url_count=len(selected_urls),
        )
        await self.repository.set_inspection_run_status(run, GSCUrlInspectionRunStatus.running)
        await self.db.commit()
        if not selected_urls:
            run = await self.repository.set_inspection_run_status(run, GSCUrlInspectionRunStatus.completed)
            await self.db.commit()
            await self.db.refresh(run)
            return run

        access_token = await self._access_token(connection)
        inspected = 0
        failed = 0
        error_messages: list[str] = []
        for index, candidate in enumerate(selected_urls):
            try:
                raw = await self.google_client.inspect_url(
                    access_token=access_token,
                    site_url=self._site_url_for_api(prop),
                    inspection_url=candidate.url,
                    language_code=language_code or settings.GSC_URL_INSPECTION_LANGUAGE_CODE,
                )
                values = normalize_url_inspection_result(
                    raw,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    inspection_run_id=run.id,
                    page_url=candidate.url,
                )
                result = await self.repository.add_inspection_result(values)
                context = await self._diagnosis_context(project, tenant_id, result.page_url, result)
                await self._classify_and_store(result, context)
                inspected += 1
            except Exception as exc:
                failed += 1
                error_messages.append(f"{candidate.url}: {exc}")
                logger.warning("URL Inspection failed", url=candidate.url, error=str(exc))
            if self.request_delay_seconds > 0 and index < len(selected_urls) - 1:
                await asyncio.sleep(self.request_delay_seconds)

        await self.repository.update_inspection_counts(run, inspected_url_count=inspected, failed_url_count=failed)
        if inspected == 0 and failed > 0:
            status = GSCUrlInspectionRunStatus.failed
        elif failed > 0:
            status = GSCUrlInspectionRunStatus.partial
        else:
            status = GSCUrlInspectionRunStatus.completed
        run = await self.repository.set_inspection_run_status(
            run,
            status,
            error_message="; ".join(error_messages[:3]) if error_messages else None,
        )
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def select_urls_for_inspection(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        requested_urls: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
    ) -> List[UrlCandidate]:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        max_urls = max(1, min(limit or settings.GSC_URL_INSPECTION_MAX_URLS_PER_RUN, settings.GSC_URL_INSPECTION_MAX_URLS_PER_RUN))
        candidates: list[UrlCandidate] = []
        if requested_urls:
            for url in requested_urls:
                normalized = self._absolute_project_url(project, url)
                if normalized:
                    candidates.append(UrlCandidate(normalized, 100, "explicit request"))
            return self._dedupe_candidates(candidates)[:max_urls]

        project_root = self._project_root_url(project)
        if project_root:
            candidates.append(UrlCandidate(project_root, 95, "homepage"))

        for url in await self._recently_changed_urls(project, tenant_id):
            candidates.append(UrlCandidate(url, 100, "recently changed URL"))

        gsc_metrics = await self.repository.gsc_page_metrics(project_id, tenant_id)
        gsc_seen = {normalize_url(item["page_url"]) for item in gsc_metrics}
        for item in gsc_metrics[:25]:
            if item["impressions"] >= settings.GSC_HIGH_IMPRESSIONS_THRESHOLD:
                candidates.append(UrlCandidate(item["page_url"], 90, "key landing page from GSC impressions"))

        for url in await self.repository.gsc_opportunity_urls(project_id, tenant_id):
            candidates.append(UrlCandidate(url, 82, "GSC opportunity page"))

        for url in await self.repository.planner_task_urls(project_id, tenant_id):
            candidates.append(UrlCandidate(url, 80, "planner task page"))

        for url in await self.repository.pages_with_internal_link_support(project_id, tenant_id):
            candidates.append(UrlCandidate(url, 75, "orphan or weak internal-link page"))

        crawl_pages = await self.repository.latest_crawl_pages(project_id, tenant_id)
        for page in crawl_pages:
            url = normalize_url(getattr(page, "final_url", None) or getattr(page, "url", None) or "")
            if not url:
                continue
            if int(getattr(page, "depth", 9) or 9) <= 1:
                candidates.append(UrlCandidate(url, 88, "key crawl landing page"))
            if url not in gsc_seen:
                candidates.append(UrlCandidate(url, 65, "crawled page with no GSC impressions"))
            if int(getattr(page, "internal_links", 0) or 0) <= 2:
                candidates.append(UrlCandidate(url, 78, "weak internal-link page"))

        sitemap_urls = await self.repository.sitemap_entries_for_project(project)
        for url in sitemap_urls:
            normalized = normalize_url(url)
            if normalized and normalized not in gsc_seen:
                candidates.append(UrlCandidate(normalized, 60, "sitemap URL not seen in GSC"))

        for url in await self.repository.previous_issue_urls(project_id, tenant_id):
            candidates.append(UrlCandidate(url, 55, "previous indexing issue"))

        return self._dedupe_candidates(candidates)[:max_urls]

    async def list_runs(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0):
        return await self.repository.list_inspection_runs(project_id, tenant_id, limit=limit, offset=offset)

    async def get_run_details(self, run_id: UUID, tenant_id: UUID) -> dict:
        run = await self.repository.get_inspection_run(run_id, tenant_id)
        if not run:
            raise ValueError("URL inspection run not found")
        results = await self.repository.list_run_results(run_id, tenant_id)
        issues = []
        for result in results:
            issues.extend(await self.repository.open_issues_for_url(run.project_id, tenant_id, result.page_url))
        return {"run": run, "results": results, "issues": issues}

    async def list_issues(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        status: Optional[GSCIndexingIssueStatus] = None,
        issue_type: Optional[GSCIndexingIssueType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GSCIndexingIssue]:
        return await self.repository.list_issues(project_id, tenant_id, status=status, issue_type=issue_type, limit=limit, offset=offset)

    async def get_issue(self, issue_id: UUID, tenant_id: UUID) -> Optional[GSCIndexingIssue]:
        return await self.repository.get_issue(issue_id, tenant_id)

    async def ignore_issue(self, issue_id: UUID, tenant_id: UUID) -> GSCIndexingIssue:
        issue = await self.repository.get_issue(issue_id, tenant_id)
        if not issue:
            raise ValueError("Indexing issue not found")
        issue = await self.repository.set_issue_status(issue, GSCIndexingIssueStatus.ignored)
        await self.db.commit()
        await self.db.refresh(issue)
        return issue

    async def create_fix_plan(self, issue_id: UUID, tenant_id: UUID) -> dict:
        issue = await self.repository.get_issue(issue_id, tenant_id)
        if not issue:
            raise ValueError("Indexing issue not found")
        project = await self.repository.get_project(issue.project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")

        planner_run = await self.repository.create_planner_run_for_fix(issue.project_id, tenant_id)
        task_values = self._fix_task_values(planner_run, issue, project)
        task, created = await self.repository.upsert_fix_task(task_values)
        planner_run.tasks_created = 1 if created else 0
        planner_run.high_priority_tasks = 1 if self._enum_value(task.priority) in {"high", "critical"} else 0

        repo_issue = None
        patch = None
        repo_issue_values = await self._repo_issue_values(issue, tenant_id)
        if repo_issue_values:
            repo_issue = await self.repository.add_repo_issue(repo_issue_values)
            try:
                from app.services.repo_agent import RepoAgentService

                repo_agent = RepoAgentService(self.db)
                await repo_agent.generate_patches(repo_issue.scan_run_id, tenant_id)
                patch = await self.repository.latest_patch_for_repo_issue(repo_issue.id, tenant_id)
            except Exception as exc:
                logger.info("Indexing fix plan created repo issue without patch", issue_id=str(issue.id), error=str(exc))

        issue = await self.repository.update_issue_links(
            issue,
            linked_repo_issue_id=getattr(repo_issue, "id", None),
            linked_patch_id=getattr(patch, "id", None),
            status=GSCIndexingIssueStatus.fix_proposed,
        )
        await self.db.commit()
        await self.db.refresh(issue)
        await self.db.refresh(task)
        return {
            "issue": issue,
            "planner_task": task,
            "repo_issue": repo_issue,
            "patch": patch,
            "safety": "Review-only fix plan. No code was applied, committed, merged, deployed, or published.",
        }

    async def validate_issue(
        self,
        issue_id: UUID,
        tenant_id: UUID,
        *,
        validation_after_days: int = 7,
        run_now: bool = True,
    ) -> dict:
        issue = await self.repository.get_issue(issue_id, tenant_id)
        if not issue:
            raise ValueError("Indexing issue not found")
        run = await self.repository.create_validation_run(
            tenant_id=tenant_id,
            project_id=issue.project_id,
            issue_id=issue.id,
            patch_id=issue.linked_patch_id,
            validation_after_days=validation_after_days,
        )
        if not run_now:
            await self.db.commit()
            await self.db.refresh(run)
            return {"validation_run": run, "result": None}

        project = await self.repository.get_project(issue.project_id, tenant_id)
        prop = await self.repository.selected_property(issue.project_id, tenant_id)
        if not project or not prop or not prop.connection_id:
            await self.repository.set_validation_run_status(run, GSCFixValidationRunStatus.failed)
            await self.db.commit()
            raise ValueError("OAuth Search Console property required for validation")
        connection = await self.repository.get_connection(prop.connection_id, tenant_id)
        if not connection:
            await self.repository.set_validation_run_status(run, GSCFixValidationRunStatus.failed)
            await self.db.commit()
            raise ValueError("Search Console OAuth connection not found")

        await self.repository.set_validation_run_status(run, GSCFixValidationRunStatus.running)
        access_token = await self._access_token(connection)
        try:
            raw = await self.google_client.inspect_url(
                access_token=access_token,
                site_url=self._site_url_for_api(prop),
                inspection_url=issue.page_url,
                language_code=settings.GSC_URL_INSPECTION_LANGUAGE_CODE,
            )
            normalized = normalize_url_inspection_result(
                raw,
                tenant_id=tenant_id,
                project_id=issue.project_id,
                inspection_run_id=UUID(int=0),
                page_url=issue.page_url,
            )
            context = await self._diagnosis_context(project, tenant_id, issue.page_url, normalized)
            diagnosis = self.classifier.classify(normalized, context)
            fixed = diagnosis is None
            still_failing = bool(diagnosis and diagnosis.issue_type == issue.issue_type)
            if fixed:
                status = GSCIndexingIssueStatus.validated
                notes = "URL Inspection now reports the URL as indexed or no matching indexing issue remains."
            elif still_failing:
                status = GSCIndexingIssueStatus.still_failing
                notes = f"Validation still detects {issue.issue_type.value}."
            else:
                status = GSCIndexingIssueStatus.inconclusive
                notes = (
                    f"Previous issue was {issue.issue_type.value}, but current diagnosis is "
                    f"{diagnosis.issue_type.value if diagnosis else 'none'}."
                )
            validation_result = await self.repository.add_validation_result(
                {
                    "tenant_id": tenant_id,
                    "project_id": issue.project_id,
                    "validation_run_id": run.id,
                    "issue_id": issue.id,
                    "page_url": issue.page_url,
                    "previous_issue_type": issue.issue_type,
                    "current_verdict": normalized.get("verdict"),
                    "current_coverage_state": normalized.get("coverage_state"),
                    "fixed": fixed,
                    "still_failing": still_failing,
                    "notes": notes,
                    "raw_result": raw,
                }
            )
            await self.repository.set_issue_status(issue, status)
            await self.repository.set_validation_run_status(run, GSCFixValidationRunStatus.completed)
            await self.db.commit()
            await self.db.refresh(run)
            await self.db.refresh(validation_result)
            await self.db.refresh(issue)
            return {"validation_run": run, "result": validation_result, "issue": issue}
        except Exception:
            await self.repository.set_validation_run_status(run, GSCFixValidationRunStatus.failed)
            await self.db.commit()
            raise

    async def summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        summary = await self.repository.indexing_summary(project_id, tenant_id)
        prop = await self.repository.selected_property(project_id, tenant_id)
        summary["url_inspection_connected"] = bool(getattr(prop, "connection_id", None))
        summary["next_validation_date"] = datetime.utcnow() + timedelta(days=7)
        return summary

    async def run_weekly_monitor(self, project_id: UUID, tenant_id: UUID, *, limit: Optional[int] = None) -> dict:
        sync_summary: dict[str, Any] = {}
        try:
            sync_job = await self.search_console_service_class(self.db).sync_project(
                tenant_id=tenant_id,
                project_id=project_id,
                sync_type=GSCSyncType.scheduled,
            )
            sync_summary = {
                "status": self._enum_value(sync_job.status),
                "rows_fetched": int(getattr(sync_job, "rows_fetched", 0) or 0),
                "opportunities_created": int(getattr(sync_job, "opportunities_created", 0) or 0),
                "opportunities_updated": int(getattr(sync_job, "opportunities_updated", 0) or 0),
            }
        except Exception as exc:
            sync_summary = {"status": "skipped_or_failed", "error": str(exc)}

        run = await self.inspect_project(
            tenant_id=tenant_id,
            project_id=project_id,
            limit=limit or settings.GSC_URL_INSPECTION_MAX_URLS_PER_RUN,
        )
        summary = await self.summary(project_id, tenant_id)
        return {
            "gsc_sync": sync_summary,
            "inspection_run_id": run.id,
            "inspection_status": run.status,
            "inspected_url_count": run.inspected_url_count,
            "failed_url_count": run.failed_url_count,
            "issues_count": summary["issues_count"],
            "issues_by_type": summary["issues_by_type"],
            "weekly_indexing_report": {
                "indexed_urls": summary["indexed_urls"],
                "not_indexed_urls": summary["not_indexed_urls"],
                "top_issues": [
                    {
                        "id": str(issue.id),
                        "page_url": issue.page_url,
                        "issue_type": self._enum_value(issue.issue_type),
                        "recommended_fix": issue.recommended_fix,
                    }
                    for issue in summary["top_issues"][:5]
                ],
            },
        }

    async def _classify_and_store(self, result: Any, context: dict) -> Optional[GSCIndexingIssue]:
        diagnosis = self.classifier.classify(result, context)
        if not diagnosis:
            for issue in await self.repository.open_issues_for_url(result.project_id, result.tenant_id, result.page_url):
                await self.repository.set_issue_status(issue, GSCIndexingIssueStatus.validated)
            return None
        return await self.repository.upsert_issue(
            {
                "tenant_id": result.tenant_id,
                "project_id": result.project_id,
                "inspection_result_id": result.id,
                "page_url": result.page_url,
                "issue_type": diagnosis.issue_type,
                "severity": diagnosis.severity,
                "likely_cause": diagnosis.likely_cause,
                "recommended_fix": diagnosis.recommended_fix,
                "status": GSCIndexingIssueStatus.open,
            }
        )

    async def _diagnosis_context(self, project: Any, tenant_id: UUID, page_url: str, result: Any) -> dict:
        normalized = normalize_url(page_url)
        crawl_page = await self.repository.crawl_page_for_url(project.id, tenant_id, normalized)
        audit_issues = await self.repository.open_audit_issues_for_url(
            project.id,
            tenant_id,
            normalized,
            crawl_page_id=getattr(crawl_page, "id", None),
        )
        sitemap_urls = {normalize_url(url) for url in await self.repository.sitemap_entries_for_project(project)}
        inbound = await self.repository.inbound_internal_link_count(project.id, tenant_id, normalized)
        local_sitemap_hit = normalized in sitemap_urls
        inspection_sitemaps = self._get_value(result, "sitemap_urls") or []
        important_route = self._important_route(project, normalized, crawl_page)
        return {
            "crawl_page": crawl_page,
            "audit_issue_types": [getattr(issue, "issue_type", "") for issue in audit_issues],
            "inbound_internal_links": inbound,
            "url_in_sitemap": local_sitemap_hit or bool(inspection_sitemaps),
            "important_route": important_route,
            "internal_links_use_old_url": bool(crawl_page and int(getattr(crawl_page, "redirect_count", 0) or 0) > 0),
        }

    async def _access_token(self, connection) -> str:
        refresh_token = decrypt_secret(connection.encrypted_refresh_token)
        tokens = await self.google_client.refresh_access_token(refresh_token)
        if tokens.get("expires_in"):
            connection.access_token_expires_at = datetime.utcnow() + timedelta(seconds=int(tokens["expires_in"]))
        connection.status = GSCConnectionStatus.connected
        await self.db.flush()
        return str(tokens["access_token"])

    def _site_url_for_api(self, prop) -> str:
        site_url = str(prop.site_url)
        if site_url.startswith("sc-domain:"):
            return site_url
        parsed = urlsplit(site_url)
        if parsed.scheme and parsed.netloc and not site_url.endswith("/") and not parsed.query:
            return f"{site_url}/"
        return site_url

    async def _recently_changed_urls(self, project: Any, tenant_id: UUID) -> List[str]:
        urls: list[str] = []
        patches = await self.repository.recent_patches(project.id, tenant_id)
        prs = await self.repository.recently_merged_pull_requests(project.id, tenant_id)
        patches.extend(await self.repository.patches_for_pull_requests([pr.id for pr in prs], tenant_id))
        for patch in patches:
            route = route_from_repo_file(getattr(patch, "file_path", ""))
            if route:
                urls.append(self._absolute_project_url(project, route))
        return [url for url in urls if url]

    def _fix_task_values(self, planner_run: Any, issue: GSCIndexingIssue, project: Any) -> dict:
        task_type, impact, effort = self._task_shape(issue.issue_type)
        compliance_note = ""
        if self._needs_pharma_review(project, issue.page_url) and task_type == SeoTaskType.content_refresh:
            compliance_note = " Pharma/healthcare content updates must pass pharma_b2b compliance review before publishing."
        return {
            "tenant_id": issue.tenant_id,
            "project_id": issue.project_id,
            "planner_run_id": planner_run.id,
            "task_type": task_type,
            "title": f"Fix indexing issue: {issue.issue_type.value.replace('_', ' ')}"[:255],
            "description": (
                f"{issue.likely_cause}\n\nRecommended fix: {issue.recommended_fix}"
                f"{compliance_note}\n\nReview-only: do not publish, merge, deploy, or apply code automatically."
            ),
            "source_type": SeoTaskSourceType.search_console,
            "source_reference_id": issue.id,
            "target_page_url": issue.page_url,
            "target_keyword": None,
            "priority": self._priority_from_severity(issue.severity),
            "priority_score": self._score_from_severity(issue.severity),
            "estimated_impact": impact,
            "effort": effort,
            "status": SeoTaskStatus.todo,
            "due_date": planner_run.target_week_end,
        }

    def _task_shape(self, issue_type: GSCIndexingIssueType) -> tuple[SeoTaskType, SeoTaskImpact, SeoTaskEffort]:
        if issue_type in {GSCIndexingIssueType.sitemap_missing, GSCIndexingIssueType.blocked_by_robots, GSCIndexingIssueType.page_with_redirect}:
            return SeoTaskType.sitemap_robots_fix, SeoTaskImpact.high, SeoTaskEffort.medium
        if issue_type == GSCIndexingIssueType.structured_data_issue:
            return SeoTaskType.schema_addition, SeoTaskImpact.medium, SeoTaskEffort.medium
        if issue_type == GSCIndexingIssueType.orphan_page:
            return SeoTaskType.internal_link, SeoTaskImpact.medium, SeoTaskEffort.low
        if issue_type == GSCIndexingIssueType.thin_content:
            return SeoTaskType.content_refresh, SeoTaskImpact.high, SeoTaskEffort.high
        return SeoTaskType.technical_seo_fix, SeoTaskImpact.high, SeoTaskEffort.medium

    async def _repo_issue_values(self, issue: GSCIndexingIssue, tenant_id: UUID) -> Optional[dict]:
        scan = await self.repository.latest_repo_scan(issue.project_id, tenant_id)
        if not scan:
            return None
        mapping = {
            GSCIndexingIssueType.canonical_mismatch: SeoCodeIssueType.missing_canonical,
            GSCIndexingIssueType.duplicate_canonical: SeoCodeIssueType.missing_canonical,
            GSCIndexingIssueType.sitemap_missing: SeoCodeIssueType.route_not_in_sitemap,
            GSCIndexingIssueType.blocked_by_robots: SeoCodeIssueType.missing_robots,
            GSCIndexingIssueType.noindex_detected: SeoCodeIssueType.heading_semantics_risk,
            GSCIndexingIssueType.structured_data_issue: SeoCodeIssueType.missing_schema,
        }
        repo_issue_type = mapping.get(issue.issue_type)
        if not repo_issue_type:
            return None
        return {
            "tenant_id": issue.tenant_id,
            "project_id": issue.project_id,
            "repo_connection_id": scan.repo_connection_id,
            "scan_run_id": scan.id,
            "file_id": None,
            "issue_type": repo_issue_type,
            "severity": self._repo_severity(issue.severity),
            "title": f"Indexing fix plan for {issue.issue_type.value.replace('_', ' ')}"[:255],
            "description": issue.likely_cause,
            "recommended_fix": self._safe_repo_recommendation(issue),
            "source_reference_type": SeoCodeIssueSource.search_console,
            "source_reference_id": issue.id,
            "status": SeoCodeIssueStatus.open,
        }

    def _safe_repo_recommendation(self, issue: GSCIndexingIssue) -> str:
        if issue.issue_type in {GSCIndexingIssueType.sitemap_missing, GSCIndexingIssueType.blocked_by_robots}:
            return (
                f"{issue.recommended_fix} Never replace rich sitemap/robots logic automatically; "
                "only propose additive patches where the repo-agent safety classifier allows it."
            )
        return issue.recommended_fix

    def _repo_severity(self, severity: GSCIndexingIssueSeverity) -> SeoCodeIssueSeverity:
        value = self._enum_value(severity)
        if value == GSCIndexingIssueSeverity.critical.value:
            return SeoCodeIssueSeverity.critical
        if value == GSCIndexingIssueSeverity.high.value:
            return SeoCodeIssueSeverity.high
        if value == GSCIndexingIssueSeverity.low.value:
            return SeoCodeIssueSeverity.low
        return SeoCodeIssueSeverity.medium

    def _priority_from_severity(self, severity: GSCIndexingIssueSeverity) -> SeoTaskPriority:
        value = self._enum_value(severity)
        if value == GSCIndexingIssueSeverity.critical.value:
            return SeoTaskPriority.critical
        if value == GSCIndexingIssueSeverity.high.value:
            return SeoTaskPriority.high
        if value == GSCIndexingIssueSeverity.low.value:
            return SeoTaskPriority.low
        return SeoTaskPriority.medium

    def _score_from_severity(self, severity: GSCIndexingIssueSeverity) -> float:
        return {
            GSCIndexingIssueSeverity.critical.value: 95,
            GSCIndexingIssueSeverity.high.value: 82,
            GSCIndexingIssueSeverity.medium.value: 64,
            GSCIndexingIssueSeverity.low.value: 35,
        }.get(self._enum_value(severity), 50)

    def _needs_pharma_review(self, project: Any, page_url: str) -> bool:
        text = f"{getattr(project, 'name', '')} {getattr(project, 'domain', '')} {page_url}".lower()
        return any(term in text for term in ["pharma", "healthcare", "medicine", "medical"])

    def _important_route(self, project: Any, page_url: str, crawl_page: Optional[CrawlPage]) -> bool:
        root = self._project_root_url(project)
        if root and normalize_url(root) == normalize_url(page_url):
            return True
        if crawl_page and int(getattr(crawl_page, "depth", 9) or 9) <= 1:
            return True
        path = urlsplit(page_url).path.strip("/").lower()
        return not any(part in path for part in ["blog", "article", "tag", "category"]) and len(path.split("/")) <= 2

    def _project_root_url(self, project: Any) -> str:
        return self._absolute_project_url(project, "/")

    def _absolute_project_url(self, project: Any, url: str) -> str:
        raw = (url or "").strip()
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return normalize_url(raw)
        base = getattr(project, "domain", "") or ""
        if not base.startswith(("http://", "https://")):
            base = f"https://{base}"
        return normalize_url(f"{base.rstrip('/')}/{raw.lstrip('/')}")

    def _dedupe_candidates(self, candidates: Iterable[UrlCandidate]) -> List[UrlCandidate]:
        by_url: Dict[str, UrlCandidate] = {}
        for candidate in candidates:
            url = normalize_url(candidate.url)
            if not url:
                continue
            existing = by_url.get(url)
            if not existing or candidate.priority > existing.priority:
                by_url[url] = UrlCandidate(url=url, priority=candidate.priority, reason=candidate.reason)
        return sorted(by_url.values(), key=lambda item: (-item.priority, item.url))

    def _get_value(self, result: Any, key: str) -> Any:
        if isinstance(result, dict):
            return result.get(key)
        return getattr(result, key, None)

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)


def normalize_url_inspection_result(
    raw: dict,
    *,
    tenant_id: UUID,
    project_id: UUID,
    inspection_run_id: UUID,
    page_url: str,
) -> dict:
    """Normalize the official URL Inspection API payload into stored fields."""
    index_status = raw.get("indexStatusResult") or raw.get("index_status_result") or {}
    mobile = raw.get("mobileUsabilityResult") or raw.get("mobile_usability_result") or {}
    rich = raw.get("richResultsResult") or raw.get("rich_results_result") or {}
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "inspection_run_id": inspection_run_id,
        "page_url": normalize_url(page_url),
        "inspection_result_link": raw.get("inspectionResultLink") or raw.get("inspection_result_link"),
        "verdict": index_status.get("verdict"),
        "coverage_state": index_status.get("coverageState"),
        "indexing_state": index_status.get("indexingState"),
        "robots_txt_state": index_status.get("robotsTxtState"),
        "page_fetch_state": index_status.get("pageFetchState"),
        "google_canonical": index_status.get("googleCanonical"),
        "user_canonical": index_status.get("userCanonical"),
        "sitemap_urls": list(index_status.get("sitemap") or []),
        "referring_urls": list(index_status.get("referringUrls") or []),
        "last_crawl_time": parse_google_datetime(index_status.get("lastCrawlTime")),
        "crawled_as": index_status.get("crawledAs"),
        "mobile_usability_verdict": mobile.get("verdict"),
        "rich_results_verdict": rich.get("verdict"),
        "raw_result": raw,
    }


def parse_google_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if "." in raw:
        prefix, suffix = raw.split(".", 1)
        tz = ""
        if "+" in suffix:
            fractional, tz = suffix.split("+", 1)
            tz = "+" + tz
        elif "-" in suffix:
            fractional, tz = suffix.split("-", 1)
            tz = "-" + tz
        else:
            fractional = suffix
        raw = f"{prefix}.{fractional[:6]}{tz}"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def route_from_repo_file(file_path: str) -> Optional[str]:
    path = (file_path or "").replace("\\", "/")
    if not path:
        return None
    match = re.search(r"(?:^|/)app/(.+?)/(?:page|layout)\.(?:tsx|ts|jsx|js|mdx)$", path)
    if match:
        route = "/" + match.group(1).strip("/")
        return "/" if route == "/page" else route
    if path.endswith("app/page.tsx") or path.endswith("app/page.ts") or path in {"app/page.tsx", "app/page.ts"}:
        return "/"
    match = re.search(r"(?:^|/)pages/(.+?)\.(?:tsx|ts|jsx|js|mdx)$", path)
    if match:
        route = "/" + match.group(1).replace("index", "").strip("/")
        return route or "/"
    return None

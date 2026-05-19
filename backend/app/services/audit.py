"""Service layer for deterministic SEO audits."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.audit.rules import AuditLink, AuditPage, SEOAuditRulesEngine
from app.models.audit import (
    SEOAuditRun,
    SEOAuditStatus,
    SEOIssue,
    SEOIssueCategory,
    SEOIssueSeverity,
    SEOIssueStatus,
    SEOPageScore,
)
from app.models.crawl import CrawlStatus
from app.repositories.audit import AuditRepository

logger = structlog.get_logger(__name__)


class AuditService:
    """Create and execute deterministic SEO audits over crawl data."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = AuditRepository(db)
        self.rules_engine = SEOAuditRulesEngine()

    async def start_audit(self, crawl_job_id: UUID, tenant_id: UUID) -> SEOAuditRun:
        crawl = await self.repository.get_crawl(crawl_job_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")

        pages = await self.repository.list_crawl_pages(crawl_job_id)
        if not pages:
            raise ValueError("Crawl has no pages to audit")

        run = await self.repository.create_run(crawl)
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("Created SEO audit run", audit_run_id=str(run.id), crawl_job_id=str(crawl_job_id))
        return run

    async def execute_audit(self, audit_run_id: UUID) -> SEOAuditRun:
        run = await self.repository.get_run(audit_run_id)
        if not run:
            raise ValueError("Audit run not found")

        await self.repository.set_run_status(run, SEOAuditStatus.running, progress=10)
        await self.db.commit()

        try:
            crawl = await self.repository.get_crawl(run.crawl_job_id, run.tenant_id)
            if not crawl:
                raise ValueError("Crawl not found")

            pages = await self.repository.list_crawl_pages(run.crawl_job_id)
            links = await self.repository.list_crawl_links(run.crawl_job_id)
            result = self.rules_engine.analyze(
                pages=[self._page_snapshot(page) for page in pages],
                links=[self._link_snapshot(link) for link in links],
                seed_url=crawl.url,
            )

            issue_values = [
                {
                    "audit_run_id": run.id,
                    "crawl_job_id": run.crawl_job_id,
                    "crawl_page_id": issue.page_id,
                    "project_id": run.project_id,
                    "tenant_id": run.tenant_id,
                    "issue_type": issue.issue_type,
                    "title": issue.title,
                    "message": issue.message,
                    "recommendation": issue.recommendation,
                    "severity": issue.severity,
                    "category": issue.category,
                    "status": SEOIssueStatus.open,
                    "url": issue.url,
                    "evidence": issue.evidence,
                    "score_impact": issue.score_impact,
                }
                for issue in result.issues
            ]
            score_values = [
                {
                    "audit_run_id": run.id,
                    "crawl_job_id": run.crawl_job_id,
                    "crawl_page_id": score.page_id,
                    "project_id": run.project_id,
                    "tenant_id": run.tenant_id,
                    "url": score.url,
                    "score": score.score,
                    "issue_count": score.issue_count,
                    "critical_issues": score.severity_counts.get("critical", 0),
                    "high_issues": score.severity_counts.get("high", 0),
                    "medium_issues": score.severity_counts.get("medium", 0),
                    "low_issues": score.severity_counts.get("low", 0),
                    "score_breakdown": score.score_breakdown,
                }
                for score in result.page_scores
            ]

            await self.repository.replace_results(
                run,
                issues=issue_values,
                page_scores=score_values,
                site_score=result.site_score,
                issue_counts_by_severity=result.issue_counts_by_severity,
                issue_counts_by_category=result.issue_counts_by_category,
            )
            await self.repository.set_run_status(run, SEOAuditStatus.completed, progress=100)
            await self.db.commit()
            await self.db.refresh(run)
            logger.info("Completed SEO audit run", audit_run_id=str(run.id), site_score=run.site_score)
            return run
        except Exception as exc:
            await self.repository.set_run_status(run, SEOAuditStatus.failed, error_message=str(exc), progress=100)
            await self.db.commit()
            logger.error("SEO audit failed", audit_run_id=str(run.id), error=str(exc), exc_info=True)
            raise

    async def get_audit_status(self, audit_run_id: UUID, tenant_id: UUID) -> Optional[SEOAuditRun]:
        return await self.repository.get_run(audit_run_id, tenant_id)

    async def list_issues(
        self,
        tenant_id: UUID,
        audit_run_id: Optional[UUID] = None,
        crawl_job_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        severity: Optional[SEOIssueSeverity] = None,
        category: Optional[SEOIssueCategory] = None,
        issue_status: Optional[SEOIssueStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SEOIssue]:
        return await self.repository.list_issues(
            tenant_id=tenant_id,
            audit_run_id=audit_run_id,
            crawl_job_id=crawl_job_id,
            project_id=project_id,
            page_id=page_id,
            severity=severity,
            category=category,
            issue_status=issue_status,
            limit=limit,
            offset=offset,
        )

    async def get_page_score(
        self,
        page_id: UUID,
        tenant_id: UUID,
        audit_run_id: Optional[UUID] = None,
    ) -> Optional[SEOPageScore]:
        return await self.repository.get_page_score(page_id, tenant_id, audit_run_id)

    async def get_site_summary(
        self,
        crawl_job_id: UUID,
        tenant_id: UUID,
        audit_run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        run = (
            await self.repository.get_run(audit_run_id, tenant_id)
            if audit_run_id
            else await self.repository.latest_run_for_crawl(crawl_job_id, tenant_id)
        )
        if not run:
            return {}
        if run.crawl_job_id != crawl_job_id:
            return {}

        top_issue_types = await self.repository.count_open_issues_by_type(run.id)
        return {
            "audit_run_id": run.id,
            "crawl_job_id": run.crawl_job_id,
            "project_id": run.project_id,
            "status": run.status.value if hasattr(run.status, "value") else run.status,
            "site_score": run.site_score,
            "total_pages": run.total_pages,
            "total_issues": run.total_issues,
            "issue_counts_by_severity": run.issue_counts_by_severity or {},
            "issue_counts_by_category": run.issue_counts_by_category or {},
            "top_issue_types": top_issue_types,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }

    def _page_snapshot(self, page) -> AuditPage:
        return AuditPage(
            id=page.id,
            url=page.url,
            normalized_url=page.normalized_url,
            title=page.title,
            title_length=page.title_length,
            meta_description=page.meta_description,
            meta_description_length=page.meta_description_length,
            h1=page.h1 or [],
            canonical_url_normalized=page.canonical_url_normalized,
            noindex=bool(page.noindex),
            word_count=int(page.word_count or 0),
            total_images=int(page.total_images or 0),
            images_without_alt=int(page.images_without_alt or 0),
            external_links=int(page.external_links or 0),
            has_schema_markup=bool(page.has_schema_markup),
            has_og_tags=bool(page.has_og_tags),
            depth=int(page.depth or 0),
            status_code=page.status_code,
        )

    def _link_snapshot(self, link) -> AuditLink:
        return AuditLink(
            source_page_id=link.source_page_id,
            normalized_url=link.normalized_url,
            link_type=link.link_type or "internal",
            status_code=link.status_code,
            is_broken=bool(link.is_broken),
        )

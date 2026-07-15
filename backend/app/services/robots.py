"""Robots.txt intelligence service.

Fetches a project's live robots.txt, runs the deterministic analyzer, stores the
analysis + issues historically, and exposes latest/history/summary with a
latest-vs-previous delta so regressions surface automatically. Editing the file
itself is left to the repo-agent / PR workflow (human approval).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.project import Project
from app.models.robots import (
    RobotsAnalysisRun,
    RobotsAnalysisStatus,
    RobotsIssue,
    RobotsIssueStatus,
)
from app.robots.analyzer import analyze_robots, parse_robots

logger = structlog.get_logger(__name__)


@dataclass
class _Fetch:
    status_code: Optional[int]
    text: str
    ok: bool
    error: Optional[str] = None


class RobotsIntelligenceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_project(self, project_id: UUID, tenant_id: UUID) -> RobotsAnalysisRun:
        project = await self._get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")

        robots_url = self._robots_url(project.domain)
        fetch = await self._fetch(robots_url)

        if not fetch.ok and fetch.status_code is None:
            run = await self._persist_run(
                project, robots_url, RobotsAnalysisStatus.unreachable,
                fetch, sitemaps=0, groups=0, findings=[], error=fetch.error,
            )
            return run

        if fetch.status_code == 404 or (fetch.status_code and fetch.status_code >= 400):
            # Missing/blocked robots.txt is itself a finding.
            from app.robots.analyzer import RobotsFinding
            from app.models.robots import RobotsIssueSeverity, RobotsIssueType

            missing = RobotsFinding(
                RobotsIssueType.missing_robots,
                RobotsIssueSeverity.high if fetch.status_code == 404 else RobotsIssueSeverity.medium,
                "No reachable robots.txt",
                f"Fetching {robots_url} returned HTTP {fetch.status_code}. Without a robots.txt "
                "you cannot declare sitemaps or manage crawl behaviour.",
                "Add a robots.txt that at minimum declares the sitemap.",
                {"http_status": fetch.status_code, "url": robots_url},
            )
            status = RobotsAnalysisStatus.missing
            run = await self._persist_run(
                project, robots_url, status, fetch, sitemaps=0, groups=0, findings=[missing],
            )
            return run

        parsed = parse_robots(fetch.text)
        findings = analyze_robots(fetch.text)
        run = await self._persist_run(
            project, robots_url, RobotsAnalysisStatus.completed, fetch,
            sitemaps=len(parsed.sitemaps), groups=len(parsed.groups), findings=findings,
        )
        return run

    async def list_analyses(self, project_id: UUID, tenant_id: UUID, limit: int = 20, offset: int = 0) -> List[RobotsAnalysisRun]:
        result = await self.db.execute(
            select(RobotsAnalysisRun)
            .where(RobotsAnalysisRun.project_id == project_id, RobotsAnalysisRun.tenant_id == tenant_id)
            .order_by(RobotsAnalysisRun.created_at.desc())
            .limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def get_latest_analysis(self, project_id: UUID, tenant_id: UUID) -> Optional[RobotsAnalysisRun]:
        result = await self.db.execute(
            select(RobotsAnalysisRun)
            .where(RobotsAnalysisRun.project_id == project_id, RobotsAnalysisRun.tenant_id == tenant_id)
            .order_by(RobotsAnalysisRun.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def list_issues(
        self,
        project_id: UUID,
        tenant_id: UUID,
        analysis_run_id: Optional[UUID] = None,
        status: Optional[RobotsIssueStatus] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[RobotsIssue]:
        query = select(RobotsIssue).where(
            RobotsIssue.project_id == project_id, RobotsIssue.tenant_id == tenant_id
        )
        if analysis_run_id:
            query = query.where(RobotsIssue.analysis_run_id == analysis_run_id)
        if status:
            query = query.where(RobotsIssue.status == status)
        result = await self.db.execute(
            query.order_by(RobotsIssue.severity.desc(), RobotsIssue.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def update_issue_status(self, issue_id: UUID, tenant_id: UUID, status: RobotsIssueStatus) -> Optional[RobotsIssue]:
        result = await self.db.execute(
            select(RobotsIssue).where(RobotsIssue.id == issue_id, RobotsIssue.tenant_id == tenant_id)
        )
        issue = result.scalars().first()
        if not issue:
            return None
        issue.status = status
        await self.db.commit()
        await self.db.refresh(issue)
        return issue

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        analyses = await self.list_analyses(project_id, tenant_id, limit=2)
        if not analyses:
            return {"status": "no_data", "latest_run_id": None, "issues_by_severity": {}, "delta": {}}

        latest = analyses[0]
        latest_issues = await self.list_issues(project_id, tenant_id, analysis_run_id=latest.id, limit=1000)
        by_severity: Dict[str, int] = {}
        for issue in latest_issues:
            key = issue.severity.value
            by_severity[key] = by_severity.get(key, 0) + 1

        delta: Dict[str, Any] = {}
        if len(analyses) > 1:
            previous = analyses[1]
            prev_issues = await self.list_issues(project_id, tenant_id, analysis_run_id=previous.id, limit=1000)
            latest_types = {i.issue_type.value for i in latest_issues}
            prev_types = {i.issue_type.value for i in prev_issues}
            delta = {
                "new_issue_types": sorted(latest_types - prev_types),
                "resolved_issue_types": sorted(prev_types - latest_types),
                "previous_run_id": str(previous.id),
            }

        return {
            "status": latest.status.value,
            "latest_run_id": str(latest.id),
            "robots_url": latest.robots_url,
            "issues_total": len(latest_issues),
            "issues_by_severity": by_severity,
            "sitemap_directive_count": latest.sitemap_directive_count,
            "delta": delta,
        }

    # -- internals -----------------------------------------------------------

    async def _get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalars().first()

    @staticmethod
    def _robots_url(domain: str) -> str:
        raw = (domain or "").strip()
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = "https://" + raw
        parts = urlsplit(raw)
        base = f"{parts.scheme}://{parts.netloc}"
        return base + "/robots.txt"

    async def _fetch(self, url: str) -> _Fetch:
        try:
            async with httpx.AsyncClient(
                timeout=settings.GSC_SITEMAP_FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": settings.GSC_SITEMAP_USER_AGENT},
            ) as client:
                response = await client.get(url)
                raw = response.content[: settings.GSC_SITEMAP_MAX_BYTES]
                text = raw.decode(response.encoding or "utf-8", errors="replace")
                return _Fetch(status_code=response.status_code, text=text, ok=200 <= response.status_code < 300)
        except httpx.HTTPError as exc:
            return _Fetch(status_code=None, text="", ok=False, error=str(exc))

    async def _persist_run(
        self,
        project: Project,
        robots_url: str,
        status: RobotsAnalysisStatus,
        fetch: _Fetch,
        *,
        sitemaps: int,
        groups: int,
        findings,
        error: Optional[str] = None,
    ) -> RobotsAnalysisRun:
        content_hash = hashlib.sha256(fetch.text.encode("utf-8")).hexdigest() if fetch.text else None
        run = RobotsAnalysisRun(
            tenant_id=project.tenant_id,
            project_id=project.id,
            robots_url=robots_url,
            status=status,
            http_status_code=fetch.status_code,
            content_hash=content_hash,
            byte_size=len(fetch.text.encode("utf-8")) if fetch.text else 0,
            raw_content=fetch.text or None,
            sitemap_directive_count=sitemaps,
            user_agent_group_count=groups,
            issues_found=len(findings),
            error_message=error,
        )
        self.db.add(run)
        await self.db.flush()  # assign run.id

        for finding in findings:
            self.db.add(
                RobotsIssue(
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    analysis_run_id=run.id,
                    issue_type=finding.issue_type,
                    severity=finding.severity,
                    title=finding.title,
                    description=finding.description,
                    recommended_action=finding.recommended_action,
                    evidence=finding.evidence,
                )
            )
        await self.db.commit()
        await self.db.refresh(run)
        return run

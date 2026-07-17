"""Core Web Vitals service — official Google PageSpeed Insights integration.

Calls the real PSI v5 API (never fabricates data). Without an API key the API is
heavily rate-limited (HTTP 429); the service then records the run with
status=quota_exceeded and no metrics, so the platform degrades honestly instead
of inventing numbers.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.pagespeed import PagespeedRun, PagespeedStatus, PagespeedStrategy
from app.models.project import Project
from app.pagespeed.parser import parse_pagespeed

logger = structlog.get_logger(__name__)


class PagespeedService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_project(
        self,
        project_id: UUID,
        tenant_id: UUID,
        strategies: Optional[List[str]] = None,
    ) -> List[PagespeedRun]:
        """Run PSI for the project's URL on mobile + desktop and persist results."""
        project = await self._get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        url = self._project_url(project.domain)
        wanted = strategies or ["mobile", "desktop"]
        runs: List[PagespeedRun] = []
        for strat in wanted:
            runs.append(await self._analyze_one(project, tenant_id, url, strat))
        return runs

    async def _analyze_one(self, project: Project, tenant_id: UUID, url: str, strategy: str) -> PagespeedRun:
        run = PagespeedRun(
            tenant_id=tenant_id, project_id=project.id, url=url,
            strategy=PagespeedStrategy(strategy), status=PagespeedStatus.error,
        )
        try:
            params = {
                "url": url,
                "strategy": strategy,
                "category": ["performance", "accessibility", "best-practices", "seo"],
            }
            if settings.GOOGLE_PAGESPEED_API_KEY:
                params["key"] = settings.GOOGLE_PAGESPEED_API_KEY
            async with httpx.AsyncClient(timeout=settings.PAGESPEED_TIMEOUT_SECONDS) as client:
                resp = await client.get(settings.PAGESPEED_API_URL, params=params)

            if resp.status_code == 429:
                run.status = PagespeedStatus.quota_exceeded
                run.error_message = (
                    "PageSpeed Insights quota exceeded (HTTP 429). Set a free "
                    "GOOGLE_PAGESPEED_API_KEY for reliable Core Web Vitals data."
                )
                logger.warning("pagespeed_quota_exceeded", url=url, strategy=strategy)
            elif resp.status_code != 200:
                run.status = PagespeedStatus.error
                run.error_message = f"PageSpeed API HTTP {resp.status_code}: {resp.text[:300]}"
            else:
                parsed = parse_pagespeed(resp.json())
                run.status = PagespeedStatus.completed
                run.performance_score = parsed["performance_score"]
                run.accessibility_score = parsed["accessibility_score"]
                run.best_practices_score = parsed["best_practices_score"]
                run.seo_score = parsed["seo_score"]
                run.lcp_ms = parsed["lcp_ms"]
                run.cls = parsed["cls"]
                run.inp_ms = parsed["inp_ms"]
                run.tbt_ms = parsed["tbt_ms"]
                run.fcp_ms = parsed["fcp_ms"]
                run.speed_index_ms = parsed["speed_index_ms"]
                run.ttfb_ms = parsed["ttfb_ms"]
                run.field_lcp_ms = parsed["field_lcp_ms"]
                run.field_cls = parsed["field_cls"]
                run.field_inp_ms = parsed["field_inp_ms"]
                run.opportunities = parsed["opportunities"]
                run.diagnostics = parsed["diagnostics"]
        except httpx.HTTPError as exc:
            run.status = PagespeedStatus.error
            run.error_message = f"PageSpeed request failed: {exc}"[:1024]
            logger.warning("pagespeed_request_failed", url=url, strategy=strategy, error=str(exc))

        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def latest(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Latest completed run per strategy for the project."""
        out: Dict[str, Any] = {"mobile": None, "desktop": None}
        for strat in (PagespeedStrategy.mobile, PagespeedStrategy.desktop):
            run = (await self.db.execute(
                select(PagespeedRun).where(
                    PagespeedRun.project_id == project_id,
                    PagespeedRun.tenant_id == tenant_id,
                    PagespeedRun.strategy == strat,
                ).order_by(PagespeedRun.created_at.desc()).limit(1)
            )).scalars().first()
            out[strat.value] = run
        return out

    async def history(self, project_id: UUID, tenant_id: UUID, strategy: Optional[str] = None, limit: int = 50) -> List[PagespeedRun]:
        query = select(PagespeedRun).where(
            PagespeedRun.project_id == project_id, PagespeedRun.tenant_id == tenant_id
        )
        if strategy:
            query = query.where(PagespeedRun.strategy == PagespeedStrategy(strategy))
        rows = await self.db.execute(query.order_by(PagespeedRun.created_at.desc()).limit(limit))
        return list(rows.scalars().all())

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Compact Core Web Vitals summary for Mission Control / the brain."""
        latest = await self.latest(project_id, tenant_id)
        mobile, desktop = latest["mobile"], latest["desktop"]
        if not mobile and not desktop:
            return {"status": "no_data", "note": "Run PageSpeed analysis (needs GOOGLE_PAGESPEED_API_KEY for reliable data)."}
        primary = mobile or desktop
        opps = (primary.opportunities or [])[:5] if primary else []
        return {
            "status": self._enum(primary.status) if primary else "no_data",
            "performance_mobile": mobile.performance_score if mobile else None,
            "performance_desktop": desktop.performance_score if desktop else None,
            "lcp_ms": primary.lcp_ms if primary else None,
            "cls": primary.cls if primary else None,
            "inp_ms": primary.inp_ms if primary else None,
            "top_opportunities": [{"id": o["id"], "title": o["title"], "savings_ms": o["savings_ms"]} for o in opps],
        }

    @staticmethod
    def delta(before: "PagespeedRun", after: "PagespeedRun") -> Dict[str, Any]:
        """Before/after deltas for the verification engine (positive = improved
        for scores; negative = improved for CWV timings/CLS)."""
        def d(a, b):
            return round(b - a, 2) if (a is not None and b is not None) else None
        return {
            "performance_delta": d(before.performance_score, after.performance_score),
            "accessibility_delta": d(before.accessibility_score, after.accessibility_score),
            "best_practices_delta": d(before.best_practices_score, after.best_practices_score),
            "seo_delta": d(before.seo_score, after.seo_score),
            "lcp_ms_delta": d(before.lcp_ms, after.lcp_ms),
            "cls_delta": d(before.cls, after.cls),
            "inp_ms_delta": d(before.inp_ms, after.inp_ms),
            "fcp_ms_delta": d(before.fcp_ms, after.fcp_ms),
            "tbt_ms_delta": d(before.tbt_ms, after.tbt_ms),
        }

    async def _get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        return (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()

    @staticmethod
    def _project_url(domain: str) -> str:
        raw = (domain or "").strip()
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = "https://" + raw
        return raw

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)

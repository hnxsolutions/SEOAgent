"""Core Web Vitals service — official Google PageSpeed Insights integration.

Calls the real PSI v5 API (never fabricates data). Without an API key the API is
heavily rate-limited (HTTP 429); the service then records the run with
status=quota_exceeded and no metrics, so the platform degrades honestly instead
of inventing numbers.
"""
from __future__ import annotations

import asyncio

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

#: One retry, not more. A PSI analysis costs Google a full Lighthouse run and
#: costs us up to a minute and a half of wall clock; hammering it turns a slow
#: page into a very slow page. Measured failures split cleanly into transient
#: (a retry succeeds) and structural (every attempt fails the same way), and a
#: second attempt separates the two without a third adding anything.
PAGESPEED_MAX_ATTEMPTS = 2

#: Breathing room for the upstream before the second attempt.
PAGESPEED_RETRY_BACKOFF_SECONDS = 5.0

#: Lighthouse failure codes that mean "the analyser gave up", not "the site is
#: broken". They arrive as HTTP 500 from PSI, which says nothing on its own.
_LIGHTHOUSE_TIMEOUT_CODES = ("PROTOCOL_TIMEOUT", "TIMED_OUT", "NO_FCP")

#: ...and the ones that mean Google could not load the page at all.
_LIGHTHOUSE_FETCH_CODES = (
    "ERRORED_DOCUMENT_REQUEST",
    "FAILED_DOCUMENT_REQUEST",
    "DNS_FAILURE",
    "INVALID_URL",
)


def describe_upstream_error(status_code: int, body: str) -> str:
    """Turn a PageSpeed failure into a sentence an operator can act on.

    The raw body is a JSON envelope wrapping a Lighthouse error string. Printed
    verbatim it fills the card with braces and quoted field names and tells the
    reader nothing they can do about it — which is exactly what the dashboard
    was showing. The distinction that matters is not the HTTP code but whether
    Google could not *reach* the page or could not *finish analysing* it, so
    that is what this says.
    """
    message = ""
    try:
        import json

        message = str(json.loads(body).get("error", {}).get("message", ""))
    except Exception:
        message = body[:300]

    upper = message.upper()

    if any(code in upper for code in _LIGHTHOUSE_TIMEOUT_CODES):
        return (
            "Google's own analyser timed out on this page before it could finish. "
            "That usually means the page is heavy enough to exhaust Lighthouse's "
            "instrumentation budget — a very large stylesheet or script payload is "
            "the common cause. Lighter pages on the same site normally still score. "
            f"(Google reported: {message[:160]})"
        )

    if any(code in upper for code in _LIGHTHOUSE_FETCH_CODES):
        return (
            "Google could not load this page to analyse it. Check that the URL is "
            "publicly reachable and is not blocking Google's fetcher. "
            f"(Google reported: {message[:160]})"
        )

    return f"PageSpeed Insights could not analyse this page (HTTP {status_code}). {message[:240]}".strip()


def describe_exception(exc: Exception, timeout_seconds: float) -> str:
    """Name a transport failure that cannot name itself.

    ``str()`` on an httpx timeout is the empty string, so the obvious
    f-string produced "PageSpeed request failed: " — an error card with no
    error in it, which is worse than no card at all because it looks like a
    bug in the dashboard rather than a timeout.
    """
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"No response from the PageSpeed Insights API within {timeout_seconds:.0f}s. "
            "A full analysis of a heavy page can legitimately take this long; "
            "retrying usually succeeds."
        )
    detail = str(exc).strip()
    return f"PageSpeed request failed: {type(exc).__name__}" + (f": {detail}" if detail else "")


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
        timeout = float(settings.PAGESPEED_TIMEOUT_SECONDS)

        # Mobile and desktop are independent analyses on Google's side, and this
        # endpoint blocks the browser until both come back. Run one after the
        # other they added up: two analyses that can each take two minutes meant
        # a request nobody would wait out. Fetched together, the wait is the
        # slower of the two rather than their sum.
        #
        # Only the HTTP calls overlap. The results are written one at a time
        # below, because an AsyncSession is a single connection and driving it
        # from concurrent tasks corrupts its state.
        results = await asyncio.gather(
            *(self._fetch_with_retry(url, strat, timeout) for strat in wanted)
        )

        runs: List[PagespeedRun] = []
        for strat, (resp, exc) in zip(wanted, results):
            runs.append(await self._persist_run(project, tenant_id, url, strat, resp, exc, timeout))
        return runs

    async def _persist_run(
        self,
        project: Project,
        tenant_id: UUID,
        url: str,
        strategy: str,
        resp: Optional[httpx.Response],
        exc: Optional[Exception],
        timeout: float,
    ) -> PagespeedRun:
        """Turn one fetched PSI result into a stored run."""
        run = PagespeedRun(
            tenant_id=tenant_id, project_id=project.id, url=url,
            strategy=PagespeedStrategy(strategy), status=PagespeedStatus.error,
        )

        if resp is None:
            run.status = PagespeedStatus.error
            run.error_message = describe_exception(exc, timeout)[:1024]
            logger.warning(
                "pagespeed_request_failed",
                url=url,
                strategy=strategy,
                error_type=type(exc).__name__,
            )
        else:
            if resp.status_code == 429:
                run.status = PagespeedStatus.quota_exceeded
                run.error_message = (
                    "PageSpeed Insights quota exceeded (HTTP 429). Set a free "
                    "GOOGLE_PAGESPEED_API_KEY for reliable Core Web Vitals data."
                )
                logger.warning("pagespeed_quota_exceeded", url=url, strategy=strategy)
            elif resp.status_code != 200:
                run.status = PagespeedStatus.error
                run.error_message = describe_upstream_error(resp.status_code, resp.text)[:1024]
                logger.warning(
                    "pagespeed_upstream_error",
                    url=url,
                    strategy=strategy,
                    status_code=resp.status_code,
                )
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

        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def _fetch_with_retry(
        self,
        url: str,
        strategy: str,
        timeout: float,
    ) -> tuple[Optional[httpx.Response], Optional[Exception]]:
        """Ask PSI for one analysis, retrying the failures that are worth retrying.

        Returns the response, or the transport exception when there was none.

        A 5xx from PSI is usually Lighthouse giving up rather than Google being
        down, and that is sometimes luck: the same page can fail one minute and
        score the next. Retrying 4xx would be pointless (the request is wrong)
        and retrying 429 would be rude (we are already over quota), so neither
        is retried.
        """
        params = {
            "url": url,
            "strategy": strategy,
            "category": ["performance", "accessibility", "best-practices", "seo"],
        }
        if settings.GOOGLE_PAGESPEED_API_KEY:
            params["key"] = settings.GOOGLE_PAGESPEED_API_KEY

        response: Optional[httpx.Response] = None
        error: Optional[Exception] = None

        for attempt in range(1, PAGESPEED_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(settings.PAGESPEED_API_URL, params=params)
                error = None
                if response.status_code < 500:
                    return response, None
            except httpx.HTTPError as exc:
                response, error = None, exc

            if attempt < PAGESPEED_MAX_ATTEMPTS:
                logger.info(
                    "pagespeed_retrying",
                    url=url,
                    strategy=strategy,
                    attempt=attempt,
                    status_code=response.status_code if response is not None else None,
                    error_type=type(error).__name__ if error else None,
                )
                await asyncio.sleep(PAGESPEED_RETRY_BACKOFF_SECONDS)

        return response, error

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

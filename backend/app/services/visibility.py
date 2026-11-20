"""
SEO Agent SaaS - AI Visibility Service

**This measures nothing, and says so.**

Whether a site is cited by ChatGPT, Perplexity or Google's AI answers cannot be
observed reliably for free: there is no first-party API that reports it, answers
differ per user and per session, and scraping an assistant's output gives a
sample of one that changes on the next request. Every product that shows a
confident "AI visibility score" is either paying a vendor or guessing.

This service previously returned `total_mentions: 0`, `visibility_score: 0.0`
and an empty trend list. That reads on a dashboard as *measured and zero* —
indistinguishable from a site genuinely never cited — which is exactly the kind
of fabrication this codebase refuses everywhere else. It now returns an explicit
`available: False` with the reason, so a caller cannot mistake absence of data
for data.

What **is** measured, and is a different thing, lives in the AEO engine
(`app/services/geo_aeo.py`): how well a page is *structured to be quoted* —
entity clarity, factual density, answer blocks, FAQ coverage, schema,
extractability. That is optimisation, not citation measurement, and the two are
reported separately on purpose.

The `AiVisibilityProvider` protocol below is the seam for a future provider —
first-party, open or paid — without the rest of the system changing. No such
provider ships by default.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


#: One string, used everywhere, so the UI can key off it rather than parsing prose.
NOT_MEASURABLE = "not_measurable_for_free"

UNAVAILABLE_REASON = (
    "Actual AI citation data is not reliably measurable without a paid provider. "
    "No score has been estimated. See the AEO analysis for how well this site is "
    "structured to be cited, which is measured."
)


@runtime_checkable
class AiVisibilityProvider(Protocol):
    """The seam a real citation source would implement.

    Deliberately narrow. A provider answers "where was this domain cited for
    these prompts, and when" — it does not get to invent a score; scoring stays
    here so that every provider is reported the same way.
    """

    name: str

    async def citations(
        self, domain: str, prompts: List[str]
    ) -> List[Dict[str, Any]]:  # pragma: no cover - interface only
        ...


def _unavailable(**extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "available": False,
        "status": NOT_MEASURABLE,
        "reason": UNAVAILABLE_REASON,
        "measured_at": None,
        "provider": None,
    }
    payload.update(extra)
    return payload


class VisibilityService:
    """AI visibility — unmeasured by default, and honest about it."""

    def __init__(self, db: AsyncSession, provider: Optional[AiVisibilityProvider] = None):
        self.db = db
        #: None unless a deployment supplies one. Nothing ships one.
        self.provider = provider

    async def query_visibility(
        self,
        keywords: Optional[List[str]] = None,
        topics: Optional[List[str]] = None,
        date_range: Optional[Dict[str, datetime]] = None,
        tenant_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        if self.provider is None:
            return _unavailable(
                total_mentions=None,
                visibility_score=None,
                avg_position=None,
                top_keywords=[],
                trends=[],
                alternative="Use the AEO analysis (/api/v1/geo-aeo) for measured answer-engine readiness.",
            )
        # A provider was supplied by this deployment; report what it returns and
        # attribute it, never blending it with anything invented here.
        citations = await self.provider.citations("", list(keywords or []))
        return {
            "available": True,
            "status": "measured",
            "provider": getattr(self.provider, "name", "custom"),
            "measured_at": datetime.utcnow().isoformat(),
            "total_mentions": len(citations),
            "citations": citations,
        }

    async def get_trends(
        self, days: int = 30, tenant_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        if self.provider is None:
            return _unavailable(
                window_days=days,
                data_points=[],
                trend_direction=None,
                change_percentage=None,
            )
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        logger.info("ai_visibility_trend_requested", provider=getattr(self.provider, "name", "custom"))
        return {
            "available": True,
            "status": "measured",
            "provider": getattr(self.provider, "name", "custom"),
            "window_days": days,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "data_points": [],
        }

    async def get_competitor_analysis(
        self, tenant_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """Competitor AI visibility — the same answer, for the same reason.

        A dict rather than the previous empty list: `[]` says "we looked and
        found no competitors", which is not what happened.
        """
        return _unavailable(
            competitors=[],
            alternative=(
                "Competitor ranking data needs a paid SERP provider. The free signals "
                "this system does measure are your own Search Console queries, content "
                "gaps and topic coverage."
            ),
        )

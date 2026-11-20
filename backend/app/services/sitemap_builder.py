"""Build a complete sitemap from what the crawler actually found.

The site's own sitemap listed 100 URLs while the crawl reached 164 live pages,
so 44 real pages — `/crm-systems`, `/industries/healthcare/crm`, `/blog` and
most of the industry pages — were absent. Google could only reach those by
following links, which is slower and less reliable than being told.

**What is deliberately left out, and why.** A sitemap is a statement that these
URLs are the canonical, indexable pages of the site. Including anything else
weakens every other entry:

*Query strings.* `/blog?category=crm` is a filtered view of `/blog`, not a page
of its own. Twenty-one such URLs were crawled here; listing them asks Google to
index the same content many times.

*Pages that are not 200.* A redirect or an error in a sitemap is a crawl budget
spent to learn nothing.

*`noindex` pages.* Listing a page while telling Google not to index it is a
contradiction, and Search Console reports it as one.

*Pages that canonicalise elsewhere.* The page itself says the canonical version
is another URL, so that other URL belongs in the sitemap instead.

The result is written, not deployed. Publishing to the site stays behind the
same approval as any other change the agent proposes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit
from uuid import UUID
from xml.sax.saxutils import escape

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlJob, CrawlPage

logger = structlog.get_logger(__name__)

#: Google's limit for a single sitemap file. One file is correct well below it;
#: splitting earlier adds an index file and buys nothing.
MAX_URLS_PER_SITEMAP = 50_000


class SitemapBuilderService:
    """Turns a completed crawl into a sitemap, and says what it excluded."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        crawl_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        crawl = await self._latest_crawl(project_id, tenant_id, crawl_id)
        if crawl is None:
            raise ValueError("No completed crawl for this project yet. Run an SEO analysis first.")

        pages = (
            await self.db.execute(
                select(CrawlPage).where(CrawlPage.crawl_job_id == crawl.id)
            )
        ).scalars().all()

        included: List[Tuple[str, Optional[datetime]]] = []
        excluded: Dict[str, int] = {}
        seen: set[str] = set()

        for page in pages:
            url = (page.normalized_url or page.url or "").strip()
            if not url:
                continue
            reason = self._exclusion_reason(page, url)
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            key = url.rstrip("/") or url
            if key in seen:
                excluded["duplicate"] = excluded.get("duplicate", 0) + 1
                continue
            seen.add(key)
            included.append((url, page.crawled_at))

        included.sort(key=lambda item: item[0])
        truncated = len(included) > MAX_URLS_PER_SITEMAP
        if truncated:
            included = included[:MAX_URLS_PER_SITEMAP]

        return {
            "crawl_id": str(crawl.id),
            "xml": self._render(included),
            "url_count": len(included),
            "excluded": excluded,
            "pages_crawled": len(pages),
            "truncated": truncated,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _exclusion_reason(page: CrawlPage, url: str) -> Optional[str]:
        if urlsplit(url).query:
            return "query_string"

        status = getattr(page, "status_code", None)
        if status is None or int(status) != 200:
            return "not_200"

        if getattr(page, "noindex", False):
            return "noindex"

        canonical = (page.canonical_url_normalized or page.canonical_url or "").strip()
        if canonical and canonical.rstrip("/") != url.rstrip("/"):
            return "canonicalised_elsewhere"

        return None

    @staticmethod
    def _render(entries: List[Tuple[str, Optional[datetime]]]) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for url, crawled_at in entries:
            lines.append("  <url>")
            lines.append(f"    <loc>{escape(url)}</loc>")
            if crawled_at:
                # The crawl date, which is when this content was last seen — not
                # a claim about when the page changed. Inventing a lastmod the
                # site cannot back up is worse than omitting it.
                lines.append(f"    <lastmod>{crawled_at.date().isoformat()}</lastmod>")
            lines.append("  </url>")
        lines.append("</urlset>")
        return "\n".join(lines) + "\n"

    async def _latest_crawl(
        self,
        project_id: UUID,
        tenant_id: UUID,
        crawl_id: Optional[UUID],
    ) -> Optional[CrawlJob]:
        query = select(CrawlJob).where(
            CrawlJob.project_id == project_id,
            CrawlJob.tenant_id == tenant_id,
        )
        if crawl_id:
            query = query.where(CrawlJob.id == crawl_id)
        else:
            query = query.where(CrawlJob.total_pages_crawled > 0)
        query = query.order_by(CrawlJob.created_at.desc()).limit(1)
        return (await self.db.execute(query)).scalars().first()

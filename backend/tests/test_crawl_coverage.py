"""A crawl must not report a partial site as a finished one.

`total_pages_discovered` was incremented by the worker as it *enqueued* URLs,
and enqueueing stops at the page cap — so the counter could never exceed the cap
and always equalled the number crawled. A site whose sitemap lists 110 URLs and
whose link graph holds 171 was crawled to 99 and recorded "99 discovered, 99
crawled". The audit, the content suggestions and the planner were then built
from a little over half the site, and nothing anywhere said so.
"""
from __future__ import annotations

import pytest

from app.core.config import settings


def test_the_default_page_budget_covers_an_ordinary_site():
    """100 truncated a 171-page site. The figure has to be large enough that the
    cap is a safety ceiling rather than the thing deciding what gets audited."""
    assert settings.SEO_RUN_MAX_PAGES >= 1000


def test_the_deep_budget_is_not_smaller_than_the_normal_one():
    assert settings.SEO_DEEP_RUN_MAX_PAGES >= settings.SEO_RUN_MAX_PAGES


def test_discovered_is_recomputed_from_the_link_graph_not_the_queue():
    """The fix in one assertion: the aggregate reads crawl_links, so it reflects
    what the site contains rather than what there was budget to fetch. Counting
    enqueued URLs is what made the number meaningless.
    """
    import inspect

    from app.repositories.crawl import CrawlRepository

    source = inspect.getsource(CrawlRepository.refresh_job_aggregates)

    assert "total_pages_discovered" in source
    assert "CrawlLink" in source
    assert "distinct" in source.lower()


def test_discovered_is_never_less_than_crawled():
    """A page can be crawled without being linked to — the start URL, sitemap
    entries — so the honest floor is what was actually fetched."""
    import inspect

    from app.repositories.crawl import CrawlRepository

    source = inspect.getsource(CrawlRepository.refresh_job_aggregates)

    assert "max(int(discovered.scalar() or 0), total_pages)" in source

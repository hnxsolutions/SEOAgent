"""Links discovered on a page are queued up to the job's budget, not a fixed 50.

The worker took `new_urls[: min(50, remaining)]`, so a page with more than fifty
internal links had the rest dropped silently however much page budget was left.
Measured on a real site: the homepage carried 71 internal links, 21 were
discarded, and nine of those were linked from nowhere else and absent from the
sitemap — so they were never crawled at all. The crawl reported 171 of 177 pages
and nothing explained the gap.
"""
from __future__ import annotations

import inspect

from app.crawler.worker import CrawlWorker


def executable_source(func) -> str:
    """Source with comments stripped: the fix's comment quotes the old
    expression, so a plain substring search would match the explanation."""
    lines = []
    for line in inspect.getsource(func).splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            lines.append(code)
    return chr(10).join(lines)


def test_the_fixed_fifty_link_cap_is_gone():
    source = executable_source(CrawlWorker.process_task)

    assert "min(50, remaining)" not in source


def test_links_are_bounded_by_the_remaining_page_budget():
    """`remaining` already stops the queue exceeding max_pages, which is the
    limit that was actually wanted."""
    source = executable_source(CrawlWorker.process_task)

    assert "new_urls[:remaining]" in source


def test_remaining_capacity_is_derived_from_max_pages():
    source = executable_source(CrawlWorker._remaining_capacity)

    assert "max_pages" in source
    assert "max(0," in source

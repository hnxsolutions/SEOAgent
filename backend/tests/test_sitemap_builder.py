"""Building a sitemap from what the crawler actually found.

The site's own sitemap listed 100 URLs against 164 live pages, so 44 real pages
were reachable only by following links. The risk in generating one is the
opposite mistake — listing everything crawled — because a sitemap is a statement
that these are the canonical, indexable pages, and each wrong entry weakens the
rest. These pin what must be left out.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services.sitemap_builder import MAX_URLS_PER_SITEMAP, SitemapBuilderService


def page(url, *, status=200, noindex=False, canonical=None):
    return SimpleNamespace(
        url=url,
        normalized_url=url,
        status_code=status,
        noindex=noindex,
        canonical_url=canonical,
        canonical_url_normalized=canonical,
        crawled_at=datetime(2026, 10, 7),
    )


def reason(p):
    return SitemapBuilderService._exclusion_reason(p, p.normalized_url)


def test_a_normal_page_is_included():
    assert reason(page("https://example.com/services")) is None


def test_a_filtered_view_is_excluded():
    """`/blog?category=crm` is a view of `/blog`, not a page of its own. Twenty
    one such URLs were crawled on the real site."""
    assert reason(page("https://example.com/blog?category=crm")) == "query_string"


def test_a_non_200_is_excluded():
    """A redirect or error in a sitemap spends crawl budget to learn nothing."""
    assert reason(page("https://example.com/gone", status=404)) == "not_200"
    assert reason(page("https://example.com/moved", status=301)) == "not_200"


def test_a_noindex_page_is_excluded():
    """Listing a page while telling Google not to index it is a contradiction,
    and Search Console reports it as one."""
    assert reason(page("https://example.com/private", noindex=True)) == "noindex"


def test_a_page_that_canonicalises_elsewhere_is_excluded():
    """The page itself says another URL is the canonical one, so that URL
    belongs in the sitemap instead."""
    p = page("https://example.com/a", canonical="https://example.com/b")

    assert reason(p) == "canonicalised_elsewhere"


def test_a_self_canonical_page_is_kept():
    """Most pages declare themselves canonical; that is not an exclusion."""
    p = page("https://example.com/a", canonical="https://example.com/a")

    assert reason(p) is None


def test_a_trailing_slash_does_not_make_a_page_non_canonical():
    p = page("https://example.com/a", canonical="https://example.com/a/")

    assert reason(p) is None


def test_the_xml_is_well_formed_and_escaped():
    from xml.etree import ElementTree

    xml = SitemapBuilderService._render(
        [("https://example.com/a?b=1&c=2", datetime(2026, 10, 7))]
    )
    root = ElementTree.fromstring(xml)

    locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert locs == ["https://example.com/a?b=1&c=2"]


def test_lastmod_is_the_crawl_date_not_an_invention():
    xml = SitemapBuilderService._render([("https://example.com/a", datetime(2026, 10, 7))])

    assert "<lastmod>2026-10-07</lastmod>" in xml


def test_a_page_with_no_crawl_date_simply_omits_lastmod():
    xml = SitemapBuilderService._render([("https://example.com/a", None)])

    assert "<lastmod>" not in xml


def test_the_single_file_limit_is_googles():
    assert MAX_URLS_PER_SITEMAP == 50_000

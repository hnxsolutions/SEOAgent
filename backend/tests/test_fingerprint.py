"""Tests for the Technology Fingerprint detector (pure, no network)."""
from app.fingerprint.detector import SiteSignals, TechnologyFingerprintDetector


def _detect(**kwargs):
    return TechnologyFingerprintDetector().detect(SiteSignals(**kwargs))


def _names(result):
    return {t.name for t in result.technologies}


def test_detects_nextjs_on_vercel_with_evidence():
    html = (
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="x">'
        '<link rel="canonical" href="https://x.com/">'
        '<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>'
        '</head><body><div id="__next">Lots of real server rendered content here '
        + ("word " * 80) + '</div><img src="/_next/image?url=a" alt="a"></body></html>'
    )
    r = _detect(
        url="https://x.com", final_url="https://x.com", status_code=200,
        headers={"server": "Vercel", "x-vercel-id": "abc", "content-encoding": "br",
                 "cache-control": "public, max-age=60", "strict-transport-security": "max-age=1"},
        html=html, robots_txt="User-agent: *\nSitemap: https://x.com/sitemap.xml", has_sitemap=True,
    )
    assert r.primary_framework == "Next.js"
    assert "React" in _names(r)          # inferred underlying library
    assert r.hosting == "Vercel"
    assert "next/image" in _names(r)
    nextjs = next(t for t in r.technologies if t.name == "Next.js")
    assert nextjs.confidence >= 90 and nextjs.evidence  # confidence + why
    assert r.scores["seo_readiness"] >= 60  # title+desc+canonical+sitemap+robots present
    assert r.scores["security"] >= 40
    assert r.scores["indexability"] == 100


def test_detects_wordpress_php_and_cms():
    html = (
        '<html><head><meta name="generator" content="WordPress 6.5">'
        '<link rel="stylesheet" href="/wp-content/themes/x/style.css"></head>'
        '<body>content ' + ("word " * 80) + '</body></html>'
    )
    r = _detect(
        url="https://blog.example", final_url="https://blog.example", status_code=200,
        headers={"server": "Apache", "x-powered-by": "PHP/8.2"},
        html=html, robots_txt=None, has_sitemap=False,
    )
    assert r.primary_cms == "WordPress"
    assert r.primary_language == "PHP"
    assert "Apache" in _names(r)


def test_detects_shopify_and_cloudflare():
    html = '<html><head></head><body><script src="https://cdn.shopify.com/s/x.js"></script></body></html>'
    r = _detect(
        url="https://shop.example", final_url="https://shop.example", status_code=200,
        headers={"server": "cloudflare", "cf-ray": "abc123"},
        html=html,
    )
    assert r.primary_cms == "Shopify"
    assert r.cdn == "Cloudflare"


def test_indexability_penalized_when_blocked_and_noindex():
    html = '<html><head><meta name="robots" content="noindex,nofollow"></head><body>x</body></html>'
    r = _detect(
        url="https://x.com", final_url="https://x.com", status_code=200,
        headers={}, html=html,
        robots_txt="User-agent: *\nDisallow: /", has_sitemap=False,
    )
    # blocked (-60) + meta noindex (-40) + no sitemap (-10), floored at 0
    assert r.scores["indexability"] == 0


def test_http_only_site_scores_lower_security():
    r = _detect(url="http://x.com", final_url="http://x.com", status_code=200, headers={}, html="<html></html>")
    assert r.scores["security"] == 0  # no https, no HSTS/CSP


def test_content_hash_stable_across_trivial_text_changes():
    base = '<html><body><div id="__next">{}</div><script id="__NEXT_DATA__">1</script></body></html>'
    a = _detect(url="https://x.com", final_url="https://x.com", status_code=200, headers={"server": "Vercel"}, html=base.format("hello"))
    b = _detect(url="https://x.com", final_url="https://x.com", status_code=200, headers={"server": "Vercel"}, html=base.format("different copy entirely"))
    # Same structural markers -> same hash (Learning: never relearn identical stack)
    assert a.content_hash == b.content_hash


def test_json_ld_schema_types_captured():
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Organization","name":"X"}</script></head><body>x</body></html>'
    )
    r = _detect(url="https://x.com", final_url="https://x.com", status_code=200, headers={}, html=html)
    schema = next(t for t in r.technologies if t.name == "JSON-LD Schema.org")
    assert any("Organization" in e for e in schema.evidence)

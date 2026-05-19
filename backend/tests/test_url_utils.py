from app.core.url_utils import URLDeduplicator, URLNormalizer


def test_normalize_url_strips_tracking_and_fragment():
    normalized = URLNormalizer.normalize_url(
        "HTTPS://Example.COM/products/?utm_source=newsletter&b=2&a=1#reviews"
    )

    assert normalized == "https://example.com/products/?a=1&b=2"


def test_deduplicator_uses_normalized_urls():
    deduplicator = URLDeduplicator()

    assert deduplicator.add("https://example.com/page?utm_campaign=spring#top") is True
    assert deduplicator.add("https://example.com/page") is False


def test_internal_link_is_same_domain_even_when_scheme_changes():
    assert URLNormalizer.is_internal_link(
        "http://example.com/start",
        "https://example.com/about",
    )
    assert not URLNormalizer.is_internal_link(
        "https://example.com/start",
        "https://other.example/about",
    )

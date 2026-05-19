from app.crawler.extraction import classify_links, count_words, normalize_whitespace, parse_json_ld_scripts


def test_parse_json_ld_collects_schema_types():
    markup, schema_types = parse_json_ld_scripts(
        [
            '{"@context":"https://schema.org","@type":"WebPage"}',
            '{"@graph":[{"@type":"Organization"},{"@type":["WebSite","Thing"]}]}',
            "{not valid json}",
        ]
    )

    assert markup is not None
    assert schema_types == ["Organization", "Thing", "WebPage", "WebSite"]


def test_classify_links_normalizes_deduplicates_and_filters():
    internal, external, internal_urls, external_urls = classify_links(
        "https://example.com/articles/start",
        [
            {"href": "/about?utm_source=x", "text": " About ", "rel": "", "target": ""},
            {"href": "https://example.com/about", "text": "Duplicate", "rel": "", "target": ""},
            {"href": "http://example.com/login", "text": "Login", "rel": "", "target": ""},
            {"href": "https://external.test/path", "text": "External", "rel": "nofollow", "target": "_blank"},
            {"href": "mailto:hello@example.com", "text": "Email"},
        ],
    )

    assert [link["text"] for link in internal] == ["About", "Login"]
    assert len(external) == 1
    assert external[0]["is_nofollow"] is True
    assert internal_urls == ["https://example.com/about", "https://example.com/login"]
    assert external_urls == ["https://external.test/path"]


def test_text_helpers_normalize_and_count_words():
    text = normalize_whitespace(" First\n\nsecond\tthird ")

    assert text == "First second third"
    assert count_words(text) == 3

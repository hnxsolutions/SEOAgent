"""Tests for sitemap intelligence: GSC Sitemaps API client, detection, parsing, issues."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.search_console import GSCPropertySourceType
from app.models.sitemap import (
    SitemapIssueSeverity,
    SitemapIssueType,
    SitemapSource,
    SitemapStatus,
)
from app.services.search_console import GoogleSearchConsoleClient, SearchConsoleGoogleAPIError
from app.services.sitemap import SitemapIntelligenceService, SitemapServiceError


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    async def flush(self):
        return None


def obj(**kwargs):
    return SimpleNamespace(**kwargs)


def make_service(**overrides):
    service = SitemapIntelligenceService(FakeDB(), google_client=overrides.pop("google_client", GoogleSearchConsoleClient()))
    for key, value in overrides.items():
        setattr(service, key, value)
    return service


def sitemap_record(**overrides):
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "project_id": uuid4(),
        "sitemap_url": "https://example.com/sitemap.xml",
        "is_submitted": False,
        "status": SitemapStatus.active,
        "source": SitemapSource.detected,
        "errors_count": 0,
        "warnings_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ---- GSC Sitemaps API client -------------------------------------------------


@pytest.mark.asyncio
async def test_list_sitemaps_uses_official_endpoint_and_parses(monkeypatch):
    client = GoogleSearchConsoleClient()
    captured = {}

    async def fake_request_json(method, url, access_token, json=None):
        captured.update({"method": method, "url": url})
        return {"sitemap": [{"path": "https://example.com/sitemap.xml", "errors": "0"}]}

    monkeypatch.setattr(client, "_request_json", fake_request_json)
    entries = await client.list_sitemaps("token", "https://example.com/")

    assert captured["method"] == "GET"
    assert "/webmasters/v3/sites/" in captured["url"]
    assert captured["url"].endswith("/sitemaps")
    assert entries[0]["path"] == "https://example.com/sitemap.xml"


@pytest.mark.asyncio
async def test_submit_sitemap_puts_encoded_feedpath(monkeypatch):
    client = GoogleSearchConsoleClient()
    captured = {}

    async def fake_no_content(method, url, access_token):
        captured.update({"method": method, "url": url})

    monkeypatch.setattr(client, "_request_no_content", fake_no_content)
    await client.submit_sitemap("token", "https://example.com/", "https://example.com/sitemap.xml")

    assert captured["method"] == "PUT"
    # Both site url and feed path are percent-encoded into the path.
    assert "https%3A%2F%2Fexample.com%2Fsitemap.xml" in captured["url"]


@pytest.mark.asyncio
async def test_delete_sitemap_uses_delete(monkeypatch):
    client = GoogleSearchConsoleClient()
    captured = {}

    async def fake_no_content(method, url, access_token):
        captured.update({"method": method})

    monkeypatch.setattr(client, "_request_no_content", fake_no_content)
    await client.delete_sitemap("token", "sc-domain:example.com", "https://example.com/sitemap.xml")
    assert captured["method"] == "DELETE"


# ---- detection ---------------------------------------------------------------


def test_robots_sitemap_directive_parsing():
    service = make_service()
    robots = "User-agent: *\nDisallow: /admin\nSitemap: https://example.com/sitemap.xml\nsitemap: https://example.com/news.xml\n"
    found = service._robots_sitemaps(robots)
    assert "https://example.com/sitemap.xml" in found
    assert "https://example.com/news.xml" in found


def test_looks_like_xml_detects_sitemaps():
    service = make_service()
    assert service._looks_like_xml('<?xml version="1.0"?><urlset></urlset>') is True
    assert service._looks_like_xml("<html><body>not a sitemap</body></html>") is False


# ---- parsing -----------------------------------------------------------------


def test_parse_urlset():
    service = make_service()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/</loc></url>"
        "<url><loc>https://example.com/about</loc></url>"
        "</urlset>"
    )
    parsed = service._parse_sitemap(xml)
    assert parsed.is_index is False
    assert parsed.urls == ["https://example.com/", "https://example.com/about"]


def test_parse_sitemap_index():
    service = make_service()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://example.com/sitemap-posts.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    parsed = service._parse_sitemap(xml)
    assert parsed.is_index is True
    assert parsed.child_sitemaps == ["https://example.com/sitemap-posts.xml"]


def test_parse_sitemap_invalid_xml_reports_error():
    service = make_service()
    parsed = service._parse_sitemap("<urlset><url><loc>oops")
    assert parsed.parse_error is not None


# ---- URL in property ---------------------------------------------------------


def test_url_in_property_domain_and_prefix():
    service = make_service()
    domain_prop = obj(site_url="sc-domain:example.com")
    prefix_prop = obj(site_url="https://example.com/shop/")

    assert service._url_in_property(domain_prop, "https://blog.example.com/x") is True
    assert service._url_in_property(domain_prop, "https://other.com/x") is False
    assert service._url_in_property(prefix_prop, "https://example.com/shop/item") is True
    assert service._url_in_property(prefix_prop, "https://example.com/other") is False


# ---- issue generation from crawl cross-reference -----------------------------


def test_validate_urls_generates_expected_issue_types():
    service = make_service()
    record = sitemap_record()
    prop = obj(site_url="https://example.com/")
    urls = [
        "https://example.com/ok",
        "https://example.com/ok",              # duplicate
        "ht!tp://broken",                      # invalid
        "http://example.com/insecure",         # non-https
        "https://other.com/outside",           # outside property
        "https://example.com/missing",         # 404
        "https://example.com/broken-server",   # 5xx
        "https://example.com/moved",           # redirect
        "https://example.com/hidden",          # noindex
        "https://example.com/dupe-canonical",  # non-canonical
    ]

    def key(u):
        return u.rstrip("/").lower()

    crawl_pages = {
        key("https://example.com/missing"): obj(status_code=404, redirect_count=0, noindex=False, canonical_url=None, canonical_url_normalized=None),
        key("https://example.com/broken-server"): obj(status_code=500, redirect_count=0, noindex=False, canonical_url=None, canonical_url_normalized=None),
        key("https://example.com/moved"): obj(status_code=301, redirect_count=1, noindex=False, canonical_url=None, canonical_url_normalized=None),
        key("https://example.com/hidden"): obj(status_code=200, redirect_count=0, noindex=True, canonical_url=None, canonical_url_normalized=None),
        key("https://example.com/dupe-canonical"): obj(status_code=200, redirect_count=0, noindex=False, canonical_url="https://example.com/canonical-target", canonical_url_normalized="https://example.com/canonical-target"),
    }

    issues = service._validate_urls(record, urls, obj(domain="https://example.com"), crawl_pages, prop)
    types = {issue["issue_type"] for issue in issues}

    assert SitemapIssueType.duplicate_url in types
    assert SitemapIssueType.invalid_url in types
    assert SitemapIssueType.non_https_url in types
    assert SitemapIssueType.url_outside_property in types
    assert SitemapIssueType.url_not_found in types
    assert SitemapIssueType.url_server_error in types
    assert SitemapIssueType.url_redirects in types
    assert SitemapIssueType.url_noindex in types
    assert SitemapIssueType.url_non_canonical in types


def test_gsc_entry_field_mapping():
    """_upsert_from_gsc_entry should map GSC Sitemaps API fields into record values."""
    captured = {}

    class FakeRepo:
        async def upsert_sitemap(self, *, project_id, tenant_id, sitemap_url, values):
            captured.update(values)
            captured["sitemap_url"] = sitemap_url
            return sitemap_record(sitemap_url=sitemap_url, **{k: v for k, v in values.items() if k in {"is_submitted", "status", "source"}})

    service = make_service(repository=FakeRepo())
    entry = {
        "path": "https://example.com/sitemap.xml",
        "isPending": False,
        "isSitemapsIndex": True,
        "lastSubmitted": "2026-07-01T10:00:00.000Z",
        "lastDownloaded": "2026-07-02T10:00:00.000Z",
        "errors": "2",
        "warnings": "1",
        "contents": [{"type": "web", "submitted": "42", "indexed": "40"}],
    }

    import asyncio

    asyncio.run(service._upsert_from_gsc_entry(uuid4(), uuid4(), uuid4(), entry))
    assert captured["sitemap_url"] == "https://example.com/sitemap.xml"
    assert captured["is_submitted"] is True
    assert captured["is_sitemaps_index"] is True
    assert captured["errors_count"] == 2
    assert captured["warnings_count"] == 1
    assert captured["submitted_urls_count"] == 42
    assert captured["source"] == SitemapSource.gsc_api
    assert captured["status"] == SitemapStatus.error  # errors > 0


# ---- submit safety -----------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_rejects_url_outside_property(monkeypatch):
    service = make_service()

    async def fake_require_project(project_id, tenant_id):
        return obj(id=project_id, domain="https://example.com")

    async def fake_require_oauth(project_id, tenant_id):
        return obj(site_url="https://example.com/", source_type=GSCPropertySourceType.oauth, connection_id=uuid4()), obj(id=uuid4())

    monkeypatch.setattr(service, "_require_project", fake_require_project)
    monkeypatch.setattr(service, "_require_oauth_property", fake_require_oauth)

    with pytest.raises(SitemapServiceError):
        await service.submit(uuid4(), uuid4(), "https://not-my-domain.com/sitemap.xml")


@pytest.mark.asyncio
async def test_submit_persists_only_after_api_success(monkeypatch):
    calls = {"submitted": False, "persisted": None}
    prop = obj(id=uuid4(), site_url="https://example.com/", source_type=GSCPropertySourceType.oauth, connection_id=uuid4())

    class FakeGoogle(GoogleSearchConsoleClient):
        async def submit_sitemap(self, access_token, site_url, feedpath):
            calls["submitted"] = True

    class FakeRepo:
        async def upsert_sitemap(self, *, project_id, tenant_id, sitemap_url, values):
            calls["persisted"] = (sitemap_url, values)
            return sitemap_record(sitemap_url=sitemap_url, is_submitted=values.get("is_submitted", False))

    service = make_service(google_client=FakeGoogle(), repository=FakeRepo())

    async def fake_require_project(project_id, tenant_id):
        return obj(id=project_id, domain="https://example.com")

    async def fake_require_oauth(project_id, tenant_id):
        return prop, obj(id=uuid4())

    async def fake_token(connection):
        return "access-token"

    monkeypatch.setattr(service, "_require_project", fake_require_project)
    monkeypatch.setattr(service, "_require_oauth_property", fake_require_oauth)
    monkeypatch.setattr(service, "_access_token", fake_token)

    record = await service.submit(uuid4(), uuid4(), "example.com/sitemap.xml")
    assert calls["submitted"] is True
    assert calls["persisted"][0] == "https://example.com/sitemap.xml"
    assert calls["persisted"][1]["is_submitted"] is True
    assert record.is_submitted is True


@pytest.mark.asyncio
async def test_no_content_request_raises_clear_403(monkeypatch):
    """A 403 on sitemap write should surface a clear re-consent message."""
    client = GoogleSearchConsoleClient()

    class FakeResponse:
        status_code = 403

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.services.search_console.httpx.AsyncClient", FakeAsyncClient)
    with pytest.raises(SearchConsoleGoogleAPIError) as exc:
        await client._request_no_content("PUT", "https://example.com", "token")
    assert "403" in str(exc.value)

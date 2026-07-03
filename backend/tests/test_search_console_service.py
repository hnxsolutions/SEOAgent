from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.search_console import (
    GSCComparisonWindow,
    GSCConnectionStatus,
    GSCPropertySourceType,
    GSCPropertyType,
    GSCSyncJobStatus,
    GSCSyncType,
    SearchConsoleImportStatus,
    SearchConsoleOpportunityType,
    SearchConsolePeriod,
    SearchConsoleSourceType,
)
from app.services.search_console import (
    GoogleSearchConsoleClient,
    SearchConsoleOpportunityAnalyzer,
    SearchConsoleGoogleAPIError,
    SearchConsoleOAuthError,
    SearchConsoleService,
    comparison_dates,
    normalize_gsc_api_rows,
    normalize_gsc_property_url,
    normalize_url,
    parse_search_console_csv,
)


class FakeDB:
    def __init__(self):
        self.rolled_back = False

    async def commit(self):
        return None

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None

    async def rollback(self):
        self.rolled_back = True


def make_manual_property(tenant_id, project_id, site_url="sc-domain:example.com", selected=True):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        connection_id=None,
        site_url=site_url,
        source_type=GSCPropertySourceType.manual,
        property_type=GSCPropertyType.domain if site_url.startswith("sc-domain:") else GSCPropertyType.url_prefix,
        permission_level=None,
        notes="CSV fallback",
        is_selected=selected,
        last_synced_at=None,
        created_at=now,
        updated_at=now,
    )


def make_oauth_property(tenant_id, project_id, connection_id, site_url="https://example.com/"):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        connection_id=connection_id,
        site_url=site_url,
        source_type=GSCPropertySourceType.oauth,
        property_type=GSCPropertyType.url_prefix,
        permission_level="siteOwner",
        notes=None,
        is_selected=True,
        last_synced_at=None,
        created_at=now,
        updated_at=now,
    )


def metric_row(
    tenant_id,
    project_id,
    import_id,
    query="local seo services",
    page_url="https://example.com/services/local-seo/",
    clicks=4,
    impressions=1000,
    ctr=0.004,
    position=12.0,
    period=SearchConsolePeriod.current,
):
    return SimpleNamespace(
        tenant_id=tenant_id,
        project_id=project_id,
        import_id=import_id,
        property_id=uuid4(),
        crawl_page_id=uuid4(),
        query=query,
        page_url=page_url,
        clicks=clicks,
        impressions=impressions,
        ctr=ctr,
        position=position,
        period=period,
    )


def test_oauth_start_url_generation_uses_gsc_scope(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://localhost/callback")

    client = GoogleSearchConsoleClient()
    url = client.build_authorization_url("state-123")

    assert "accounts.google.com" in url
    assert "client_id=client-id" in url
    assert "webmasters.readonly" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


@pytest.mark.asyncio
async def test_gsc_fetch_falls_back_when_search_appearance_dimension_is_rejected(monkeypatch):
    client = GoogleSearchConsoleClient()
    requested_dimensions = []

    async def fake_request_json(method, url, access_token, json=None):
        requested_dimensions.append(json["dimensions"])
        if "searchAppearance" in json["dimensions"]:
            raise SearchConsoleGoogleAPIError("Google Search Console request failed with status 400.")
        return {
            "rows": [
                {
                    "keys": ["seo", "https://example.com/", "2026-05-01", "usa", "DESKTOP"],
                    "clicks": 1,
                    "impressions": 10,
                    "ctr": 0.1,
                    "position": 3.2,
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    rows = await client.fetch_search_analytics(
        access_token="access-token",
        site_url="sc-domain:example.com",
        date_start=datetime(2026, 5, 1),
        date_end=datetime(2026, 5, 7),
        row_limit=100,
        dimensions=["query", "page", "date", "country", "device", "searchAppearance"],
    )

    assert rows[0]["_dimensions"] == ["query", "page", "date", "country", "device"]
    assert requested_dimensions[0][-1] == "searchAppearance"
    assert requested_dimensions[1] == ["query", "page", "date", "country", "device"]


@pytest.mark.asyncio
async def test_oauth_callback_encrypts_refresh_token(monkeypatch):
    tenant_id = uuid4()
    user_id = uuid4()
    stored = {}

    class FakeGoogleClient:
        credentials_configured = True

        async def exchange_code(self, code):
            assert code == "auth-code"
            return {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/webmasters.readonly",
                "token_type": "Bearer",
            }

    class FakeRepository:
        async def get_user_in_tenant(self, user_id_arg, tenant_id_arg):
            assert user_id_arg == user_id
            assert tenant_id_arg == tenant_id
            return SimpleNamespace(id=user_id, tenant_id=tenant_id, is_active=True)

        async def upsert_connection(self, **kwargs):
            stored.update(kwargs)
            return SimpleNamespace(
                id=uuid4(),
                tenant_id=kwargs["tenant_id"],
                user_id=kwargs["user_id"],
                status=GSCConnectionStatus.connected,
                scopes=kwargs["scopes"],
            )

    service = SearchConsoleService(FakeDB(), google_client=FakeGoogleClient())
    service.repository = FakeRepository()
    state = service._encode_oauth_state(tenant_id, user_id)

    response = await service.handle_oauth_callback("auth-code", state)

    assert response["tenant_id"] == tenant_id
    assert stored["tenant_id"] == tenant_id
    assert stored["user_id"] == user_id
    assert stored["encrypted_refresh_token"] != "refresh-token"
    assert decrypt_secret(stored["encrypted_refresh_token"]) == "refresh-token"


@pytest.mark.asyncio
async def test_oauth_callback_rejects_state_for_unknown_user_before_token_exchange():
    tenant_id = uuid4()
    user_id = uuid4()

    class FakeGoogleClient:
        credentials_configured = True

        async def exchange_code(self, code):
            raise AssertionError("Token exchange should not run for an invalid local OAuth state user")

    class FakeRepository:
        async def get_user_in_tenant(self, user_id_arg, tenant_id_arg):
            assert user_id_arg == user_id
            assert tenant_id_arg == tenant_id
            return None

    service = SearchConsoleService(FakeDB(), google_client=FakeGoogleClient())
    service.repository = FakeRepository()
    state = service._encode_oauth_state(tenant_id, user_id)

    with pytest.raises(SearchConsoleOAuthError, match="not active in this tenant"):
        await service.handle_oauth_callback("auth-code", state)


@pytest.mark.asyncio
async def test_property_listing_refreshes_from_mocked_gsc_client():
    tenant_id = uuid4()
    user_id = uuid4()
    connection_id = uuid4()
    encrypted = encrypt_secret("refresh-token")

    class FakeGoogleClient:
        credentials_configured = True

        async def refresh_access_token(self, refresh_token):
            assert refresh_token == "refresh-token"
            return {"access_token": "access-token", "expires_in": 3600}

        async def list_sites(self, access_token):
            assert access_token == "access-token"
            return [{"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"}]

    class FakeRepository:
        def __init__(self):
            self.properties = []

        async def list_properties(self, tenant_id_arg, project_id=None):
            return self.properties

        async def latest_connection(self, tenant_id_arg, user_id=None, include_failed=False):
            assert tenant_id_arg == tenant_id
            assert user_id == user_id
            return SimpleNamespace(
                id=connection_id,
                tenant_id=tenant_id,
                user_id=user_id,
                encrypted_refresh_token=encrypted,
                access_token_expires_at=None,
                status=GSCConnectionStatus.connected,
            )

        async def upsert_properties(self, connection, properties):
            self.properties = [
                SimpleNamespace(
                    id=uuid4(),
                    tenant_id=connection.tenant_id,
                    project_id=None,
                    connection_id=connection.id,
                    site_url=item["siteUrl"],
                    permission_level=item["permissionLevel"],
                    is_selected=False,
                    last_synced_at=None,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                for item in properties
            ]
            return self.properties

    repository = FakeRepository()
    service = SearchConsoleService(FakeDB(), google_client=FakeGoogleClient())
    service.repository = repository

    properties = await service.list_properties(tenant_id, user_id=user_id, refresh=True)

    assert properties[0].site_url == "https://example.com/"
    assert properties[0].permission_level == "siteOwner"


def test_gsc_data_normalization_and_csv_fallback_share_row_shape():
    tenant_id = uuid4()
    project_id = uuid4()
    import_id = uuid4()
    property_id = uuid4()
    start = datetime(2026, 5, 1)
    end = datetime(2026, 5, 7)

    api_rows = normalize_gsc_api_rows(
        [{"keys": ["Local SEO", "HTTPS://Example.com/Services/"], "clicks": 5, "impressions": 500, "ctr": 0.01, "position": 9.5}],
        tenant_id=tenant_id,
        project_id=project_id,
        import_id=import_id,
        property_id=property_id,
        date_start=start,
        date_end=end,
        comparison_window=GSCComparisonWindow.last_7_days,
        period=SearchConsolePeriod.current,
    )
    csv_rows = parse_search_console_csv(
        b"query,page,clicks,impressions,ctr,position,period\nLocal SEO,https://example.com/services,4,450,0.8%,11,previous\n",
        tenant_id=tenant_id,
        project_id=project_id,
        import_id=import_id,
        property_id=None,
        date_start=start,
        date_end=end,
        comparison_window=GSCComparisonWindow.last_7_days,
    )

    assert api_rows[0]["source_type"] == SearchConsoleSourceType.gsc_api
    assert csv_rows[0]["source_type"] == SearchConsoleSourceType.csv_upload
    assert csv_rows[0]["period"] == SearchConsolePeriod.previous
    assert csv_rows[0]["ctr"] == 0.008
    assert api_rows[0]["page_url"] == "https://example.com/Services"
    assert len(api_rows[0]["content_hash"]) == 64


def test_manual_property_url_normalization():
    assert normalize_gsc_property_url("example.com", GSCPropertyType.domain) == "sc-domain:example.com"
    assert normalize_gsc_property_url("https://Example.com/path/", GSCPropertyType.url_prefix) == "https://example.com/path"


@pytest.mark.asyncio
async def test_manual_property_creation_and_duplicate_update():
    tenant_id = uuid4()
    project_id = uuid4()

    class FakeRepository:
        def __init__(self):
            self.property = None

        async def get_project(self, project_id_arg, tenant_id_arg):
            assert project_id_arg == project_id
            assert tenant_id_arg == tenant_id
            return SimpleNamespace(id=project_id, tenant_id=tenant_id)

        async def upsert_manual_property(self, **kwargs):
            if self.property:
                self.property.notes = kwargs["notes"]
                self.property.property_type = kwargs["property_type"]
                self.property.site_url = kwargs["site_url"]
                return self.property
            self.property = make_manual_property(
                kwargs["tenant_id"],
                kwargs["project_id"],
                site_url=kwargs["site_url"],
                selected=True,
            )
            self.property.notes = kwargs["notes"]
            self.property.property_type = kwargs["property_type"]
            return self.property

    repository = FakeRepository()
    service = SearchConsoleService(FakeDB())
    service.repository = repository

    created = await service.register_manual_property(
        project_id=project_id,
        tenant_id=tenant_id,
        site_url="example.com",
        property_type=GSCPropertyType.domain,
        notes="Initial",
    )
    updated = await service.register_manual_property(
        project_id=project_id,
        tenant_id=tenant_id,
        site_url="sc-domain:example.com",
        property_type=GSCPropertyType.domain,
        notes="Updated",
    )

    assert created.id == updated.id
    assert updated.source_type == GSCPropertySourceType.manual
    assert updated.connection_id is None
    assert updated.is_selected is True
    assert updated.notes == "Updated"


@pytest.mark.asyncio
async def test_csv_import_uses_selected_manual_property():
    tenant_id = uuid4()
    project_id = uuid4()
    prop = make_manual_property(tenant_id, project_id)
    captured = {}
    start = datetime(2026, 5, 1)
    end = datetime(2026, 5, 7)

    class FakeRepository:
        async def get_project(self, project_id_arg, tenant_id_arg):
            return SimpleNamespace(id=project_id_arg, tenant_id=tenant_id_arg)

        async def selected_property(self, project_id_arg, tenant_id_arg):
            return prop

        async def create_import(self, **kwargs):
            captured["property_id"] = kwargs["property_id"]
            record = SimpleNamespace(
                id=uuid4(),
                tenant_id=kwargs["tenant_id"],
                project_id=kwargs["project_id"],
                property_id=kwargs["property_id"],
                source_type=kwargs["source_type"],
                status=None,
                rows_imported=0,
            )
            return record

        async def set_import_status(self, import_record, status, error_message=None):
            import_record.status = status
            import_record.error_message = error_message
            return import_record

        async def add_rows(self, rows):
            captured["rows"] = rows
            return len(rows)

        async def finish_import(self, import_record, rows_imported):
            import_record.rows_imported = rows_imported
            import_record.status = "completed"
            return import_record

        async def match_pages_by_urls(self, tenant_id_arg, project_id_arg, urls):
            return {}

    service = SearchConsoleService(FakeDB())
    service.repository = FakeRepository()

    record = await service.import_csv(
        tenant_id=tenant_id,
        project_id=project_id,
        filename="gsc.csv",
        content=b"query,page,clicks,impressions,ctr,position\nseo,https://example.com,1,10,10%,5\n",
        date_start=start,
        date_end=end,
    )

    assert record.property_id == prop.id
    assert captured["property_id"] == prop.id
    assert captured["rows"][0]["property_id"] == prop.id


@pytest.mark.asyncio
async def test_sync_request_on_manual_property_returns_failed_job():
    tenant_id = uuid4()
    project_id = uuid4()
    prop = make_manual_property(tenant_id, project_id)

    class FakeRepository:
        async def get_project(self, project_id_arg, tenant_id_arg):
            return SimpleNamespace(id=project_id_arg, tenant_id=tenant_id_arg)

        async def selected_property(self, project_id_arg, tenant_id_arg):
            return prop

        async def create_sync_job(self, **kwargs):
            return SimpleNamespace(
                id=uuid4(),
                tenant_id=kwargs["tenant_id"],
                project_id=kwargs["project_id"],
                connection_id=kwargs["connection_id"],
                property_id=kwargs["property_id"],
                sync_type=kwargs["sync_type"],
                date_start=kwargs["date_start"],
                date_end=kwargs["date_end"],
                comparison_window=kwargs["comparison_window"],
                status=kwargs["status"],
                rows_fetched=0,
                opportunities_created=0,
                opportunities_updated=0,
                error_message=kwargs["error_message"],
            )

    service = SearchConsoleService(FakeDB())
    service.repository = FakeRepository()

    job = await service.sync_project(
        tenant_id=tenant_id,
        project_id=project_id,
        sync_type=GSCSyncType.manual,
        comparison_window=GSCComparisonWindow.last_28_days,
    )

    assert job.status == GSCSyncJobStatus.failed
    assert job.connection_id is None
    assert "OAuth connection required" in job.error_message


@pytest.mark.asyncio
async def test_summary_includes_selected_manual_property():
    tenant_id = uuid4()
    project_id = uuid4()
    prop = make_manual_property(tenant_id, project_id)

    class FakeRepository:
        async def get_project(self, project_id_arg, tenant_id_arg):
            return SimpleNamespace(id=project_id_arg, tenant_id=tenant_id_arg)

        async def summary(self, project_id_arg, tenant_id_arg):
            return {
                "project_id": project_id_arg,
                "imports_count": 1,
                "rows_count": 10,
                "opportunities_count": 0,
                "opportunities_by_status": {},
                "opportunities_by_type": {},
                "latest_sync_job_id": None,
                "latest_sync_status": None,
                "selected_property": prop,
            }

        async def list_opportunities(self, **kwargs):
            return []

    service = SearchConsoleService(FakeDB())
    service.repository = FakeRepository()

    summary = await service.summary(project_id, tenant_id)

    assert summary["selected_property"].source_type == GSCPropertySourceType.manual
    assert summary["selected_property"].connection_id is None


def test_opportunity_detection_and_comparison_window_analysis():
    tenant_id = uuid4()
    project_id = uuid4()
    import_id = uuid4()
    rows = [
        metric_row(tenant_id, project_id, import_id, clicks=4, impressions=1000, ctr=0.004, position=12, period=SearchConsolePeriod.current),
        metric_row(tenant_id, project_id, import_id, clicks=20, impressions=800, ctr=0.025, position=7, period=SearchConsolePeriod.previous),
    ]
    analyzer = SearchConsoleOpportunityAnalyzer(high_impressions_threshold=100)
    opportunities = analyzer.analyze(rows)
    types = {item["opportunity_type"] for item in opportunities}

    assert SearchConsoleOpportunityType.high_impressions_low_ctr in types
    assert SearchConsoleOpportunityType.striking_distance_keyword in types
    assert SearchConsoleOpportunityType.ranking_drop in types
    assert SearchConsoleOpportunityType.ctr_drop in types
    assert SearchConsoleOpportunityType.click_decline in types

    current_start, current_end, previous_start, previous_end = comparison_dates(
        GSCComparisonWindow.last_7_days,
        today=date(2026, 5, 19),
    )
    assert current_start.date().isoformat() == "2026-05-12"
    assert current_end.date().isoformat() == "2026-05-18"
    assert previous_start.date().isoformat() == "2026-05-05"
    assert previous_end.date().isoformat() == "2026-05-11"


@pytest.mark.asyncio
async def test_duplicate_opportunities_update_instead_of_recreate():
    tenant_id = uuid4()
    project_id = uuid4()
    import_id = uuid4()
    rows = [
        metric_row(tenant_id, project_id, import_id, clicks=4, impressions=1000, ctr=0.004, position=12, period=SearchConsolePeriod.current),
        metric_row(tenant_id, project_id, import_id, clicks=20, impressions=800, ctr=0.025, position=7, period=SearchConsolePeriod.previous),
    ]

    class FakeRepository:
        def __init__(self):
            self.opportunities = {}

        async def get_import(self, import_id_arg, tenant_id_arg):
            return SimpleNamespace(id=import_id_arg, tenant_id=tenant_id_arg, project_id=project_id)

        async def rows_for_analysis(self, import_id_arg, tenant_id_arg):
            return rows

        async def signal_context(self, tenant_id_arg, project_id_arg, page_ids):
            return {}

        async def find_open_opportunity(self, tenant_id, project_id, query, page_url, opportunity_type):
            return self.opportunities.get((tenant_id, project_id, query, page_url, opportunity_type))

        async def create_opportunity(self, values):
            opportunity = SimpleNamespace(id=uuid4(), **values)
            self.opportunities[(values["tenant_id"], values["project_id"], values["query"], values["page_url"], values["opportunity_type"])] = opportunity
            return opportunity

        async def update_opportunity(self, opportunity, values):
            for key, value in values.items():
                setattr(opportunity, key, value)
            opportunity.updated_at = datetime.utcnow()
            return opportunity

    repository = FakeRepository()
    service = SearchConsoleService(FakeDB())
    service.repository = repository

    first = await service.analyze_import(import_id, tenant_id, commit=False)
    second = await service.analyze_import(import_id, tenant_id, commit=False)

    assert first.created > 0
    assert first.updated == 0
    assert second.created == 0
    assert second.updated == len(first.opportunities)
    assert len(repository.opportunities) == len(first.opportunities)


def test_url_normalization_removes_fragment_and_trailing_slash():
    assert normalize_url("HTTPS://Example.com/Services/#section") == "https://example.com/Services"


def test_gsc_api_normalization_supports_query_only_rows():
    tenant_id = uuid4()
    project_id = uuid4()
    import_id = uuid4()
    property_id = uuid4()
    rows = normalize_gsc_api_rows(
        [
            {
                "keys": ["Local SEO"],
                "_dimensions": ["query"],
                "clicks": 3,
                "impressions": 120,
                "ctr": 0.025,
                "position": 6.4,
            }
        ],
        tenant_id=tenant_id,
        project_id=project_id,
        import_id=import_id,
        property_id=property_id,
        date_start=datetime(2026, 5, 1),
        date_end=datetime(2026, 5, 7),
        comparison_window=GSCComparisonWindow.last_7_days,
        period=SearchConsolePeriod.current,
        site_url="https://example.com/",
    )

    assert rows[0]["query"] == "Local SEO"
    assert rows[0]["page_url"] == "https://example.com/"
    assert rows[0]["source_type"] == SearchConsoleSourceType.gsc_api


@pytest.mark.asyncio
async def test_monitor_settings_require_oauth_property_when_enabled():
    tenant_id = uuid4()
    project_id = uuid4()
    connection_id = uuid4()
    prop = make_oauth_property(tenant_id, project_id, connection_id)

    class FakeRepository:
        def __init__(self):
            self.setting = None

        async def get_project(self, project_id_arg, tenant_id_arg):
            return SimpleNamespace(id=project_id_arg, tenant_id=tenant_id_arg)

        async def get_monitor_setting(self, project_id_arg, tenant_id_arg):
            return self.setting

        async def selected_property(self, project_id_arg, tenant_id_arg):
            return prop

        async def get_property(self, property_id, tenant_id_arg):
            return prop if property_id == prop.id and tenant_id_arg == tenant_id else None

        async def upsert_monitor_setting(self, **kwargs):
            values = kwargs["values"]
            now = datetime.utcnow()
            self.setting = SimpleNamespace(
                id=uuid4(),
                tenant_id=kwargs["tenant_id"],
                project_id=kwargs["project_id"],
                property_id=kwargs["property_id"],
                created_at=now,
                updated_at=now,
                last_scheduled_at=None,
                **values,
            )
            return self.setting

    repository = FakeRepository()
    service = SearchConsoleService(FakeDB())
    service.repository = repository

    setting = await service.update_monitor_setting(
        project_id,
        tenant_id,
        {"enabled": True, "frequency_days": 2, "lookback_days": 7},
    )

    assert setting.enabled is True
    assert setting.frequency_days == 2
    assert setting.lookback_days == 7
    assert setting.next_sync_at is not None


@pytest.mark.asyncio
async def test_due_monitor_sync_skips_duplicate_scheduled_job():
    tenant_id = uuid4()
    project_id = uuid4()
    property_id = uuid4()
    now = datetime(2026, 7, 3, 9, 0, 0)
    setting = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        property_id=property_id,
        enabled=True,
        frequency_days=1,
        lookback_days=7,
        next_sync_at=now,
    )

    class FakeRepository:
        def __init__(self):
            self.created_jobs = 0
            self.updated_schedule = None

        async def due_monitor_settings(self, now, tenant_id=None, limit=50):
            return [setting]

        async def get_project(self, project_id_arg, tenant_id_arg):
            return SimpleNamespace(id=project_id_arg, tenant_id=tenant_id_arg)

        async def get_property(self, property_id_arg, tenant_id_arg):
            return make_oauth_property(tenant_id_arg, project_id, uuid4())

        async def scheduled_job_exists(self, **kwargs):
            return True

        async def create_sync_job(self, **kwargs):
            self.created_jobs += 1

        async def update_monitor_schedule(self, setting_arg, last_scheduled_at, next_sync_at):
            self.updated_schedule = (last_scheduled_at, next_sync_at)
            return setting_arg

    repository = FakeRepository()
    service = SearchConsoleService(FakeDB())
    service.repository = repository

    result = await service.run_due_monitor_syncs(tenant_id=tenant_id, now=now)

    assert result["due_count"] == 1
    assert result["jobs"] == []
    assert repository.created_jobs == 0
    assert repository.updated_schedule[0] == now


@pytest.mark.asyncio
async def test_run_sync_job_fetches_safe_search_analytics_groups():
    tenant_id = uuid4()
    project_id = uuid4()
    connection_id = uuid4()
    property_id = uuid4()
    import_id = uuid4()
    job_id = uuid4()
    prop = make_oauth_property(tenant_id, project_id, connection_id)
    prop.id = property_id
    connection = SimpleNamespace(
        id=connection_id,
        tenant_id=tenant_id,
        encrypted_refresh_token=encrypt_secret("refresh-token"),
        status=GSCConnectionStatus.connected,
        access_token_expires_at=None,
    )
    monitor = SimpleNamespace(
        sync_queries=True,
        sync_pages=True,
        sync_query_page_pairs=True,
        sync_country_device=True,
    )
    job = SimpleNamespace(
        id=job_id,
        tenant_id=tenant_id,
        project_id=project_id,
        connection_id=connection_id,
        property_id=property_id,
        sync_type=GSCSyncType.scheduled,
        date_start=datetime(2026, 6, 1),
        date_end=datetime(2026, 6, 7),
        comparison_window=GSCComparisonWindow.last_7_days,
        status=GSCSyncJobStatus.queued,
        rows_fetched=0,
        opportunities_created=0,
        opportunities_updated=0,
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    class FakeGoogleClient:
        credentials_configured = True

        def __init__(self):
            self.dimensions = []

        async def refresh_access_token(self, refresh_token):
            return {"access_token": "access-token", "expires_in": 3600}

        async def fetch_search_analytics(self, access_token, site_url, date_start, date_end, row_limit, dimensions=None):
            self.dimensions.append(tuple(dimensions or []))
            if dimensions == ["query"]:
                return [{"keys": ["local seo"], "_dimensions": dimensions, "clicks": 1, "impressions": 100, "ctr": 0.01, "position": 8}]
            if dimensions == ["page"]:
                return [{"keys": ["https://example.com/"], "_dimensions": dimensions, "clicks": 2, "impressions": 120, "ctr": 0.016, "position": 7}]
            return [{"keys": ["local seo", "https://example.com/"], "_dimensions": dimensions, "clicks": 3, "impressions": 130, "ctr": 0.02, "position": 6}]

    class FakeRepository:
        def __init__(self):
            self.rows = []
            self.import_record = None

        async def get_sync_job(self, job_id_arg, tenant_id=None):
            return job if job_id_arg == job_id else None

        async def set_sync_job_status(self, job_arg, status, error_message=None):
            job_arg.status = status
            job_arg.error_message = error_message
            return job_arg

        async def get_property(self, property_id_arg, tenant_id_arg):
            return prop

        async def get_connection(self, connection_id_arg, tenant_id_arg):
            return connection

        async def get_monitor_setting(self, project_id_arg, tenant_id_arg):
            return monitor

        async def create_import(self, **kwargs):
            self.import_record = SimpleNamespace(id=import_id, status=None, rows_imported=0, **kwargs)
            return self.import_record

        async def get_import(self, import_id_arg, tenant_id_arg):
            return self.import_record if import_id_arg == import_id else None

        async def set_import_status(self, import_record, status, error_message=None):
            import_record.status = status
            import_record.error_message = error_message
            return import_record

        async def add_rows(self, rows):
            self.rows = rows
            return len(rows)

        async def finish_import(self, import_record, rows_imported):
            import_record.rows_imported = rows_imported
            import_record.status = SearchConsoleImportStatus.completed
            return import_record

        async def rows_for_analysis(self, import_id_arg, tenant_id_arg):
            return []

        async def signal_context(self, tenant_id_arg, project_id_arg, page_ids):
            return {}

        async def finish_sync_job(self, job_arg, import_id, rows_fetched, opportunities_created, opportunities_updated):
            job_arg.import_id = import_id
            job_arg.rows_fetched = rows_fetched
            job_arg.opportunities_created = opportunities_created
            job_arg.opportunities_updated = opportunities_updated
            job_arg.status = GSCSyncJobStatus.completed
            return job_arg

        async def match_pages_by_urls(self, tenant_id_arg, project_id_arg, urls):
            return {}

    google_client = FakeGoogleClient()
    repository = FakeRepository()
    service = SearchConsoleService(FakeDB(), google_client=google_client)
    service.repository = repository

    completed = await service.run_sync_job(job_id, tenant_id=tenant_id)

    assert completed.status == GSCSyncJobStatus.completed
    assert ("query",) in google_client.dimensions
    assert ("page",) in google_client.dimensions
    assert ("query", "page") in google_client.dimensions
    assert ("query", "page", "date") in google_client.dimensions
    assert ("query", "page", "device", "country") in google_client.dimensions
    assert repository.rows


@pytest.mark.asyncio
async def test_token_refresh_failure_marks_connection_expired():
    tenant_id = uuid4()
    connection = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        encrypted_refresh_token=encrypt_secret("refresh-token"),
        status=GSCConnectionStatus.connected,
        access_token_expires_at=None,
        updated_at=None,
    )

    class FakeGoogleClient:
        credentials_configured = True

        async def refresh_access_token(self, refresh_token):
            raise SearchConsoleOAuthError("invalid_grant")

    service = SearchConsoleService(FakeDB(), google_client=FakeGoogleClient())

    with pytest.raises(SearchConsoleOAuthError):
        await service._access_token(connection)

    assert connection.status == GSCConnectionStatus.expired

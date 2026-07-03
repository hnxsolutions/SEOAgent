from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import search_console as search_console_routes
from app.models.search_console import (
    GSCComparisonWindow,
    GSCConnectionStatus,
    GSCPropertySourceType,
    GSCPropertyType,
    GSCSyncJobStatus,
    GSCSyncType,
    SearchConsoleImportStatus,
    SearchConsoleOpportunityStatus,
    SearchConsoleOpportunityType,
    SearchConsolePeriod,
    SearchConsoleSourceType,
)


def make_property(tenant_id, project_id, connection_id, property_id=None):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=property_id or uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        connection_id=connection_id,
        site_url="https://example.com/",
        source_type=GSCPropertySourceType.oauth,
        property_type=GSCPropertyType.url_prefix,
        permission_level="siteOwner",
        notes=None,
        is_selected=True,
        last_synced_at=now,
        created_at=now,
        updated_at=now,
    )


def make_connection(tenant_id, user_id, connection_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=connection_id,
        tenant_id=tenant_id,
        user_id=user_id,
        provider="google",
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        status=GSCConnectionStatus.connected,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def make_monitor(tenant_id, project_id, property_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        property_id=property_id,
        enabled=True,
        frequency_days=1,
        lookback_days=28,
        sync_queries=True,
        sync_pages=True,
        sync_query_page_pairs=True,
        sync_country_device=True,
        last_scheduled_at=None,
        next_sync_at=now,
        created_at=now,
        updated_at=now,
    )


def make_sync_job(tenant_id, project_id, connection_id, property_id, import_id=None):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        connection_id=connection_id,
        property_id=property_id,
        import_id=import_id,
        sync_type=GSCSyncType.manual,
        date_start=now,
        date_end=now,
        comparison_window=GSCComparisonWindow.last_28_days,
        status=GSCSyncJobStatus.completed,
        rows_fetched=4,
        opportunities_created=2,
        opportunities_updated=1,
        error_message=None,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


def make_import(tenant_id, project_id, import_id=None):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=import_id or uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        property_id=None,
        source_type=SearchConsoleSourceType.csv_upload,
        status=SearchConsoleImportStatus.completed,
        filename="gsc.csv",
        date_start=now,
        date_end=now,
        comparison_window=GSCComparisonWindow.last_7_days,
        rows_imported=1,
        error_message=None,
        metadata_json={"mode": "csv_fallback"},
        created_at=now,
        updated_at=now,
    )


def make_row(tenant_id, project_id, import_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        import_id=import_id,
        property_id=None,
        crawl_page_id=None,
        query="local seo services",
        page_url="https://example.com/services",
        clicks=5,
        impressions=500,
        ctr=0.01,
        position=9.5,
        date_start=now,
        date_end=now,
        comparison_window=GSCComparisonWindow.last_7_days,
        period=SearchConsolePeriod.current,
        source_type=SearchConsoleSourceType.csv_upload,
        content_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )


def make_opportunity(tenant_id, project_id, import_id, opportunity_id=None, status=SearchConsoleOpportunityStatus.suggested):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=opportunity_id or uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        import_id=import_id,
        property_id=None,
        crawl_page_id=None,
        query="local seo services",
        page_url="https://example.com/services",
        opportunity_type=SearchConsoleOpportunityType.striking_distance_keyword,
        status=status,
        current_clicks=5,
        current_impressions=500,
        current_ctr=0.01,
        current_position=9.5,
        previous_clicks=2,
        previous_impressions=400,
        previous_ctr=0.005,
        previous_position=12.0,
        reason="Ranking opportunity.",
        recommended_action="Expand the page and add internal links.",
        priority_score=88,
        confidence_score=78,
        evidence={"source": "test"},
        created_at=now,
        updated_at=now,
        approved_at=None,
        rejected_at=None,
        completed_at=None,
    )


def test_search_console_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    connection_id = uuid4()
    property_id = uuid4()
    import_id = uuid4()
    opportunity_id = uuid4()
    prop = make_property(tenant_id, project_id, connection_id, property_id)
    connection = make_connection(tenant_id, user_id, connection_id)
    monitor = make_monitor(tenant_id, project_id, property_id)
    sync_job = make_sync_job(tenant_id, project_id, connection_id, property_id, import_id)
    import_record = make_import(tenant_id, project_id, import_id)
    row = make_row(tenant_id, project_id, import_id)
    opportunity = make_opportunity(tenant_id, project_id, import_id, opportunity_id)

    class FakeSearchConsoleService:
        def __init__(self, db):
            self.db = db

        def google_oauth_enabled(self):
            return True

        def build_oauth_start(self, tenant_id, user_id):
            return {
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?scope=webmasters.readonly",
                "state": "state-token",
                "expires_at": datetime.utcnow(),
                "scopes": ["https://www.googleapis.com/auth/webmasters.readonly"],
            }

        async def handle_oauth_callback(self, code, state):
            return {
                "connection_id": connection_id,
                "tenant_id": tenant_id,
                "status": GSCConnectionStatus.connected,
                "scopes": ["https://www.googleapis.com/auth/webmasters.readonly"],
            }

        async def list_connections(self, tenant_id):
            return [connection]

        async def disconnect_connection(self, tenant_id, connection_id):
            connection.status = GSCConnectionStatus.revoked
            return connection

        async def list_properties(self, **kwargs):
            return [prop]

        async def select_property(self, project_id, tenant_id, property_id):
            prop.project_id = project_id
            prop.id = property_id
            return prop

        async def selected_project_property(self, project_id, tenant_id):
            return {"selected_property": prop, "monitor_setting": monitor}

        async def get_monitor_setting(self, project_id, tenant_id):
            return monitor

        async def update_monitor_setting(self, project_id, tenant_id, values):
            for key, value in values.items():
                setattr(monitor, key, value)
            return monitor

        async def register_manual_property(self, project_id, tenant_id, site_url, property_type, notes=None):
            prop.project_id = project_id
            prop.connection_id = None
            prop.site_url = "sc-domain:example.com"
            prop.source_type = GSCPropertySourceType.manual
            prop.property_type = GSCPropertyType.domain
            prop.notes = notes
            prop.is_selected = True
            return prop

        async def sync_project(self, **kwargs):
            return sync_job

        async def list_sync_jobs(self, project_id, tenant_id, limit=100, offset=0):
            return [sync_job]

        async def run_due_monitor_syncs(self, tenant_id=None, limit=50):
            return {"due_count": 1, "jobs": [sync_job]}

        async def summary(self, project_id, tenant_id):
            return {
                "project_id": project_id,
                "imports_count": 1,
                "rows_count": 1,
                "opportunities_count": 1,
                "opportunities_by_status": {"suggested": 1},
                "opportunities_by_type": {"striking_distance_keyword": 1},
                "latest_sync_job_id": sync_job.id,
                "latest_sync_status": "completed",
                "top_opportunities": [opportunity],
            }

        async def import_csv(self, **kwargs):
            return import_record

        async def list_imports(self, tenant_id, project_id=None, limit=100, offset=0):
            return [import_record]

        async def get_import(self, import_id, tenant_id):
            import_record.id = import_id
            return import_record

        async def list_rows(self, import_id, tenant_id, period=None, limit=100, offset=0):
            row.import_id = import_id
            return [row]

        async def analyze_import(self, import_id, tenant_id):
            return SimpleNamespace(created=1, updated=1, opportunities=[opportunity, opportunity])

        async def list_opportunities(self, **kwargs):
            return [opportunity]

        async def update_opportunity_status(self, opportunity_id, tenant_id, status):
            return make_opportunity(tenant_id, project_id, import_id, opportunity_id=opportunity_id, status=status)

    monkeypatch.setattr(search_console_routes, "SearchConsoleService", FakeSearchConsoleService)

    app = FastAPI()
    app.include_router(search_console_routes.router, prefix="/search-console")
    app.dependency_overrides[search_console_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": user_id,
    }
    app.dependency_overrides[search_console_routes.get_db] = lambda: object()
    client = TestClient(app)

    start_response = client.post("/search-console/connections/google/start")
    assert start_response.status_code == 200
    assert "webmasters.readonly" in start_response.json()["authorization_url"]

    callback_response = client.get(
        "/search-console/connections/google/callback?code=abc&state=xyz",
        follow_redirects=False,
    )
    assert callback_response.status_code == 307

    callback_response = client.get("/search-console/connections/google/callback?code=abc&state=xyz&as_json=true")
    assert callback_response.status_code == 200
    assert callback_response.json()["connection_id"] == str(connection_id)

    connections_response = client.get("/search-console/connections")
    assert connections_response.status_code == 200
    assert connections_response.json()["connections"][0]["id"] == str(connection_id)

    disconnect_response = client.delete(f"/search-console/connections/{connection_id}")
    assert disconnect_response.status_code == 200
    assert disconnect_response.json()["status"] == "revoked"
    connection.status = GSCConnectionStatus.connected

    properties_response = client.get("/search-console/properties?refresh=true")
    assert properties_response.status_code == 200
    assert properties_response.json()["properties"][0]["site_url"] == "https://example.com/"

    select_response = client.post(
        f"/search-console/projects/{project_id}/property",
        json={"property_id": str(property_id)},
    )
    assert select_response.status_code == 200
    assert select_response.json()["is_selected"] is True

    select_alias_response = client.post(
        f"/search-console/projects/{project_id}/property/select",
        json={"property_id": str(property_id)},
    )
    assert select_alias_response.status_code == 200
    assert select_alias_response.json()["id"] == str(property_id)

    selected_response = client.get(f"/search-console/projects/{project_id}/property")
    assert selected_response.status_code == 200
    assert selected_response.json()["monitor_setting"]["enabled"] is True

    monitor_response = client.get(f"/search-console/projects/{project_id}/monitor")
    assert monitor_response.status_code == 200
    assert monitor_response.json()["frequency_days"] == 1

    update_monitor_response = client.put(
        f"/search-console/projects/{project_id}/monitor",
        json={"enabled": True, "frequency_days": 2, "lookback_days": 7},
    )
    assert update_monitor_response.status_code == 200
    assert update_monitor_response.json()["frequency_days"] == 2

    manual_response = client.post(
        f"/search-console/projects/{project_id}/property/manual",
        json={"site_url": "example.com", "property_type": "domain", "notes": "CSV fallback"},
    )
    assert manual_response.status_code == 201
    assert manual_response.json()["source_type"] == "manual"
    assert manual_response.json()["connection_id"] is None

    sync_response = client.post(
        f"/search-console/projects/{project_id}/sync",
        json={"comparison_window": "last_28_days", "sync_type": "manual"},
    )
    assert sync_response.status_code == 200
    assert sync_response.json()["opportunities_created"] == 2

    jobs_response = client.get(f"/search-console/projects/{project_id}/sync-jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["sync_jobs"][0]["rows_fetched"] == 4

    due_response = client.post("/search-console/monitor/run-due")
    assert due_response.status_code == 200
    assert due_response.json()["due_count"] == 1

    summary_response = client.get(f"/search-console/projects/{project_id}/summary")
    assert summary_response.status_code == 200
    assert summary_response.json()["opportunities_count"] == 1

    import_response = client.post(
        "/search-console/imports",
        data={"project_id": str(project_id), "date_start": "2026-05-01", "date_end": "2026-05-07"},
        files={"file": ("gsc.csv", b"query,page,clicks,impressions,ctr,position\nx,https://example.com,1,10,10%,5\n")},
    )
    assert import_response.status_code == 201
    assert import_response.json()["source_type"] == "csv_upload"

    imports_response = client.get("/search-console/imports")
    assert imports_response.status_code == 200
    assert imports_response.json()["imports"][0]["id"] == str(import_id)

    status_response = client.get(f"/search-console/imports/{import_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    rows_response = client.get(f"/search-console/imports/{import_id}/rows")
    assert rows_response.status_code == 200
    assert rows_response.json()["rows"][0]["query"] == "local seo services"

    analyze_response = client.post(f"/search-console/imports/{import_id}/analyze")
    assert analyze_response.status_code == 200
    assert analyze_response.json()["opportunities_updated"] == 1

    opportunities_response = client.get(f"/search-console/imports/{import_id}/opportunities")
    assert opportunities_response.status_code == 200
    assert opportunities_response.json()["opportunities"][0]["priority_score"] == 88

    approve_response = client.post(f"/search-console/opportunities/{opportunity_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    reject_response = client.post(f"/search-console/opportunities/{opportunity_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    completed_response = client.post(f"/search-console/opportunities/{opportunity_id}/mark-completed")
    assert completed_response.status_code == 200
    assert completed_response.json()["status"] == "completed"

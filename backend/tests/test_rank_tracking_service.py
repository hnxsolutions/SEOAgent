from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.search_console import SearchConsolePeriod, SearchConsoleSourceType
from app.services.rank_tracking import RankTrackingService
from app.services.search_console import normalize_gsc_api_rows, parse_search_console_csv


class FakeDB:
    pass


class FakeRankRepository:
    def __init__(self, tenant_id, project_id, rows):
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.rows = rows

    async def get_project(self, project_id, tenant_id):
        if project_id == self.project_id and tenant_id == self.tenant_id:
            return SimpleNamespace(id=project_id, tenant_id=tenant_id)
        return None

    async def list_rows(self, project_id, tenant_id, **kwargs):
        rows = [row for row in self.rows if row.project_id == project_id and row.tenant_id == tenant_id]
        if kwargs.get("device"):
            rows = [row for row in rows if row.device == kwargs["device"]]
        if kwargs.get("country"):
            rows = [row for row in rows if row.country == kwargs["country"]]
        return rows


def row(tenant_id, project_id, period, position, clicks=10, impressions=100, ctr=0.1):
    return SimpleNamespace(
        tenant_id=tenant_id,
        project_id=project_id,
        query="pcd pharma company in haryana",
        page_url="https://example.com/pcd-pharma-company-in-haryana",
        clicks=clicks,
        impressions=impressions,
        ctr=ctr,
        position=position,
        period=period,
        country="ind",
        device="desktop",
        search_appearance=None,
        date_start=datetime(2026, 5, 1),
        date_end=datetime(2026, 5, 7),
    )


def test_gsc_dimensions_normalization_and_csv_fallback_nulls():
    tenant_id = uuid4()
    project_id = uuid4()
    import_id = uuid4()
    property_id = uuid4()
    api_rows = [
        {
            "keys": [
                "pcd pharma",
                "https://example.com/page",
                "2026-05-01",
                "ind",
                "DESKTOP",
                "AMP_BLUE_LINK",
            ],
            "_dimensions": ["query", "page", "date", "country", "device", "searchAppearance"],
            "clicks": 4,
            "impressions": 40,
            "ctr": 0.1,
            "position": 8.9,
        }
    ]

    rows = normalize_gsc_api_rows(
        api_rows,
        tenant_id,
        project_id,
        import_id,
        property_id,
        datetime(2026, 5, 1),
        datetime(2026, 5, 7),
        None,
        SearchConsolePeriod.current,
    )

    assert rows[0]["country"] == "ind"
    assert rows[0]["device"] == "DESKTOP"
    assert rows[0]["search_appearance"] == "AMP_BLUE_LINK"
    assert rows[0]["date_start"] == datetime(2026, 5, 1)

    csv_rows = parse_search_console_csv(
        b"query,page,clicks,impressions,ctr,position\npcd,https://example.com,1,10,10%,5\n",
        tenant_id,
        project_id,
        import_id,
        property_id,
        datetime(2026, 5, 1),
        datetime(2026, 5, 7),
    )
    assert csv_rows[0]["country"] is None
    assert csv_rows[0]["device"] is None
    assert csv_rows[0]["search_appearance"] is None


@pytest.mark.asyncio
async def test_rank_tracking_aggregates_improved_dropped_and_low_ctr_rows():
    tenant_id = uuid4()
    project_id = uuid4()
    rows = [
        row(tenant_id, project_id, SearchConsolePeriod.previous, 14.2, clicks=3, impressions=120, ctr=0.025),
        row(tenant_id, project_id, SearchConsolePeriod.current, 8.9, clicks=12, impressions=160, ctr=0.075),
        SimpleNamespace(
            **{
                **row(tenant_id, project_id, SearchConsolePeriod.previous, 4.0).__dict__,
                "query": "wholesale medicine supplier",
            }
        ),
        SimpleNamespace(
            **{
                **row(tenant_id, project_id, SearchConsolePeriod.current, 9.0, clicks=1, impressions=300, ctr=0.003).__dict__,
                "query": "wholesale medicine supplier",
            }
        ),
    ]
    service = RankTrackingService(FakeDB())
    service.repository = FakeRankRepository(tenant_id, project_id, rows)

    rankings, _ = await service.rankings(project_id, tenant_id, movement="improved")
    low_ctr, _ = await service.rankings(project_id, tenant_id, movement="low_ctr")
    summary = await service.summary(project_id, tenant_id)

    assert rankings[0].current_position == 8.9
    assert rankings[0].previous_position == 14.2
    assert rankings[0].position_delta == -5.3
    assert any(row.query == "wholesale medicine supplier" for row in low_ctr)
    assert summary["improved_keywords"] == 1
    assert summary["dropped_keywords"] == 1
    assert summary["striking_distance_keywords"] == 2

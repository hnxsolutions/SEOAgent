from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import impact as impact_routes
from app.api.v1.routes import rank_tracking as rank_routes
from app.api.v1.routes import serp_snapshots as serp_routes
from app.models.impact import (
    SeoImpactDataSource,
    SeoImpactExperimentStatus,
    SeoImpactExperimentType,
    SeoImpactOutcome,
    SeoImpactSnapshotType,
    SeoImpactSourceType,
)
from app.models.serp import (
    SerpSnapshotAssetType,
    SerpSnapshotCaptureMode,
    SerpSnapshotDevice,
    SerpSnapshotSearchEngine,
    SerpSnapshotStatus,
)
from app.schemas.rank_tracking import RankTrackingRow


def test_measurement_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    experiment_id = uuid4()
    snapshot_id = uuid4()
    asset_id = uuid4()
    now = datetime.utcnow()

    rank_row = RankTrackingRow(
        query="pcd pharma company in haryana",
        page_url="https://example.com/pcd-pharma-company-in-haryana",
        current_clicks=12,
        current_impressions=160,
        current_ctr=0.075,
        current_position=8.9,
        previous_clicks=3,
        previous_impressions=120,
        previous_ctr=0.025,
        previous_position=14.2,
        position_delta=-5.3,
        clicks_delta=9,
        impressions_delta=40,
        ctr_delta=0.05,
    )
    experiment = SimpleNamespace(
        id=experiment_id,
        tenant_id=tenant_id,
        project_id=project_id,
        experiment_type=SeoImpactExperimentType.metadata_update,
        source_type=SeoImpactSourceType.manual,
        source_reference_id=None,
        target_page_url="https://example.com/page",
        target_query="pcd pharma",
        target_keywords=["pcd pharma"],
        baseline_start_date=now,
        baseline_end_date=now,
        action_date=None,
        review_start_date=None,
        review_end_date=None,
        review_after_days=14,
        status=SeoImpactExperimentStatus.baseline_pending,
        notes=None,
        created_at=now,
        updated_at=now,
    )
    impact_snapshot = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        experiment_id=experiment_id,
        snapshot_type=SeoImpactSnapshotType.baseline,
        date_start=now,
        date_end=now,
        query="pcd pharma",
        page_url="https://example.com/page",
        clicks=3,
        impressions=100,
        ctr=0.03,
        position=14.2,
        data_source=SeoImpactDataSource.gsc_api,
        created_at=now,
    )
    impact_result = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        experiment_id=experiment_id,
        clicks_delta=9,
        impressions_delta=60,
        ctr_delta=0.045,
        position_delta=-5.3,
        percentage_clicks_change=3.0,
        percentage_impressions_change=0.6,
        outcome=SeoImpactOutcome.improved,
        confidence_score=68,
        summary="Improved",
        created_at=now,
    )

    serp_payload = {
        "id": snapshot_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "keyword": "pcd pharma company in haryana",
        "target_url": None,
        "target_domain": "novakoshealthcare.com",
        "search_engine": SerpSnapshotSearchEngine.google,
        "country": "India",
        "city": None,
        "device": SerpSnapshotDevice.desktop,
        "language": None,
        "capture_mode": SerpSnapshotCaptureMode.manual,
        "observed_target_rank": 7,
        "status": SerpSnapshotStatus.captured,
        "captured_at": now,
        "notes": None,
        "results": [],
        "assets": [],
        "competitors_above_target": [],
        "previous_rank": None,
        "rank_delta": None,
    }
    asset = SimpleNamespace(
        id=asset_id,
        tenant_id=tenant_id,
        project_id=project_id,
        snapshot_id=snapshot_id,
        asset_type=SerpSnapshotAssetType.screenshot,
        file_path="C:/tmp/serp.png",
        original_filename="serp.png",
        mime_type="image/png",
        created_at=now,
    )

    class FakeRankService:
        def __init__(self, db):
            pass

        async def rankings(self, *args, **kwargs):
            return [rank_row], False

        async def movements(self, *args, **kwargs):
            return [rank_row], False

        async def pages(self, *args, **kwargs):
            return [], False

        async def keywords(self, *args, **kwargs):
            return [], False

        async def summary(self, project_id, tenant_id):
            return {
                "project_id": project_id,
                "total_keywords": 1,
                "total_pages": 1,
                "total_rows": 1,
                "improved_keywords": 1,
                "dropped_keywords": 0,
                "striking_distance_keywords": 1,
                "low_ctr_keywords": 0,
                "total_clicks": 12,
                "total_impressions": 160,
                "average_ctr": 0.075,
                "average_position": 8.9,
                "message": None,
                "top_movements": [rank_row],
            }

    class FakeImpactService:
        def __init__(self, db):
            pass

        async def create_experiment(self, tenant_id, payload):
            return experiment

        async def list_experiments(self, *args, **kwargs):
            return [experiment]

        async def get_experiment(self, *args, **kwargs):
            return experiment

        async def capture_baseline(self, *args, **kwargs):
            return impact_snapshot

        async def mark_action_applied(self, *args, **kwargs):
            experiment.status = SeoImpactExperimentStatus.monitoring
            return experiment

        async def evaluate(self, *args, **kwargs):
            return impact_result

        async def summary(self, project_id, tenant_id):
            return {"project_id": project_id, "total_experiments": 1, "by_status": {"monitoring": 1}, "by_outcome": {"improved": 1}, "ready_for_review": 0, "message": None}

    class FakeSerpService:
        def __init__(self, db):
            pass

        async def create_snapshot(self, *args, **kwargs):
            return serp_payload

        async def list_snapshots(self, *args, **kwargs):
            return [serp_payload]

        async def get_snapshot(self, *args, **kwargs):
            return serp_payload

        async def history(self, *args, **kwargs):
            return [serp_payload]

        async def summary(self, project_id, tenant_id):
            return {"project_id": project_id, "total_snapshots": 1, "keywords_tracked": 1, "latest_snapshots": [serp_payload]}

        async def add_screenshot(self, *args, **kwargs):
            return asset

    monkeypatch.setattr(rank_routes, "RankTrackingService", FakeRankService)
    monkeypatch.setattr(impact_routes, "SeoImpactService", FakeImpactService)
    monkeypatch.setattr(serp_routes, "SerpSnapshotService", FakeSerpService)

    app = FastAPI()
    app.include_router(rank_routes.router, prefix="/rank-tracking")
    app.include_router(impact_routes.router, prefix="/impact")
    app.include_router(serp_routes.router, prefix="/serp-snapshots")
    for module in [rank_routes, impact_routes, serp_routes]:
        app.dependency_overrides[module.get_current_user] = lambda: {"tenant_id": tenant_id, "user_id": uuid4()}
        app.dependency_overrides[module.get_db] = lambda: object()
    client = TestClient(app)

    assert client.get(f"/rank-tracking/projects/{project_id}/rankings").status_code == 200
    assert client.get(f"/rank-tracking/projects/{project_id}/summary").json()["improved_keywords"] == 1
    assert client.post(
        "/impact/experiments",
        json={
            "project_id": str(project_id),
            "experiment_type": "metadata_update",
            "source_type": "manual",
            "target_page_url": "https://example.com/page",
            "baseline_start_date": now.isoformat(),
            "baseline_end_date": now.isoformat(),
        },
    ).status_code == 201
    assert client.post(f"/impact/experiments/{experiment_id}/capture-baseline").status_code == 200
    assert client.post(f"/impact/experiments/{experiment_id}/mark-action-applied", json={"action_date": now.isoformat()}).status_code == 200
    assert client.post(f"/impact/experiments/{experiment_id}/evaluate").json()["outcome"] == "improved"
    assert client.post(
        f"/serp-snapshots/projects/{project_id}/snapshots",
        json={
            "keyword": "pcd pharma company in haryana",
            "target_domain": "novakoshealthcare.com",
            "country": "India",
            "results": [{"position": 7, "title": "Novakos", "url": "https://www.novakoshealthcare.com"}],
        },
    ).status_code == 201
    assert client.get(f"/serp-snapshots/{snapshot_id}").status_code == 200
    upload = client.post(f"/serp-snapshots/{snapshot_id}/screenshot", files={"file": ("serp.png", b"fake", "image/png")})
    assert upload.status_code == 201

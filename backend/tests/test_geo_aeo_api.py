from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import geo_aeo as geo_routes


def make_run(crawl_id, tenant_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        crawl_id=crawl_id,
        project_id=None,
        tenant_id=tenant_id,
        status="pending",
        progress=0,
        model="qwen2.5:3b",
        total_pages=0,
        total_recommendations=0,
        average_geo_score=0,
        average_aeo_score=0,
        average_citation_readiness_score=0,
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def make_page_score(crawl_id, page_id, tenant_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        tenant_id=tenant_id,
        project_id=None,
        crawl_id=crawl_id,
        page_id=page_id,
        url="https://example.com/page",
        geo_score=71,
        aeo_score=68,
        citation_readiness_score=66,
        answer_block_score=60,
        entity_clarity_score=70,
        schema_readiness_score=75,
        trust_signal_score=62,
        topical_completeness_score=69,
        score_breakdown={"semantic_clarity_score": 72},
        extracted_entities=["Example"],
        extracted_claims=["Example offers useful information."],
        evidence={"word_count": 120},
        created_at=now,
        updated_at=now,
    )


def make_recommendation(crawl_id, page_id, tenant_id, recommendation_id=None, status="suggested"):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=recommendation_id or uuid4(),
        run_id=uuid4(),
        tenant_id=tenant_id,
        project_id=None,
        crawl_id=crawl_id,
        page_id=page_id,
        recommendation_type="answer_block",
        recommendation_text="Add a concise answer block near the top.",
        reason="Improve answer extractability.",
        priority_score=82,
        confidence_score=86,
        status=status,
        created_at=now,
        updated_at=now,
        approved_at=None,
        rejected_at=None,
        applied_at=None,
    )


def test_geo_aeo_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    crawl_id = uuid4()
    page_id = uuid4()
    recommendation_id = uuid4()
    run = make_run(crawl_id, tenant_id)
    page_score = make_page_score(crawl_id, page_id, tenant_id)
    recommendation = make_recommendation(crawl_id, page_id, tenant_id, recommendation_id)

    class FakeGeoAeoService:
        def __init__(self, db):
            self.db = db

        async def start_analysis(self, crawl_id, tenant_id):
            return run

        async def get_run_status(self, run_id, tenant_id):
            run.id = run_id
            run.status = "completed"
            run.progress = 100
            run.total_pages = 1
            run.total_recommendations = 1
            run.average_geo_score = 71
            run.average_aeo_score = 68
            run.average_citation_readiness_score = 66
            return run

        async def summary(self, crawl_id, tenant_id):
            return {
                "crawl_id": crawl_id,
                "project_id": None,
                "run_id": run.id,
                "status": "completed",
                "total_pages": 1,
                "total_recommendations": 1,
                "average_geo_score": 71,
                "average_aeo_score": 68,
                "average_citation_readiness_score": 66,
                "average_answer_block_score": 60,
                "average_entity_clarity_score": 70,
                "average_schema_readiness_score": 75,
                "average_trust_signal_score": 62,
                "average_topical_completeness_score": 69,
                "recommendations_by_status": {"suggested": 1},
                "recommendations_by_type": {"answer_block": 1},
            }

        async def get_page_score(self, page_id, tenant_id):
            page_score.page_id = page_id
            return page_score

        async def list_recommendations(self, **kwargs):
            return [recommendation]

        async def update_status(self, recommendation_id, tenant_id, status):
            return make_recommendation(
                crawl_id,
                page_id,
                tenant_id,
                recommendation_id=recommendation_id,
                status=status.value if hasattr(status, "value") else status,
            )

    async def no_background(run_id):
        return None

    monkeypatch.setattr(geo_routes, "GeoAeoService", FakeGeoAeoService)
    monkeypatch.setattr(geo_routes, "run_geo_aeo_background", no_background)

    app = FastAPI()
    app.include_router(geo_routes.router, prefix="/geo-aeo")
    app.dependency_overrides[geo_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[geo_routes.get_db] = lambda: object()
    client = TestClient(app)

    analyze_response = client.post(f"/geo-aeo/crawls/{crawl_id}/analyze")
    assert analyze_response.status_code == 202
    assert analyze_response.json()["model"] == "qwen2.5:3b"

    status_response = client.get(f"/geo-aeo/runs/{run.id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    summary_response = client.get(f"/geo-aeo/crawls/{crawl_id}/summary")
    assert summary_response.status_code == 200
    assert summary_response.json()["recommendations_by_type"] == {"answer_block": 1}

    score_response = client.get(f"/geo-aeo/pages/{page_id}/score")
    assert score_response.status_code == 200
    assert score_response.json()["geo_score"] == 71

    recommendations_response = client.get(f"/geo-aeo/crawls/{crawl_id}/recommendations")
    assert recommendations_response.status_code == 200
    assert recommendations_response.json()["recommendations"][0]["recommendation_type"] == "answer_block"

    approve_response = client.post(f"/geo-aeo/recommendations/{recommendation_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    reject_response = client.post(f"/geo-aeo/recommendations/{recommendation_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    applied_response = client.post(f"/geo-aeo/recommendations/{recommendation_id}/mark-applied")
    assert applied_response.status_code == 200
    assert applied_response.json()["status"] == "applied"

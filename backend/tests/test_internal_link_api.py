from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import internal_links as internal_link_routes


def recommendation_namespace(**overrides):
    now = datetime.utcnow()
    values = {
        "id": uuid4(),
        "crawl_job_id": uuid4(),
        "project_id": None,
        "tenant_id": uuid4(),
        "source_page_id": uuid4(),
        "source_url": "https://example.com/source",
        "target_page_id": uuid4(),
        "target_url": "https://example.com/target",
        "suggested_anchor_text": "Target",
        "suggested_context_snippet": "Source context",
        "reason": "Pages are semantically related.",
        "confidence_score": 88.0,
        "priority_score": 76.0,
        "status": "suggested",
        "recommendation_type": "semantic_related",
        "semantic_similarity": 0.91,
        "evidence": {"incoming_internal_links": 0},
        "created_at": now,
        "updated_at": now,
        "approved_at": None,
        "rejected_at": None,
        "applied_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_internal_link_api_smoke_and_status_flow(monkeypatch):
    tenant_id = uuid4()
    crawl_id = uuid4()
    page_id = uuid4()
    recommendation_id = uuid4()

    base_recommendation = recommendation_namespace(
        id=recommendation_id,
        crawl_job_id=crawl_id,
        tenant_id=tenant_id,
        source_page_id=page_id,
    )

    class FakeInternalLinkService:
        def __init__(self, db):
            self.db = db

        async def generate_for_crawl(self, crawl_job_id, tenant_id, limit=100):
            return {
                "crawl_id": crawl_job_id,
                "created_count": 1,
                "recommendations": [base_recommendation],
            }

        async def list_recommendations(self, **kwargs):
            return [base_recommendation]

        async def update_status(self, recommendation_id, tenant_id, status):
            return recommendation_namespace(
                id=recommendation_id,
                crawl_job_id=crawl_id,
                tenant_id=tenant_id,
                source_page_id=page_id,
                status=status.value if hasattr(status, "value") else status,
            )

        async def summary(self, crawl_job_id, tenant_id):
            return {
                "crawl_id": crawl_job_id,
                "project_id": None,
                "total_pages": 4,
                "orphan_pages": 1,
                "weakly_linked_pages": 2,
                "pages_with_too_few_internal_links": 1,
                "pages_with_excessive_internal_links": 0,
                "duplicate_anchor_text_risks": 0,
                "total_recommendations": 1,
                "average_priority_score": 76.0,
                "recommendations_by_status": {"suggested": 1},
                "recommendations_by_type": {"semantic_related": 1},
            }

    monkeypatch.setattr(internal_link_routes, "InternalLinkService", FakeInternalLinkService)

    app = FastAPI()
    app.include_router(internal_link_routes.router, prefix="/internal-links")
    app.dependency_overrides[internal_link_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[internal_link_routes.get_db] = lambda: object()
    client = TestClient(app)

    generate_response = client.post(f"/internal-links/crawls/{crawl_id}/generate")
    assert generate_response.status_code == 200
    assert generate_response.json()["created_count"] == 1

    crawl_list_response = client.get(f"/internal-links/crawls/{crawl_id}/recommendations")
    assert crawl_list_response.status_code == 200
    assert crawl_list_response.json()["recommendations"][0]["recommendation_type"] == "semantic_related"

    page_list_response = client.get(f"/internal-links/pages/{page_id}/recommendations")
    assert page_list_response.status_code == 200
    assert page_list_response.json()["recommendations"][0]["source_page_id"] == str(page_id)

    approve_response = client.post(f"/internal-links/recommendations/{recommendation_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    reject_response = client.post(f"/internal-links/recommendations/{recommendation_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    applied_response = client.post(f"/internal-links/recommendations/{recommendation_id}/mark-applied")
    assert applied_response.status_code == 200
    assert applied_response.json()["status"] == "applied"

    summary_response = client.get(f"/internal-links/crawls/{crawl_id}/summary")
    assert summary_response.status_code == 200
    assert summary_response.json()["recommendations_by_status"] == {"suggested": 1}

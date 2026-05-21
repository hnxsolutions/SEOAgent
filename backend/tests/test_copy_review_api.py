from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import copy_review as copy_routes
from app.models.copy_review import (
    SeoCopyApprovalReadiness,
    SeoCopyComplianceProfile,
    SeoCopyRevisionStatus,
    SeoCopySourceType,
)


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def make_review(tenant_id, project_id, **overrides):
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "project_id": project_id,
        "source_type": SeoCopySourceType.metadata,
        "source_reference_id": None,
        "page_url": "/pcd-pharma-company-in-haryana",
        "target_keyword": "pcd pharma company in haryana",
        "original_title": "Learn about pcd pharma company in haryana",
        "original_description": "Learn about pcd pharma company in haryana with clear service details and next steps.",
        "reviewed_title": "PCD Pharma Company in Haryana | Novakos Healthcare",
        "reviewed_description": "Explore Novakos Healthcare's B2B PCD pharma support in Haryana.",
        "quality_score": 92.0,
        "compliance_score": 100.0,
        "approval_readiness": SeoCopyApprovalReadiness.ready,
        "issues": [],
        "revision_notes": "Generic SEO copy was refined.",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_revision(tenant_id, project_id, review_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        review_id=review_id,
        source_type=SeoCopySourceType.metadata,
        source_reference_id=None,
        revised_title="PCD Pharma Company in Haryana | Novakos Healthcare",
        revised_description="Explore Novakos Healthcare's B2B PCD pharma support in Haryana.",
        reason="Generic SEO copy was refined.",
        compliance_notes=["No blocked compliance claims detected."],
        status=SeoCopyRevisionStatus.pending,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def test_copy_review_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    review = make_review(tenant_id, project_id)
    revision = make_revision(tenant_id, project_id, review.id)

    class FakeRepository:
        async def get_project(self, project_id_arg, tenant_id_arg):
            return SimpleNamespace(id=project_id_arg, tenant_id=tenant_id_arg)

        async def upsert_policy(self, **kwargs):
            return SimpleNamespace(
                id=uuid4(),
                tenant_id=kwargs["tenant_id"],
                project_id=kwargs["project_id"],
                compliance_profile=kwargs["compliance_profile"],
                blocked_phrases=kwargs.get("blocked_phrases"),
                allowed_topics=kwargs.get("allowed_topics"),
                notes=kwargs.get("notes"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

    class FakeService:
        def __init__(self, db):
            self.repository = FakeRepository()

        async def review_copy(self, **kwargs):
            review.project_id = kwargs["project_id"]
            review.tenant_id = kwargs["tenant_id"]
            return {"review": review, "revision": revision, "source_updated": False}

        async def review_repo_patch(self, *args, **kwargs):
            return {"review": review, "revision": revision, "source_updated": True}

        async def list_reviews(self, project_id_arg, tenant_id_arg, readiness=None, limit=100, offset=0):
            return [review]

        async def get_review(self, review_id_arg, tenant_id_arg):
            review.id = review_id_arg
            return review

        async def accept_revision(self, review_id_arg, tenant_id_arg):
            review.id = review_id_arg
            revision.status = SeoCopyRevisionStatus.accepted
            return {"review": review, "revision": revision, "source_updated": False}

        async def reject_revision(self, review_id_arg, tenant_id_arg):
            review.id = review_id_arg
            revision.status = SeoCopyRevisionStatus.rejected
            return {"review": review, "revision": revision, "source_updated": False}

    monkeypatch.setattr(copy_routes, "SeoCopyReviewService", FakeService)

    app = FastAPI()
    app.include_router(copy_routes.router, prefix="/copy-review")
    app.dependency_overrides[copy_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[copy_routes.get_db] = lambda: FakeDB()
    client = TestClient(app)

    create_response = client.post(
        "/copy-review/review",
        json={
            "project_id": str(project_id),
            "source_type": "metadata",
            "page_url": "/pcd-pharma-company-in-haryana",
            "target_keyword": "pcd pharma company in haryana",
            "original_title": "Learn about pcd pharma company in haryana",
            "original_description": "Learn about pcd pharma company in haryana with clear service details and next steps.",
            "compliance_profile": "pharma_b2b",
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["review"]["approval_readiness"] == "ready"
    assert create_response.json()["revision"]["status"] == "pending"

    policy_response = client.post(
        "/copy-review/policies",
        json={
            "project_id": str(project_id),
            "compliance_profile": "pharma_b2b",
            "blocked_phrases": ["cure"],
            "allowed_topics": ["verified buyer registration"],
            "notes": "Pharma B2B compliance.",
        },
    )
    assert policy_response.status_code == 201
    assert policy_response.json()["compliance_profile"] == SeoCopyComplianceProfile.pharma_b2b.value

    list_response = client.get(f"/copy-review/projects/{project_id}/reviews")
    assert list_response.status_code == 200
    assert list_response.json()["reviews"][0]["reviewed_title"].startswith("PCD Pharma")

    get_response = client.get(f"/copy-review/reviews/{review.id}")
    assert get_response.status_code == 200

    accept_response = client.post(f"/copy-review/reviews/{review.id}/accept-revision")
    assert accept_response.status_code == 200
    assert accept_response.json()["revision"]["status"] == "accepted"

    reject_response = client.post(f"/copy-review/reviews/{review.id}/reject-revision")
    assert reject_response.status_code == 200
    assert reject_response.json()["revision"]["status"] == "rejected"

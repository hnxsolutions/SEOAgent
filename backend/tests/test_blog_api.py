from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import blogs as blog_routes


def make_plan(plan_id, tenant_id, project_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=plan_id,
        tenant_id=tenant_id,
        project_id=project_id,
        title="Weekly blog plan",
        description="Support service pages.",
        target_site_url="https://example.com",
        status="draft",
        blogs_per_week=3,
        created_at=now,
        updated_at=now,
    )


def make_topic(plan_id, tenant_id, project_id, topic_id=None, status="suggested"):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=topic_id or uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        blog_plan_id=plan_id,
        target_keyword="local SEO landing pages",
        search_intent="commercial",
        title="Local SEO Landing Pages: What to Fix First",
        angle="Buyer-intent guide.",
        target_audience="Service business owners",
        target_landing_page_id=uuid4(),
        priority_score=88,
        status=status,
        reason="Supports a landing page.",
        created_at=now,
        updated_at=now,
        approved_at=None,
        rejected_at=None,
        drafted_at=None,
        published_at=None,
    )


def make_draft(topic_id, tenant_id, project_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        blog_topic_id=topic_id,
        title="Local SEO Landing Pages",
        slug="local-seo-landing-pages",
        meta_title="Local SEO Landing Pages",
        meta_description="Improve service landing pages with local SEO fixes.",
        outline={"h1": "Local SEO Landing Pages", "sections": []},
        draft_markdown="# Local SEO Landing Pages\n\nDraft body.",
        faq_json=[{"question": "What matters?", "answer": "Useful service details."}],
        schema_json={"@context": "https://schema.org", "@type": "BlogPosting"},
        internal_link_plan=[{"url": "https://example.com/service", "anchor": "service page", "reason": "Support page"}],
        knowledge_sources_used=[{"title": "Business profile"}],
        status="draft",
        created_at=now,
        updated_at=now,
        approved_at=None,
        rejected_at=None,
        published_at=None,
    )


def test_blog_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    plan_id = uuid4()
    topic_id = uuid4()
    plan = make_plan(plan_id, tenant_id, project_id)
    topic = make_topic(plan_id, tenant_id, project_id, topic_id)
    draft = make_draft(topic_id, tenant_id, project_id)

    class FakeBlogService:
        def __init__(self, db):
            self.db = db

        async def create_plan(self, **kwargs):
            plan.title = kwargs["title"]
            plan.project_id = kwargs["project_id"]
            plan.blogs_per_week = kwargs["blogs_per_week"]
            return plan

        async def list_plans(self, **kwargs):
            return [plan]

        async def get_plan(self, plan_id, tenant_id):
            plan.id = plan_id
            return plan

        async def generate_topics(self, plan_id, tenant_id, count=None):
            topic.blog_plan_id = plan_id
            return [topic]

        async def list_topics(self, **kwargs):
            return [topic]

        async def update_topic_status(self, topic_id, tenant_id, status):
            return make_topic(plan_id, tenant_id, project_id, topic_id=topic_id, status=status.value)

        async def draft_topic(self, topic_id, tenant_id):
            draft.blog_topic_id = topic_id
            return draft

        async def get_draft(self, draft_id, tenant_id):
            draft.id = draft_id
            return draft

        async def list_drafts_for_plan(self, plan_id, tenant_id, limit=100, offset=0):
            return [draft]

    monkeypatch.setattr(blog_routes, "BlogService", FakeBlogService)

    app = FastAPI()
    app.include_router(blog_routes.router, prefix="/blogs")
    app.dependency_overrides[blog_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[blog_routes.get_db] = lambda: object()
    client = TestClient(app)

    create_response = client.post(
        "/blogs/plans",
        json={
            "title": "Weekly blog plan",
            "description": "Support service pages.",
            "target_site_url": "https://example.com",
            "project_id": str(project_id),
            "blogs_per_week": 3,
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["blogs_per_week"] == 3

    plans_response = client.get("/blogs/plans")
    assert plans_response.status_code == 200
    assert plans_response.json()["plans"][0]["title"] == "Weekly blog plan"

    plan_response = client.get(f"/blogs/plans/{plan_id}")
    assert plan_response.status_code == 200
    assert plan_response.json()["id"] == str(plan_id)

    generate_response = client.post(f"/blogs/plans/{plan_id}/topics/generate", json={"count": 3})
    assert generate_response.status_code == 200
    assert generate_response.json()["topics"][0]["target_keyword"] == "local SEO landing pages"

    topics_response = client.get(f"/blogs/plans/{plan_id}/topics")
    assert topics_response.status_code == 200
    assert topics_response.json()["topics"][0]["search_intent"] == "commercial"

    approve_response = client.post(f"/blogs/topics/{topic_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    reject_response = client.post(f"/blogs/topics/{topic_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    draft_response = client.post(f"/blogs/topics/{topic_id}/draft")
    assert draft_response.status_code == 201
    assert draft_response.json()["slug"] == "local-seo-landing-pages"

    draft_id = draft_response.json()["id"]
    get_draft_response = client.get(f"/blogs/drafts/{draft_id}")
    assert get_draft_response.status_code == 200
    assert get_draft_response.json()["outline"]["h1"] == "Local SEO Landing Pages"

    drafts_response = client.get(f"/blogs/plans/{plan_id}/drafts")
    assert drafts_response.status_code == 200
    assert drafts_response.json()["drafts"][0]["knowledge_sources_used"][0]["title"] == "Business profile"

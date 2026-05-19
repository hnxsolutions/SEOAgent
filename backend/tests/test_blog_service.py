from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.blog import BlogPlanStatus, BlogSearchIntent, BlogTopicStatus
from app.services.blogs import BlogService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


class FakeLLMService:
    def __init__(self):
        self.calls = 0

    async def generate(self, prompt, model=None, options=None):
        self.calls += 1
        if "JSON shape" in prompt and '"topics"' in prompt:
            return {
                "response": """
                Here is the plan:
                {
                  "topics": [
                    {
                      "target_keyword": "local SEO landing pages for plumbers",
                      "search_intent": "commercial",
                      "title": "Local SEO Landing Pages for Plumbers: What to Fix First",
                      "angle": "Buyer-intent guide for service businesses.",
                      "target_audience": "Plumbing business owners",
                      "target_landing_page_id": "PAGE_ID",
                      "priority_score": 88,
                      "reason": "Supports a service landing page and uses knowledge base service context."
                    }
                  ]
                }
                """,
            }
        return {
            "response": """
            {
              "title": "Local SEO Landing Pages for Plumbers",
              "meta_title": "Local SEO Landing Pages for Plumbers",
              "meta_description": "Plan stronger plumber landing pages with technical SEO, FAQs, schema, and internal links.",
              "outline": {
                "h1": "Local SEO Landing Pages for Plumbers",
                "intro_angle": "Help service buyers understand what to improve first.",
                "sections": [{"h2": "What to fix first", "h3": ["Technical basics", "FAQs and proof"]}],
                "faq": [{"question": "What should a plumber landing page include?", "answer": "It should include service details, FAQs, trust signals, and clear internal links."}],
                "recommended_schema_type": "BlogPosting"
              },
              "draft_markdown": "# Local SEO Landing Pages for Plumbers\\n\\nPlumbing companies need pages that explain services clearly and support quote requests.\\n\\n## What to fix first\\n\\nStart with crawl issues, service-specific FAQs, schema, and internal links.",
              "faq_json": [{"question": "What should a plumber landing page include?", "answer": "Service details, FAQs, trust signals, and internal links."}],
              "schema_json": {"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Local SEO Landing Pages for Plumbers"},
              "internal_link_plan": [{"url": "https://example.com/plumbing", "anchor": "plumbing services", "reason": "Primary landing page"}]
            }
            """,
        }


class FakeKnowledgeService:
    async def relevant_knowledge(self, **kwargs):
        return {
            "results": [
                {
                    "score": 0.91,
                    "source_id": str(uuid4()),
                    "document_id": str(uuid4()),
                    "title": "Business profile",
                    "source_type": "business_profile",
                    "text_preview": "We help plumbers improve local SEO landing pages.",
                    "chunk_text": "We help plumbers improve local SEO landing pages with technical fixes, FAQs, schema, and internal links.",
                }
            ]
        }


class FakeBlogRepository:
    def __init__(self):
        self.tenant_id = uuid4()
        self.project_id = uuid4()
        self.plan_id = uuid4()
        self.page_id = uuid4()
        now = datetime.utcnow()
        self.plan = SimpleNamespace(
            id=self.plan_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            title="Weekly local SEO blog plan",
            description="Support home service pages.",
            target_site_url="https://example.com",
            status=BlogPlanStatus.draft,
            blogs_per_week=3,
            created_at=now,
            updated_at=now,
        )
        self.page = SimpleNamespace(
            id=self.page_id,
            url="https://example.com/plumbing",
            title="Plumbing Services",
            h1=["Plumbing Services"],
            word_count=250,
            internal_links=2,
            crawled_at=now,
        )
        self.topic = None
        self.draft = None

    async def create_plan(self, **kwargs):
        self.plan.title = kwargs["title"]
        self.plan.description = kwargs["description"]
        self.plan.target_site_url = kwargs["target_site_url"]
        self.plan.blogs_per_week = kwargs["blogs_per_week"]
        return self.plan

    async def list_plans(self, *args, **kwargs):
        return [self.plan]

    async def get_plan(self, plan_id, tenant_id):
        return self.plan if plan_id == self.plan_id and tenant_id == self.tenant_id else None

    async def set_plan_status(self, plan, status):
        plan.status = status
        return plan

    async def existing_topic_keywords(self, plan_id, tenant_id):
        return set()

    async def add_topics(self, records):
        values = list(records)[0]
        values["target_landing_page_id"] = self.page_id
        self.topic = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            approved_at=None,
            rejected_at=None,
            drafted_at=None,
            published_at=None,
            **values,
        )
        return 1

    async def list_topics(self, plan_id, tenant_id, status=None, limit=100, offset=0):
        return [self.topic] if self.topic else []

    async def get_topic(self, topic_id, tenant_id):
        if self.topic and self.topic.id == topic_id and tenant_id == self.tenant_id:
            return self.topic
        return None

    async def set_topic_status(self, topic, status):
        topic.status = status
        if status == BlogTopicStatus.drafted:
            topic.drafted_at = datetime.utcnow()
        return topic

    async def create_draft(self, values):
        self.draft = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            approved_at=None,
            rejected_at=None,
            published_at=None,
            **values,
        )
        return self.draft

    async def get_draft(self, draft_id, tenant_id):
        return self.draft if self.draft and self.draft.id == draft_id and tenant_id == self.tenant_id else None

    async def list_drafts_for_plan(self, plan_id, tenant_id, limit=100, offset=0):
        return [self.draft] if self.draft else []

    async def list_candidate_pages(self, plan, limit=50):
        return [self.page]

    async def list_audit_issues_for_pages(self, tenant_id, page_ids):
        return [SimpleNamespace(crawl_page_id=self.page_id, issue_type="thin_content")]

    async def list_geo_scores_for_pages(self, tenant_id, page_ids):
        return [SimpleNamespace(page_id=self.page_id, geo_score=55, aeo_score=52)]

    async def list_geo_recommendations_for_pages(self, tenant_id, page_ids):
        return []

    async def list_content_suggestions_for_pages(self, tenant_id, page_ids):
        return []

    async def list_internal_link_recommendations_for_pages(self, tenant_id, page_ids):
        return [
            SimpleNamespace(
                source_page_id=self.page_id,
                target_page_id=uuid4(),
                target_url="https://example.com/plumbing",
                suggested_anchor_text="plumbing services",
                reason="Support the service page.",
                priority_score=80,
            )
        ]

    async def list_semantic_content_for_pages(self, tenant_id, page_ids):
        return [SimpleNamespace(crawl_page_id=self.page_id)]


@pytest.mark.asyncio
async def test_blog_plan_generation_uses_mocked_llm_and_knowledge():
    repository = FakeBlogRepository()
    llm = FakeLLMService()
    service = BlogService(FakeDB(), llm_service=llm, knowledge_service=FakeKnowledgeService())
    service.repository = repository

    topics = await service.generate_topics(repository.plan_id, repository.tenant_id, count=1)

    assert repository.plan.status == BlogPlanStatus.active
    assert len(topics) == 1
    assert topics[0].target_keyword == "local SEO landing pages for plumbers"
    assert topics[0].search_intent == BlogSearchIntent.commercial
    assert topics[0].target_landing_page_id == repository.page_id


@pytest.mark.asyncio
async def test_blog_draft_generation_uses_knowledge_and_updates_topic_status():
    repository = FakeBlogRepository()
    service = BlogService(FakeDB(), llm_service=FakeLLMService(), knowledge_service=FakeKnowledgeService())
    service.repository = repository
    topics = await service.generate_topics(repository.plan_id, repository.tenant_id, count=1)
    topic = topics[0]
    topic.status = BlogTopicStatus.approved

    draft = await service.draft_topic(topic.id, repository.tenant_id)

    assert topic.status == BlogTopicStatus.drafted
    assert draft.slug == "local-seo-landing-pages-for-plumbers"
    assert draft.meta_title == "Local SEO Landing Pages for Plumbers"
    assert draft.outline["h1"] == "Local SEO Landing Pages for Plumbers"
    assert draft.internal_link_plan[0]["url"] == "https://example.com/plumbing"
    assert draft.knowledge_sources_used[0]["title"] == "Business profile"
    assert draft.draft_markdown.startswith("# Local SEO Landing Pages")


@pytest.mark.asyncio
async def test_blog_draft_requires_approved_topic():
    repository = FakeBlogRepository()
    service = BlogService(FakeDB(), llm_service=FakeLLMService(), knowledge_service=FakeKnowledgeService())
    service.repository = repository
    topic = (await service.generate_topics(repository.plan_id, repository.tenant_id, count=1))[0]

    with pytest.raises(ValueError, match="approved"):
        await service.draft_topic(topic.id, repository.tenant_id)

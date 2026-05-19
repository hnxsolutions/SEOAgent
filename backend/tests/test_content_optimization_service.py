from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest

from app.models.content_optimization import (
    ContentOptimizationRunStatus,
    ContentOptimizationSuggestionStatus,
    ContentOptimizationSuggestionType,
)
from app.services.content_optimization import ContentOptimizationService, META_MIN_LENGTH, TITLE_MIN_LENGTH


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


class FakeLLMService:
    async def generate(self, prompt, model=None, options=None):
        return {
            "model": model or "qwen2.5:3b",
            "done": True,
            "response": """
            Here is the JSON:
            {
              "seo_title": {"suggested_value": "Tiny", "reason": "Improve title.", "confidence_score": 91},
              "meta_description": {"suggested_value": "Short", "reason": "Improve meta.", "confidence_score": 90},
              "h1": {"suggested_value": "Better Local Page H1", "reason": "Use one H1.", "confidence_score": 88},
              "headings": {"suggested_value": ["Benefits", "How it works"], "reason": "Clarify sections.", "confidence_score": 82},
              "faq": {"suggested_value": [{"question": "What is this?", "answer": "A useful page."}], "reason": "Add FAQ.", "confidence_score": 80},
              "schema": {"suggested_value": {"@type": "WebPage", "name": "Useful page"}, "reason": "Add schema.", "confidence_score": 81},
              "content_refresh": {"suggested_value": ["Add examples"], "reason": "Refresh content.", "confidence_score": 78},
              "answer_block": {"suggested_value": "This page helps visitors quickly understand the topic and choose a useful next step.", "reason": "AEO readiness.", "confidence_score": 76},
              "internal_link_context": {"suggested_value": ["Link to the target page near related copy."], "reason": "Support internal linking.", "confidence_score": 74}
            }
            """,
        }


class FakeContentOptimizationRepository:
    def __init__(self):
        self.tenant_id = uuid4()
        self.project_id = uuid4()
        self.crawl_id = uuid4()
        self.page_id = uuid4()
        self.crawl = SimpleNamespace(id=self.crawl_id, tenant_id=self.tenant_id, project_id=self.project_id)
        self.page = SimpleNamespace(
            id=self.page_id,
            url="https://example.com/example-page",
            title="Tiny",
            meta_description="Short",
            h1=[],
            h2=[],
            h3=[],
            word_count=120,
            text_content="Example page text with enough detail for local optimization suggestions.",
            schema_markup=None,
            crawl_order=1,
            crawled_at=datetime.utcnow(),
        )
        self.run = SimpleNamespace(
            id=uuid4(),
            crawl_id=self.crawl_id,
            project_id=self.project_id,
            tenant_id=self.tenant_id,
            status=ContentOptimizationRunStatus.pending,
            progress=0,
            model="qwen2.5:3b",
            total_pages=0,
            total_suggestions=0,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.records = []
        self.existing_keys = set()

    async def get_crawl(self, crawl_id, tenant_id=None):
        if crawl_id == self.crawl_id and (tenant_id is None or tenant_id == self.tenant_id):
            return self.crawl
        return None

    async def list_crawl_pages(self, crawl_id):
        return [self.page] if crawl_id == self.crawl_id else []

    async def list_audit_issues(self, crawl_id, tenant_id):
        return [
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="title_too_short"),
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="missing_meta_description"),
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="missing_h1"),
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="missing_schema"),
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="thin_content"),
        ]

    async def list_page_scores(self, crawl_id, tenant_id):
        return [SimpleNamespace(crawl_page_id=self.page_id, score=42)]

    async def list_internal_link_recommendations(self, crawl_id, tenant_id):
        return [
            SimpleNamespace(
                source_page_id=self.page_id,
                target_page_id=uuid4(),
                source_url=self.page.url,
                target_url="https://example.com/target",
                suggested_anchor_text="Target",
                reason="Related page.",
            )
        ]

    async def create_run(self, crawl, model):
        return self.run

    async def get_run(self, run_id, tenant_id=None):
        return self.run if run_id == self.run.id else None

    async def set_run_status(self, run, status, error_message=None, progress=None):
        run.status = status
        run.error_message = error_message
        if progress is not None:
            run.progress = progress
        return run

    async def existing_suggestion_keys(self, crawl_id, tenant_id):
        return set(self.existing_keys)

    async def add_suggestions(self, records):
        records = list(records)
        self.records.extend(records)
        return len(records)

    async def finish_run(self, run, total_pages, total_suggestions):
        run.total_pages = total_pages
        run.total_suggestions = total_suggestions
        return run


@pytest.mark.asyncio
async def test_content_optimization_generates_validated_suggestions_with_mocked_llm():
    repository = FakeContentOptimizationRepository()
    service = ContentOptimizationService(FakeDB(), llm_service=FakeLLMService())
    service.repository = repository

    run = await service.execute_generation(repository.run.id)

    assert run.status == ContentOptimizationRunStatus.completed
    types = {record["suggestion_type"] for record in repository.records}
    assert ContentOptimizationSuggestionType.seo_title in types
    assert ContentOptimizationSuggestionType.meta_description in types
    assert ContentOptimizationSuggestionType.faq in types
    assert ContentOptimizationSuggestionType.schema in types
    assert ContentOptimizationSuggestionType.internal_link_context in types

    title = next(record for record in repository.records if record["suggestion_type"] == ContentOptimizationSuggestionType.seo_title)
    meta = next(record for record in repository.records if record["suggestion_type"] == ContentOptimizationSuggestionType.meta_description)
    faq = next(record for record in repository.records if record["suggestion_type"] == ContentOptimizationSuggestionType.faq)
    schema = next(record for record in repository.records if record["suggestion_type"] == ContentOptimizationSuggestionType.schema)

    assert len(title["suggested_value"]) >= TITLE_MIN_LENGTH
    assert len(meta["suggested_value"]) >= META_MIN_LENGTH
    assert json.loads(faq["suggested_value"])[0]["question"]
    assert json.loads(schema["suggested_value"])["@context"] == "https://schema.org"


@pytest.mark.asyncio
async def test_duplicate_suggestion_hashes_are_skipped():
    repository = FakeContentOptimizationRepository()
    service = ContentOptimizationService(FakeDB(), llm_service=FakeLLMService())
    service.repository = repository
    issue_types = {
        "title_too_short",
        "missing_meta_description",
        "missing_h1",
        "missing_schema",
        "thin_content",
    }
    title_hash = service._content_hash(
        repository.page,
        ContentOptimizationSuggestionType.seo_title,
        repository.page.title,
        issue_types,
    )
    repository.existing_keys.add((repository.page_id, ContentOptimizationSuggestionType.seo_title, title_hash))

    await service.execute_generation(repository.run.id)

    assert all(record["suggestion_type"] != ContentOptimizationSuggestionType.seo_title for record in repository.records)


def test_content_optimization_topic_skips_generic_slug_segments():
    service = ContentOptimizationService(FakeDB(), llm_service=FakeLLMService())
    page = SimpleNamespace(
        id=uuid4(),
        url="https://quotes.toscrape.com/tag/change/page/1/",
        title="Quotes to Scrape",
        h1=["Quotes to Scrape"],
    )

    assert service._topic(page) == "Change"

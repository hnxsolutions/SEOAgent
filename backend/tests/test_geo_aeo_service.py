from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.content_optimization import ContentOptimizationSuggestionType
from app.models.geo_aeo import (
    GeoAeoRecommendationStatus,
    GeoAeoRecommendationType,
    GeoAeoRunStatus,
)
from app.services.geo_aeo import GeoAeoService


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
            GEO/AEO extraction:
            {
              "entities": ["Example Service", "Example Company"],
              "factual_claims": [],
              "answer_block": "Example Service helps visitors understand what the page covers and where to go next."
            }
            """,
        }


class FakeGeoAeoRepository:
    def __init__(self):
        self.tenant_id = uuid4()
        self.project_id = uuid4()
        self.crawl_id = uuid4()
        self.page_id = uuid4()
        self.crawl = SimpleNamespace(id=self.crawl_id, tenant_id=self.tenant_id, project_id=self.project_id)
        self.page = SimpleNamespace(
            id=self.page_id,
            url="https://example.com/services/example-service",
            normalized_url="https://example.com/services/example-service",
            final_url=None,
            title="",
            meta_description="",
            h1=[],
            h2=[],
            h3=[],
            h4=[],
            h5=[],
            h6=[],
            word_count=55,
            text_content="Example service page. It is short and has limited support.",
            content_hash="abc123",
            internal_links=0,
            internal_link_urls=[],
            canonical_url=None,
            noindex=False,
            has_og_tags=False,
            schema_markup=None,
            schema_types=[],
            has_schema_markup=False,
            crawl_order=1,
            crawled_at=datetime.utcnow(),
        )
        self.run = SimpleNamespace(
            id=uuid4(),
            crawl_id=self.crawl_id,
            project_id=self.project_id,
            tenant_id=self.tenant_id,
            status=GeoAeoRunStatus.pending,
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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.page_score_records = []
        self.recommendation_records = []
        self.existing_keys = set()

    async def get_crawl(self, crawl_id, tenant_id=None):
        if crawl_id == self.crawl_id and (tenant_id is None or tenant_id == self.tenant_id):
            return self.crawl
        return None

    async def list_crawl_pages(self, crawl_id):
        return [self.page] if crawl_id == self.crawl_id else []

    async def list_audit_issues(self, crawl_id, tenant_id):
        return [
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="missing_title"),
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="missing_h1"),
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="missing_schema"),
            SimpleNamespace(crawl_page_id=self.page_id, issue_type="thin_content"),
        ]

    async def list_seo_page_scores(self, crawl_id, tenant_id):
        return [SimpleNamespace(crawl_page_id=self.page_id, score=38)]

    async def list_internal_links(self, crawl_id):
        return []

    async def list_internal_link_recommendations(self, crawl_id, tenant_id):
        return [
            SimpleNamespace(
                source_page_id=self.page_id,
                target_page_id=uuid4(),
                source_url=self.page.url,
                target_url="https://example.com/target",
                suggested_anchor_text="related guide",
            )
        ]

    async def list_content_suggestions(self, crawl_id, tenant_id):
        return [
            SimpleNamespace(
                page_id=self.page_id,
                suggestion_type=ContentOptimizationSuggestionType.schema,
                suggested_value='{"@type": "WebPage"}',
            )
        ]

    async def list_semantic_content(self, crawl_id, tenant_id):
        return []

    async def create_run(self, crawl, model):
        return self.run

    async def get_run(self, run_id, tenant_id=None):
        return self.run if run_id == self.run.id else None

    async def latest_run_for_crawl(self, crawl_id, tenant_id):
        return self.run

    async def set_run_status(self, run, status, error_message=None, progress=None):
        run.status = status
        run.error_message = error_message
        if progress is not None:
            run.progress = progress
        return run

    async def add_page_scores(self, records):
        records = list(records)
        self.page_score_records.extend(records)
        return len(records)

    async def existing_recommendation_keys(self, crawl_id, tenant_id):
        return set(self.existing_keys)

    async def add_recommendations(self, records):
        records = list(records)
        self.recommendation_records.extend(records)
        return len(records)

    async def finish_run(
        self,
        run,
        total_pages,
        total_recommendations,
        average_geo_score,
        average_aeo_score,
        average_citation_readiness_score,
    ):
        run.total_pages = total_pages
        run.total_recommendations = total_recommendations
        run.average_geo_score = average_geo_score
        run.average_aeo_score = average_aeo_score
        run.average_citation_readiness_score = average_citation_readiness_score
        return run


@pytest.mark.asyncio
async def test_geo_aeo_generates_scores_and_recommendations_with_mocked_llm():
    repository = FakeGeoAeoRepository()
    service = GeoAeoService(FakeDB(), llm_service=FakeLLMService())
    service.repository = repository

    run = await service.execute_analysis(repository.run.id)

    assert run.status == GeoAeoRunStatus.completed
    assert run.total_pages == 1
    assert repository.page_score_records
    score_record = repository.page_score_records[0]
    assert 0 <= score_record["geo_score"] <= 100
    assert 0 <= score_record["aeo_score"] <= 100
    assert "Example Service" in score_record["extracted_entities"]
    assert "Example Company" in score_record["extracted_entities"]
    assert "It" not in score_record["extracted_entities"]
    rec_types = {record["recommendation_type"] for record in repository.recommendation_records}
    assert GeoAeoRecommendationType.entity_clarity in rec_types
    assert GeoAeoRecommendationType.schema in rec_types
    assert GeoAeoRecommendationType.factual_claims in rec_types


@pytest.mark.asyncio
async def test_duplicate_geo_aeo_recommendations_are_skipped():
    repository = FakeGeoAeoRepository()
    service = GeoAeoService(FakeDB(), llm_service=FakeLLMService())
    service.repository = repository
    issue_types = {"missing_title", "missing_h1", "missing_schema", "thin_content"}
    duplicate_text = "Add WebPage or FAQPage JSON-LD that reflects the visible page topic and canonical URL."
    duplicate_hash = service._content_hash(
        repository.page,
        GeoAeoRecommendationType.schema,
        duplicate_text,
        issue_types,
    )
    repository.existing_keys.add((repository.page_id, GeoAeoRecommendationType.schema, duplicate_hash))

    await service.execute_analysis(repository.run.id)

    assert all(
        record["recommendation_type"] != GeoAeoRecommendationType.schema
        for record in repository.recommendation_records
    )


def test_geo_aeo_parser_handles_imperfect_json():
    service = GeoAeoService(FakeDB(), llm_service=FakeLLMService())
    parsed = service._parse_llm_json(
        'Here is JSON:\n{"entities":["Brand"],"factual_claims":["Brand offers services."],"answer_block":"Brand helps visitors."}'
    )

    assert parsed["entities"] == ["Brand"]


def test_geo_aeo_status_enum_values():
    assert GeoAeoRecommendationStatus.suggested.value == "suggested"

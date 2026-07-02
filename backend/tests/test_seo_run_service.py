from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.audit import SEOAuditStatus
from app.models.content_optimization import ContentOptimizationRunStatus
from app.models.crawl import CrawlStatus
from app.models.planner import SeoPlannerRunStatus
from app.models.semantic import SemanticIndexStatus
from app.models.seo_run import SeoRunStage, SeoRunStageStatus, SeoRunStatus
from app.services.local_llm import OllamaUnavailableError
from app.services.seo_run import SeoRunService


class FakeDB:
    def expire_all(self):
        return None

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    async def rollback(self):
        return None


class FakeSeoRunRepository:
    def __init__(self, project, run):
        self.project = project
        self.run = run

    async def get_project(self, project_id, tenant_id):
        if project_id == self.project.id and tenant_id == self.project.tenant_id:
            return self.project
        return None

    async def create_run(self, project, tenant_id):
        return self.run

    async def get_run(self, run_id, tenant_id=None):
        return self.run if run_id == self.run.id else None

    async def list_runs(self, project_id, tenant_id, limit=25, offset=0):
        return [self.run]

    async def set_status(self, run, status, current_stage=None, error_message=None):
        run.status = status
        if current_stage:
            run.current_stage = current_stage
        if error_message is not None:
            run.error_message = error_message
        if status == SeoRunStatus.running and not run.started_at:
            run.started_at = datetime.utcnow()
        if status in {SeoRunStatus.completed, SeoRunStatus.failed}:
            run.completed_at = datetime.utcnow()
        return run

    async def set_stage(self, run, stage, stage_status, error_message=None):
        run.current_stage = stage
        run.stage_statuses[stage.value] = stage_status.value
        if error_message:
            run.stage_errors[stage.value] = error_message
        return run

    async def attach_ids(self, run, **ids):
        for key, value in ids.items():
            if value is not None:
                setattr(run, key, value)
        return run


def make_run(project):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=project.tenant_id,
        project_id=project.id,
        status=SeoRunStatus.queued,
        current_stage=SeoRunStage.crawl,
        stage_statuses={
            "crawl": "pending",
            "audit": "pending",
            "semantic_index": "pending",
            "content_optimization": "pending",
            "planner": "pending",
        },
        stage_errors={},
        crawl_id=None,
        audit_id=None,
        semantic_index_run_id=None,
        content_optimization_run_id=None,
        planner_run_id=None,
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def test_project_url_uses_http_for_local_targets():
    service = SeoRunService(FakeDB())

    assert service._project_url("frontend:3000") == "http://frontend:3000"
    assert service._project_url("localhost:3000") == "http://localhost:3000"
    assert service._project_url("example.com") == "https://example.com"


@pytest.mark.asyncio
async def test_seo_run_continues_to_planner_when_content_ollama_unavailable():
    tenant_id = uuid4()
    project = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, domain="frontend:3000")
    run = make_run(project)
    crawl = SimpleNamespace(id=uuid4(), status=CrawlStatus.completed, error_message=None)
    audit = SimpleNamespace(id=uuid4(), status=SEOAuditStatus.completed, error_message=None)
    semantic = SimpleNamespace(id=uuid4(), status=SemanticIndexStatus.completed, error_message=None)
    content = SimpleNamespace(id=uuid4(), status=ContentOptimizationRunStatus.failed, error_message=None)
    planner = SimpleNamespace(id=uuid4(), status=SeoPlannerRunStatus.completed, error_message=None)

    class FakeCrawlService:
        def __init__(self, db):
            self.db = db

        async def create_crawl_job(self, **kwargs):
            return crawl

        async def enqueue_crawl_job(self, crawl_id, tenant_id=None):
            return crawl

        async def get_crawl_job(self, crawl_id, tenant_id=None):
            return crawl

    class FakeAuditService:
        def __init__(self, db):
            self.db = db

        async def start_audit(self, crawl_id, tenant_id):
            return audit

        async def execute_audit(self, audit_id):
            return audit

    class FakeSemanticService:
        def __init__(self, db):
            self.db = db

        async def start_index(self, crawl_id, tenant_id):
            return semantic

        async def execute_index(self, run_id):
            return semantic

    class FakeContentService:
        def __init__(self, db):
            self.db = db

        async def start_generation(self, crawl_id, tenant_id):
            return content

        async def execute_generation(self, run_id):
            raise OllamaUnavailableError("Ollama is not reachable.")

    class FakePlannerService:
        def __init__(self, db):
            self.db = db

        async def run_project(self, project_id, tenant_id, run_type=None):
            return planner

    service = SeoRunService(
        FakeDB(),
        poll_interval_seconds=0,
        crawl_service_factory=FakeCrawlService,
        audit_service_factory=FakeAuditService,
        semantic_service_factory=FakeSemanticService,
        content_service_factory=FakeContentService,
        planner_service_factory=FakePlannerService,
    )
    service.repository = FakeSeoRunRepository(project, run)

    result = await service.execute_run(run.id, tenant_id)

    assert result.status == SeoRunStatus.completed
    assert result.crawl_id == crawl.id
    assert result.audit_id == audit.id
    assert result.semantic_index_run_id == semantic.id
    assert result.content_optimization_run_id == content.id
    assert result.planner_run_id == planner.id
    assert result.stage_statuses["content_optimization"] == SeoRunStageStatus.skipped_or_failed.value
    assert result.stage_statuses["planner"] == SeoRunStageStatus.completed.value
    assert "not reachable" in result.stage_errors["content_optimization"]

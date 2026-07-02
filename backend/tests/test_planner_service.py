from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.audit import SEOIssueCategory, SEOIssueSeverity
from app.models.blog import BlogTopicStatus
from app.models.content_optimization import ContentOptimizationSuggestionType
from app.models.geo_aeo import GeoAeoRecommendationType
from app.models.internal_linking import InternalLinkRecommendationType
from app.models.planner import (
    SeoPlannerRunStatus,
    SeoPlannerRunType,
    SeoTaskStatus,
    SeoTaskType,
)
from app.models.repo_agent import SeoCodePatchRisk, SeoCodePatchStatus, SeoCodePatchType
from app.models.search_console import SearchConsoleOpportunityType
from app.services.planner import PlannerService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def obj(**kwargs):
    return SimpleNamespace(**kwargs)


class FakePlannerRepository:
    def __init__(self, tenant_id, project_id):
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.project = obj(id=project_id, tenant_id=tenant_id, domain="example.com")
        self.runs = []
        self.tasks = []
        self.reports = []
        self.crawl = obj(id=uuid4())
        self.audit = obj(id=uuid4())
        self.semantic_run = obj(id=uuid4())
        self.content_run = obj(id=uuid4())
        self.geo_run = obj(id=uuid4())
        self.gsc_sync = obj(id=uuid4())
        self.gsc_import = obj(id=uuid4())
        self.blog_plan = obj(id=uuid4())
        self.repo_scan = obj(id=uuid4())
        self.has_repo = True
        self.has_knowledge_value = True
        self.audit_issues = []
        self.gsc_opportunities = []
        self.keyword_baselines = []
        self.content_suggestions = []
        self.geo_recommendations = []
        self.internal_link_recommendations = []
        self.blog_topics = []
        self.repo_patches = []
        self.repo_issues = []

    async def get_project(self, project_id, tenant_id):
        return self.project if project_id == self.project_id and tenant_id == self.tenant_id else None

    async def create_run(self, tenant_id, project_id, run_type, target_week_start, target_week_end):
        run = obj(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            status=SeoPlannerRunStatus.queued,
            run_type=run_type,
            target_week_start=target_week_start,
            target_week_end=target_week_end,
            crawl_id=None,
            audit_id=None,
            semantic_run_id=None,
            internal_link_run_id=None,
            content_optimization_run_id=None,
            geo_aeo_run_id=None,
            gsc_sync_job_id=None,
            blog_plan_id=None,
            repo_scan_run_id=None,
            tasks_created=0,
            high_priority_tasks=0,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.runs.append(run)
        return run

    async def get_run(self, run_id, tenant_id=None):
        return next((run for run in self.runs if run.id == run_id), None)

    async def list_runs(self, project_id, tenant_id, limit=100, offset=0):
        return self.runs[offset : offset + limit]

    async def set_run_status(self, run, status, error_message=None):
        run.status = status
        run.error_message = error_message
        return run

    async def finish_run(self, run, tasks_created, high_priority_tasks, signal_ids):
        for key, value in signal_ids.items():
            setattr(run, key, value)
        run.tasks_created = tasks_created
        run.high_priority_tasks = high_priority_tasks
        run.status = SeoPlannerRunStatus.completed
        run.completed_at = datetime.utcnow()
        return run

    async def upsert_task(self, values):
        existing = await self.find_open_task(values)
        if existing:
            existing.description = values["description"]
            existing.priority_score = values["priority_score"]
            existing.priority = values["priority"]
            existing.planner_run_id = values["planner_run_id"]
            existing.updated_at = datetime.utcnow()
            return existing, False
        task = obj(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
        self.tasks.append(task)
        return task, True

    async def find_open_task(self, values):
        for task in self.tasks:
            if task.status not in {SeoTaskStatus.todo, SeoTaskStatus.in_progress, SeoTaskStatus.approved}:
                continue
            if (
                task.task_type == values["task_type"]
                and task.target_page_url == values.get("target_page_url")
                and task.target_keyword == values.get("target_keyword")
                and task.source_type == values["source_type"]
                and task.source_reference_id == values.get("source_reference_id")
            ):
                return task
        return None

    async def list_tasks(self, project_id, tenant_id, status=None, limit=100, offset=0):
        tasks = [task for task in self.tasks if not status or task.status == status]
        return tasks[offset : offset + limit]

    async def list_tasks_for_dedupe(self, project_id, tenant_id, limit=5000):
        return [
            task for task in self.tasks[:limit]
            if task.status in {SeoTaskStatus.todo, SeoTaskStatus.in_progress, SeoTaskStatus.approved}
        ]

    async def get_task(self, task_id, tenant_id):
        return next((task for task in self.tasks if task.id == task_id), None)

    async def set_task_status(self, task, status):
        task.status = status
        return task

    async def create_report(self, values):
        report = obj(id=uuid4(), created_at=datetime.utcnow(), **values)
        self.reports.append(report)
        return report

    async def get_report(self, run_id, tenant_id):
        return next((report for report in self.reports if report.planner_run_id == run_id), None)

    async def latest_crawl(self, project_id, tenant_id):
        return self.crawl

    async def latest_audit(self, crawl_id, project_id, tenant_id):
        return self.audit

    async def latest_semantic_run(self, crawl_id, project_id, tenant_id):
        return self.semantic_run

    async def latest_content_run(self, crawl_id, project_id, tenant_id):
        return self.content_run

    async def latest_geo_run(self, crawl_id, project_id, tenant_id):
        return self.geo_run

    async def latest_gsc_sync(self, project_id, tenant_id):
        return self.gsc_sync

    async def latest_search_console_import(self, project_id, tenant_id):
        return self.gsc_import

    async def latest_blog_plan(self, project_id, tenant_id):
        return self.blog_plan

    async def latest_repo_scan(self, project_id, tenant_id):
        return self.repo_scan

    async def has_repo_connection(self, project_id, tenant_id):
        return self.has_repo

    async def has_knowledge(self, project_id, tenant_id):
        return self.has_knowledge_value

    async def list_audit_issues(self, project_id, tenant_id, limit=200):
        return self.audit_issues

    async def list_gsc_opportunities(self, project_id, tenant_id, limit=200):
        return self.gsc_opportunities

    async def list_keyword_baselines(self, project_id, tenant_id, limit=500):
        return self.keyword_baselines

    async def list_content_suggestions(self, project_id, tenant_id, limit=200):
        return self.content_suggestions

    async def list_geo_recommendations(self, project_id, tenant_id, limit=200):
        return self.geo_recommendations

    async def list_internal_link_recommendations(self, project_id, tenant_id, limit=200):
        return self.internal_link_recommendations

    async def list_blog_topics(self, project_id, tenant_id, limit=200):
        return self.blog_topics

    async def list_repo_patches(self, project_id, tenant_id, limit=200):
        return self.repo_patches

    async def list_repo_issues(self, project_id, tenant_id, limit=200):
        return self.repo_issues


def seeded_repository():
    tenant_id = uuid4()
    project_id = uuid4()
    repo = FakePlannerRepository(tenant_id, project_id)
    page_url = "https://example.com/services"
    repo.gsc_opportunities = [
        obj(
            id=uuid4(),
            opportunity_type=SearchConsoleOpportunityType.high_impressions_low_ctr,
            query="seo services",
            page_url=page_url,
            recommended_action="Rewrite title and meta description.",
            reason="High impressions and low CTR.",
            priority_score=88,
        ),
        obj(
            id=uuid4(),
            opportunity_type=SearchConsoleOpportunityType.striking_distance_keyword,
            query="technical seo agency",
            page_url=page_url,
            recommended_action="Expand landing page sections.",
            reason="Position 8-20.",
            priority_score=74,
        ),
    ]
    repo.audit_issues = [
        obj(
            id=uuid4(),
            issue_type="missing_schema",
            title="Missing schema",
            message="No schema.",
            recommendation="Add JSON-LD.",
            severity=SEOIssueSeverity.high,
            category=SEOIssueCategory.schema,
            url=page_url,
            score_impact=15,
        )
    ]
    repo.content_suggestions = [
        obj(
            id=uuid4(),
            suggestion_type=ContentOptimizationSuggestionType.content_refresh,
            reason="Refresh stale sections.",
            priority_score=70,
            evidence={"url": page_url},
        )
    ]
    repo.geo_recommendations = [
        obj(
            id=uuid4(),
            recommendation_type=GeoAeoRecommendationType.answer_block,
            recommendation_text="Add a concise answer block.",
            reason="Weak answer extraction.",
            priority_score=72,
            evidence={"url": page_url},
        )
    ]
    repo.internal_link_recommendations = [
        obj(
            id=uuid4(),
            recommendation_type=InternalLinkRecommendationType.weak_page_support,
            target_url=page_url,
            reason="Target has weak inbound links.",
            priority_score=67,
        )
    ]
    repo.blog_topics = [
        obj(
            id=uuid4(),
            target_keyword="technical seo checklist",
            title="Technical SEO Checklist for Service Businesses",
            status=BlogTopicStatus.suggested,
            priority_score=62,
            reason="Supports services page.",
        ),
        obj(
            id=uuid4(),
            target_keyword="local seo audit",
            title="How to Run a Local SEO Audit",
            status=BlogTopicStatus.approved,
            priority_score=82,
            reason="Approved supporting topic.",
        ),
    ]
    repo.repo_patches = [
        obj(
            id=uuid4(),
            patch_type=SeoCodePatchType.metadata_update,
            file_path="app/services/page.tsx",
            explanation="Review metadata-only patch.",
            risk_level=SeoCodePatchRisk.low,
            status=SeoCodePatchStatus.proposed,
        )
    ]
    return repo, tenant_id, project_id


@pytest.mark.asyncio
async def test_planner_run_creation_and_task_generation_from_all_modules():
    repo, tenant_id, project_id = seeded_repository()
    service = PlannerService(FakeDB())
    service.repository = repo

    run = await service.run_project(project_id, tenant_id)
    task_types = {task.task_type for task in repo.tasks}

    assert run.status == SeoPlannerRunStatus.completed
    assert run.tasks_created == len(repo.tasks)
    assert SeoTaskType.metadata_rewrite in task_types
    assert SeoTaskType.content_refresh in task_types
    assert SeoTaskType.schema_addition in task_types
    assert SeoTaskType.geo_aeo_improvement in task_types
    assert SeoTaskType.internal_link in task_types
    assert SeoTaskType.blog_topic in task_types
    assert SeoTaskType.blog_draft in task_types
    assert SeoTaskType.repo_patch_review in task_types
    assert repo.reports[0].summary.startswith("Weekly SEO plan")


@pytest.mark.asyncio
async def test_planner_deduplicates_open_tasks_across_runs_and_updates_priority():
    repo, tenant_id, project_id = seeded_repository()
    service = PlannerService(FakeDB())
    service.repository = repo

    first_run = await service.run_project(project_id, tenant_id)
    original_count = len(repo.tasks)
    repo.gsc_opportunities[0].priority_score = 95
    repo.gsc_opportunities[0].recommended_action = "Urgently rewrite metadata."
    second_run = await service.run_project(project_id, tenant_id)

    assert first_run.tasks_created == original_count
    assert second_run.tasks_created == 0
    assert len(repo.tasks) == original_count
    metadata_task = next(task for task in repo.tasks if task.task_type == SeoTaskType.metadata_rewrite)
    assert metadata_task.priority_score == 95
    assert "Urgently" in metadata_task.description


@pytest.mark.asyncio
async def test_planner_task_approval_rejection_completion_flow():
    repo, tenant_id, project_id = seeded_repository()
    service = PlannerService(FakeDB())
    service.repository = repo
    await service.run_project(project_id, tenant_id)
    task = repo.tasks[0]

    assert (await service.update_task_status(task.id, tenant_id, SeoTaskStatus.approved)).status == SeoTaskStatus.approved
    assert (await service.update_task_status(task.id, tenant_id, SeoTaskStatus.in_progress)).status == SeoTaskStatus.in_progress
    assert (await service.update_task_status(task.id, tenant_id, SeoTaskStatus.completed)).status == SeoTaskStatus.completed
    assert (await service.update_task_status(task.id, tenant_id, SeoTaskStatus.rejected)).status == SeoTaskStatus.rejected


@pytest.mark.asyncio
async def test_planner_dedupe_preview_and_apply_skips_duplicates():
    repo, tenant_id, project_id = seeded_repository()
    service = PlannerService(FakeDB())
    service.repository = repo
    await service.run_project(project_id, tenant_id)
    task = repo.tasks[0]
    duplicate = obj(
        **{
            **task.__dict__,
            "id": uuid4(),
            "source_reference_id": uuid4(),
            "priority_score": max(float(task.priority_score or 0) - 5, 1),
            "updated_at": datetime.utcnow(),
        }
    )
    repo.tasks.append(duplicate)

    preview = await service.dedupe_preview(project_id, tenant_id)

    assert preview["dry_run"] is True
    assert preview["duplicate_group_count"] >= 1
    assert preview["duplicate_task_count"] >= 1
    assert duplicate.status == SeoTaskStatus.todo

    applied = await service.dedupe_apply(project_id, tenant_id)

    assert applied["dry_run"] is False
    assert applied["skipped_task_count"] >= 1
    assert duplicate.status == SeoTaskStatus.skipped


@pytest.mark.asyncio
async def test_planner_gracefully_handles_missing_gsc_repo_and_knowledge():
    tenant_id = uuid4()
    project_id = uuid4()
    repo = FakePlannerRepository(tenant_id, project_id)
    repo.crawl = None
    repo.audit = None
    repo.semantic_run = None
    repo.content_run = None
    repo.geo_run = None
    repo.gsc_sync = None
    repo.gsc_import = None
    repo.blog_plan = None
    repo.repo_scan = None
    repo.has_repo = False
    repo.has_knowledge_value = False
    service = PlannerService(FakeDB())
    service.repository = repo

    run = await service.run_project(project_id, tenant_id, run_type=SeoPlannerRunType.scheduled)
    report = repo.reports[0]

    assert run.status == SeoPlannerRunStatus.completed
    assert repo.tasks[0].task_type == SeoTaskType.manual_review
    assert any(risk["type"] == "gsc_missing" for risk in report.risks)
    assert any(risk["type"] == "repo_missing" for risk in report.risks)
    assert "Knowledge base content is empty" in report.summary


@pytest.mark.asyncio
async def test_planner_uses_project_context_for_manual_tasks():
    tenant_id = uuid4()
    project_id = uuid4()
    repo = FakePlannerRepository(tenant_id, project_id)
    repo.project = obj(
        id=project_id,
        tenant_id=tenant_id,
        domain="example.com",
        business_name="Acme Studio",
        industry="Home services",
        target_location="Phoenix",
        target_audience="Homeowners",
        primary_services=["kitchen remodeling"],
        target_keywords=["custom kitchen remodel"],
        competitor_urls=["https://competitor.example"],
        seo_goal="Increase consultation requests",
        brand_tone="Warm and expert",
    )
    repo.audit_issues = []
    repo.gsc_opportunities = []
    repo.content_suggestions = []
    repo.geo_recommendations = []
    repo.internal_link_recommendations = []
    repo.blog_topics = []
    repo.repo_patches = []
    repo.repo_issues = []
    service = PlannerService(FakeDB())
    service.repository = repo

    run = await service.run_project(project_id, tenant_id)
    titles = {task.title for task in repo.tasks}

    assert run.status == SeoPlannerRunStatus.completed
    assert "Review SEO goal alignment" in titles
    assert "Map target keyword: custom kitchen remodel" in titles
    assert all("competitor" not in task.description.lower() for task in repo.tasks)


@pytest.mark.asyncio
async def test_planner_creates_tasks_from_manual_keyword_baselines():
    tenant_id = uuid4()
    project_id = uuid4()
    repo = FakePlannerRepository(tenant_id, project_id)
    repo.audit_issues = []
    repo.gsc_opportunities = []
    repo.content_suggestions = []
    repo.geo_recommendations = []
    repo.internal_link_recommendations = []
    repo.blog_topics = []
    repo.repo_patches = []
    repo.repo_issues = []
    repo.keyword_baselines = [
        obj(
            id=uuid4(),
            keyword="local seo services",
            target_location="Phoenix",
            device="desktop",
            current_position=None,
            current_url=None,
        ),
        obj(
            id=uuid4(),
            keyword="technical seo agency",
            target_location="Phoenix",
            device="mobile",
            current_position=34,
            current_url="https://example.com/services",
        ),
        obj(
            id=uuid4(),
            keyword="seo audit checklist",
            target_location=None,
            device="desktop",
            current_position=8,
            current_url=None,
        ),
    ]
    service = PlannerService(FakeDB())
    service.repository = repo

    run = await service.run_project(project_id, tenant_id)
    titles = {task.title for task in repo.tasks}

    assert run.status == SeoPlannerRunStatus.completed
    assert "Manually check keyword position: local seo services" in titles
    assert "Improve content for keyword outside top 20: technical seo agency" in titles
    assert "Map keyword to target page: seo audit checklist" in titles
    assert any("do not use automated google scraping" in task.description.lower() for task in repo.tasks)
    assert repo.reports[0].search_console_summary["keyword_baseline_summary"]["total_keywords"] == 3

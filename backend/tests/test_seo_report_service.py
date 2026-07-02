from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.seo_report import SeoReportService


def make_run(tenant_id, project_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        status="completed",
        crawl_id=uuid4(),
        audit_id=uuid4(),
        semantic_index_run_id=uuid4(),
        content_optimization_run_id=uuid4(),
        planner_run_id=uuid4(),
        completed_at=datetime.utcnow(),
    )


def patch_report_sources(
    monkeypatch,
    service,
    run,
    *,
    content_suggestions=None,
    data_availability=None,
):
    project = SimpleNamespace(id=run.project_id, tenant_id=run.tenant_id, name="Acme", domain="example.com")
    crawl = SimpleNamespace(id=run.crawl_id, total_pages_crawled=5, url="https://example.com")
    audit = SimpleNamespace(
        id=run.audit_id,
        site_score=82,
        total_pages=5,
        total_issues=3,
        issue_counts_by_severity={"high": 1, "medium": 2},
        issue_counts_by_category={"metadata": 2, "technical": 1},
    )
    semantic = SimpleNamespace(id=run.semantic_index_run_id, indexed_vectors=12, total_vectors=12, total_pages=5)
    content_run = SimpleNamespace(id=run.content_optimization_run_id, total_suggestions=len(content_suggestions or []))
    planner_run = SimpleNamespace(id=run.planner_run_id, tasks_created=1)

    monkeypatch.setattr(service, "_get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "_get_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "_get_crawl", AsyncMock(return_value=crawl))
    monkeypatch.setattr(service, "_get_audit", AsyncMock(return_value=audit))
    monkeypatch.setattr(service, "_get_semantic_run", AsyncMock(return_value=semantic))
    monkeypatch.setattr(service, "_get_content_run", AsyncMock(return_value=content_run))
    monkeypatch.setattr(service, "_get_planner_run", AsyncMock(return_value=planner_run))
    monkeypatch.setattr(
        service,
        "_list_top_audit_issues",
        AsyncMock(
            return_value=[
                {
                    "id": str(uuid4()),
                    "title": "Missing meta description",
                    "message": "A page is missing a meta description.",
                    "recommendation": "Write a concise page-specific meta description.",
                    "severity": "high",
                    "category": "metadata",
                    "status": "open",
                    "url": "https://example.com/about",
                    "score_impact": 8,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        service,
        "_list_semantic_summaries",
        AsyncMock(
            return_value=[
                {
                    "id": str(uuid4()),
                    "url": "https://example.com/",
                    "content_type": "full_text",
                    "heading_context": "Home",
                    "text_preview": "Acme services and case studies.",
                }
            ]
        ),
    )
    monkeypatch.setattr(service, "_list_content_suggestions", AsyncMock(return_value=content_suggestions or []))
    monkeypatch.setattr(
        service,
        "_list_planner_tasks",
        AsyncMock(
            return_value=[
                {
                    "id": str(uuid4()),
                    "title": "Fix priority metadata",
                    "description": "Update missing descriptions on priority pages.",
                    "priority": "high",
                    "status": "todo",
                    "target_page_url": "https://example.com/about",
                    "due_date": None,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        service,
        "_data_availability",
        AsyncMock(
            return_value=data_availability
            or {
                "search_console": "Connected",
                "ranking_data": "Real Search Console data available",
                "serp": "Manual SERP snapshots available",
            }
        ),
    )


@pytest.mark.asyncio
async def test_completed_seo_run_returns_report(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    run = make_run(tenant_id, project_id)
    service = SeoReportService(db=object())
    patch_report_sources(
        monkeypatch,
        service,
        run,
        content_suggestions=[
            {
                "id": str(uuid4()),
                "suggestion_type": "meta_description",
                "suggested_value": "Better page summary",
                "reason": "The current description is missing.",
                "priority_score": 80,
                "confidence_score": 90,
                "status": "suggested",
                "page_url": "https://example.com/about",
            }
        ],
    )

    report = await service.generate_report(run.id, tenant_id)

    assert report is not None
    assert report.project_name == "Acme"
    assert report.website_url == "https://example.com"
    assert report.audit_score == 82
    assert report.crawl_pages_processed == 5
    assert report.semantic_vector_count == 12
    assert report.content_suggestions_count == 1
    assert report.planner_tasks_count == 1
    assert report.next_actions


@pytest.mark.asyncio
async def test_report_gracefully_handles_missing_content_suggestions(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    run = make_run(tenant_id, project_id)
    service = SeoReportService(db=object())
    patch_report_sources(monkeypatch, service, run, content_suggestions=[])

    report = await service.generate_report(run.id, tenant_id)

    assert report is not None
    assert report.content_suggestions_count == 0
    content_section = next(section for section in report.sections if section.key == "content_optimization")
    assert content_section.status == "no_data"
    assert "No content optimization suggestions" in content_section.summary


@pytest.mark.asyncio
async def test_report_gracefully_handles_missing_gsc_and_serp_data(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    run = make_run(tenant_id, project_id)
    service = SeoReportService(db=object())
    patch_report_sources(
        monkeypatch,
        service,
        run,
        data_availability={
            "search_console": "Not connected",
            "ranking_data": "No real ranking data available",
            "serp": "No real ranking data available",
        },
    )

    report = await service.generate_report(run.id, tenant_id)

    assert report is not None
    assert report.data_availability["search_console"] == "Not connected"
    assert report.data_availability["ranking_data"] == "No real ranking data available"
    assert report.data_availability["serp"] == "No real ranking data available"
    real_search_section = next(section for section in report.sections if section.key == "real_search_data")
    assert real_search_section.status == "not_connected"


@pytest.mark.asyncio
async def test_no_fake_ranking_data_appears(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    run = make_run(tenant_id, project_id)
    service = SeoReportService(db=object())
    patch_report_sources(
        monkeypatch,
        service,
        run,
        data_availability={
            "search_console": "Not connected",
            "ranking_data": "No real ranking data available",
            "serp": "No real ranking data available",
        },
    )

    report = await service.generate_report(run.id, tenant_id)
    payload = report.model_dump_json()

    assert "No real ranking data available" in payload
    assert "current_position" not in payload
    assert "observed_target_rank" not in payload
    assert "Position 1" not in payload

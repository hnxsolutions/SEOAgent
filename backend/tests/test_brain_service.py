"""Composition tests for SeoBrainService (DB collection mocked).

Live DB collection is exercised in the PR's end-to-end verification; here we
prove the ranking, health score, next-action and code-fixable aggregation.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.brain.classifier import BrainIssue
from app.services.seo_brain import SeoBrainService


def _make_service(monkeypatch, issues, *, pending=None, modules=None, run=None):
    service = SeoBrainService(db=object())
    project = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), name="Novako", domain="example.com")

    async def fake_project(project_id, tenant_id):
        return project

    async def fake_collect(project_id, tenant_id):
        return issues

    async def fake_latest_run(project_id, tenant_id):
        return run

    async def fake_pending(project_id, tenant_id):
        return pending or {"proposed_patches": 0, "open_pull_requests": 0}

    async def fake_modules(project_id, tenant_id):
        return modules or {"planner": {"open_tasks": 0}}

    monkeypatch.setattr(service, "_get_project", fake_project)
    monkeypatch.setattr(service, "_collect_issues", fake_collect)
    monkeypatch.setattr(service, "_latest_run", fake_latest_run)
    monkeypatch.setattr(service, "_pending_approvals", fake_pending)
    monkeypatch.setattr(service, "_module_summaries", fake_modules)
    return service, project


@pytest.mark.asyncio
async def test_master_plan_ranks_and_flags_code_fixable(monkeypatch):
    issues = [
        BrainIssue("audit", "thin_content", "medium", category="content", title="Thin content"),
        BrainIssue("robots", "disallow_all", "critical", title="Site blocked"),
        BrainIssue("audit", "meta_description", "high", category="metadata", title="Weak meta"),
    ]
    service, project = _make_service(monkeypatch, issues)
    plan = await service.get_master_plan(project.id, project.tenant_id)

    assert plan["total_issues"] == 3
    # Highest priority first, and it must be the critical site-wide block.
    assert plan["items"][0]["title"] == "Site blocked"
    assert plan["items"][0]["priority_score"] >= plan["items"][1]["priority_score"]
    # Thin content is not code-fixable; the other two are.
    assert plan["code_fixable_count"] == 2
    assert plan["top_priority"]["code_fixable"] is True


@pytest.mark.asyncio
async def test_master_plan_empty(monkeypatch):
    service, project = _make_service(monkeypatch, [])
    plan = await service.get_master_plan(project.id, project.tenant_id)
    assert plan["total_issues"] == 0
    assert plan["top_priority"] is None


@pytest.mark.asyncio
async def test_brain_state_health_and_next_action(monkeypatch):
    issues = [
        BrainIssue("robots", "disallow_all", "critical", title="Site blocked"),
        BrainIssue("audit", "meta_description", "high", category="metadata", title="Weak meta"),
    ]
    run = SimpleNamespace(id=uuid4(), status="completed", current_stage="completed", stage_statuses={}, audit_id=uuid4())
    service, project = _make_service(monkeypatch, issues, run=run)
    state = await service.get_brain_state(project.id, project.tenant_id)

    assert state["project_name"] == "Novako"
    assert 0 <= state["overall_health"] <= 100
    # Open critical issue must pull health below perfect.
    assert state["overall_health"] < 100
    assert state["current_run"]["status"] == "completed"
    # No pending PRs/patches -> next action addresses the top issue.
    assert "Site blocked" in state["next_action"]
    assert state["master_plan_total"] == 2


def test_enrich_patch_includes_quality_metadata_and_traceability():
    service = SeoBrainService(db=object())
    issue = SimpleNamespace(
        id=uuid4(),
        issue_type="missing_schema",
        title="Add FAQ schema",
        severity=SimpleNamespace(value="medium"),
        source_reference_type=SimpleNamespace(value="planner_task"),
        source_reference_id=uuid4(),
    )
    patch = SimpleNamespace(
        id=uuid4(),
        status=SimpleNamespace(value="proposed"),
        patch_type=SimpleNamespace(value="schema_addition"),
        file_path="app/page.tsx",
        explanation="Adds JSON-LD WebPage schema.",
        diff_text="--- a/app/page.tsx\n+++ b/app/page.tsx\n+<script type=...",
        risk_level=SimpleNamespace(value="low"),
        original_content_hash="abcdef1234567890",
        issue_id=issue.id,
    )
    enriched = service._enrich_patch(patch, issue)

    # Required patch-quality fields are all present.
    for key in (
        "reason", "seo_impact", "expected_ranking_gain", "expected_traffic_gain",
        "confidence", "affected_files", "diff", "rollback_strategy",
    ):
        assert key in enriched and enriched[key] not in (None, "")
    assert enriched["affected_files"] == ["app/page.tsx"]
    assert enriched["before_after_available"] is True
    # Traceable back to the originating (planner) issue.
    assert enriched["issue"]["source"] == "planner_task"
    assert enriched["issue"]["title"] == "Add FAQ schema"
    assert "roll back" in enriched["rollback_strategy"].lower()


def test_enrich_patch_without_issue_is_graceful():
    service = SeoBrainService(db=object())
    patch = SimpleNamespace(
        id=uuid4(),
        status=SimpleNamespace(value="proposed"),
        patch_type=SimpleNamespace(value="metadata_update"),
        file_path="app/layout.tsx",
        explanation="Metadata update.",
        diff_text="diff",
        risk_level=SimpleNamespace(value="low"),
        original_content_hash="0" * 64,
        issue_id=None,
    )
    enriched = service._enrich_patch(patch, None)
    assert enriched["issue"]["source"] == "repo_scan"
    assert enriched["confidence"] >= 0
    assert enriched["affected_files"] == ["app/layout.tsx"]


@pytest.mark.asyncio
async def test_brain_state_prioritizes_pending_pr_approval(monkeypatch):
    issues = [BrainIssue("audit", "meta_description", "high", title="Weak meta")]
    service, project = _make_service(
        monkeypatch, issues, pending={"proposed_patches": 3, "open_pull_requests": 1}
    )
    state = await service.get_brain_state(project.id, project.tenant_id)
    assert "pull request" in state["next_action"].lower()
    assert state["pending_approvals"]["open_pull_requests"] == 1

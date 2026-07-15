"""Control-flow tests for RobotsIntelligenceService (DB + network mocked).

Persistence and the summary delta are exercised live against Postgres in the
PR's end-to-end verification; here we prove the branching and URL logic.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.robots import RobotsAnalysisStatus, RobotsIssueType
from app.services.robots import RobotsIntelligenceService, _Fetch


def _service_with_capture(monkeypatch, fetch: _Fetch, *, domain="example.com"):
    service = RobotsIntelligenceService(db=object())
    project = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), domain=domain)
    captured = {}

    async def fake_get_project(project_id, tenant_id):
        return project

    async def fake_fetch(url):
        captured["url"] = url
        return fetch

    async def fake_persist(project_arg, robots_url, status, fetch_arg, *, sitemaps, groups, findings, error=None):
        captured["status"] = status
        captured["findings"] = findings
        captured["sitemaps"] = sitemaps
        captured["robots_url"] = robots_url
        return SimpleNamespace(id=uuid4(), status=status, issues_found=len(findings))

    monkeypatch.setattr(service, "_get_project", fake_get_project)
    monkeypatch.setattr(service, "_fetch", fake_fetch)
    monkeypatch.setattr(service, "_persist_run", fake_persist)
    return service, project, captured


def test_robots_url_normalizes_domain():
    assert RobotsIntelligenceService._robots_url("example.com") == "https://example.com/robots.txt"
    assert RobotsIntelligenceService._robots_url("https://www.example.com/path") == "https://www.example.com/robots.txt"
    assert RobotsIntelligenceService._robots_url("http://foo.test") == "http://foo.test/robots.txt"


@pytest.mark.asyncio
async def test_completed_analysis_runs_detectors(monkeypatch):
    body = "User-agent: *\nDisallow: /\n"  # site-wide block, no sitemap
    service, project, captured = _service_with_capture(
        monkeypatch, _Fetch(status_code=200, text=body, ok=True)
    )
    await service.analyze_project(project.id, project.tenant_id)
    assert captured["status"] == RobotsAnalysisStatus.completed
    assert captured["url"] == "https://example.com/robots.txt"
    types = {f.issue_type for f in captured["findings"]}
    assert RobotsIssueType.disallow_all in types
    assert RobotsIssueType.missing_sitemap_directive in types


@pytest.mark.asyncio
async def test_404_records_missing_robots(monkeypatch):
    service, project, captured = _service_with_capture(
        monkeypatch, _Fetch(status_code=404, text="", ok=False)
    )
    await service.analyze_project(project.id, project.tenant_id)
    assert captured["status"] == RobotsAnalysisStatus.missing
    types = {f.issue_type for f in captured["findings"]}
    assert RobotsIssueType.missing_robots in types


@pytest.mark.asyncio
async def test_connection_error_records_unreachable(monkeypatch):
    service, project, captured = _service_with_capture(
        monkeypatch, _Fetch(status_code=None, text="", ok=False, error="timeout")
    )
    await service.analyze_project(project.id, project.tenant_id)
    assert captured["status"] == RobotsAnalysisStatus.unreachable
    # No parsed findings when the file could not be fetched at all.
    assert captured["findings"] == []


@pytest.mark.asyncio
async def test_missing_project_raises(monkeypatch):
    service = RobotsIntelligenceService(db=object())

    async def none_project(project_id, tenant_id):
        return None

    monkeypatch.setattr(service, "_get_project", none_project)
    with pytest.raises(ValueError):
        await service.analyze_project(uuid4(), uuid4())

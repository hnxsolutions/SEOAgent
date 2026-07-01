from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.encryption import encrypt_secret
from app.models.indexing import (
    GSCFixValidationRunStatus,
    GSCIndexingIssueSeverity,
    GSCIndexingIssueStatus,
    GSCIndexingIssueType,
)
from app.models.planner import SeoTaskStatus, SeoTaskType
from app.models.search_console import GSCConnectionStatus
from app.services.indexing import (
    GSCIndexingIssueClassifier,
    IndexingService,
    normalize_url_inspection_result,
)
from app.services.search_console import GoogleSearchConsoleClient


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    async def flush(self):
        return None


def obj(**kwargs):
    return SimpleNamespace(**kwargs)


def inspection(verdict="FAIL", coverage_state="URL is not on Google", **overrides):
    values = {
        "verdict": verdict,
        "coverage_state": coverage_state,
        "indexing_state": None,
        "robots_txt_state": None,
        "page_fetch_state": None,
        "google_canonical": None,
        "user_canonical": None,
        "sitemap_urls": [],
        "rich_results_verdict": None,
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_url_inspection_api_client_uses_official_endpoint(monkeypatch):
    client = GoogleSearchConsoleClient()
    captured = {}

    async def fake_request_json(method, url, access_token, json=None):
        captured.update({"method": method, "url": url, "access_token": access_token, "json": json})
        return {
            "inspectionResult": {
                "inspectionResultLink": "https://search.google.com/search-console/inspect",
                "indexStatusResult": {"verdict": "PASS", "coverageState": "Submitted and indexed"},
            }
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    result = await client.inspect_url(
        access_token="access-token",
        site_url="sc-domain:example.com",
        inspection_url="https://example.com/",
    )

    assert "searchconsole.googleapis.com/v1/urlInspection/index:inspect" in captured["url"]
    assert captured["json"]["inspectionUrl"] == "https://example.com/"
    assert captured["json"]["siteUrl"] == "sc-domain:example.com"
    assert result["indexStatusResult"]["verdict"] == "PASS"


def test_indexed_url_classification_has_no_issue():
    classifier = GSCIndexingIssueClassifier()

    assert classifier.classify(inspection(verdict="PASS", coverage_state="Submitted and indexed")) is None


def test_not_indexed_classification():
    diagnosis = GSCIndexingIssueClassifier().classify(
        inspection(coverage_state="Crawled - currently not indexed")
    )

    assert diagnosis.issue_type == GSCIndexingIssueType.crawled_not_indexed


def test_canonical_mismatch_classification():
    diagnosis = GSCIndexingIssueClassifier().classify(
        inspection(
            coverage_state="Alternate page with proper canonical tag",
            google_canonical="https://example.com/canonical",
            user_canonical="https://example.com/page",
        )
    )

    assert diagnosis.issue_type == GSCIndexingIssueType.canonical_mismatch
    assert diagnosis.severity == GSCIndexingIssueSeverity.high


def test_robots_blocked_classification():
    diagnosis = GSCIndexingIssueClassifier().classify(
        inspection(robots_txt_state="DISALLOWED")
    )

    assert diagnosis.issue_type == GSCIndexingIssueType.blocked_by_robots
    assert diagnosis.severity == GSCIndexingIssueSeverity.critical


def test_page_with_redirect_classification():
    diagnosis = GSCIndexingIssueClassifier().classify(
        inspection(coverage_state="URL is not on Google"),
        {
            "crawl_page": obj(status_code=301, redirect_count=1, word_count=900),
            "url_in_sitemap": True,
            "internal_links_use_old_url": True,
        },
    )

    assert diagnosis.issue_type == GSCIndexingIssueType.page_with_redirect


def test_sitemap_missing_classification():
    diagnosis = GSCIndexingIssueClassifier().classify(
        inspection(coverage_state="URL is unknown to Google"),
        {"important_route": True, "url_in_sitemap": False, "inbound_internal_links": 2},
    )

    assert diagnosis.issue_type == GSCIndexingIssueType.sitemap_missing


def test_orphan_and_thin_content_enrichment_from_crawl_audit():
    classifier = GSCIndexingIssueClassifier()

    thin = classifier.classify(
        inspection(coverage_state="URL is unknown to Google"),
        {
            "crawl_page": obj(status_code=200, redirect_count=0, word_count=120),
            "url_in_sitemap": True,
            "important_route": True,
            "inbound_internal_links": 3,
        },
    )
    orphan = classifier.classify(
        inspection(coverage_state="URL is unknown to Google"),
        {
            "crawl_page": obj(status_code=200, redirect_count=0, word_count=900),
            "url_in_sitemap": True,
            "important_route": True,
            "inbound_internal_links": 0,
        },
    )

    assert thin.issue_type == GSCIndexingIssueType.thin_content
    assert orphan.issue_type == GSCIndexingIssueType.orphan_page


@pytest.mark.asyncio
async def test_fix_plan_creation_adds_planner_task_and_marks_issue_fix_proposed():
    tenant_id = uuid4()
    project_id = uuid4()
    issue_id = uuid4()
    issue = obj(
        id=issue_id,
        tenant_id=tenant_id,
        project_id=project_id,
        page_url="https://example.com/service",
        issue_type=GSCIndexingIssueType.thin_content,
        severity=GSCIndexingIssueSeverity.high,
        likely_cause="Thin content.",
        recommended_fix="Expand page content.",
        linked_patch_id=None,
        linked_repo_issue_id=None,
        status=GSCIndexingIssueStatus.open,
    )
    planner_run = obj(id=uuid4(), target_week_end=datetime.utcnow(), tasks_created=0, high_priority_tasks=0)
    task = None

    class FakeRepository:
        async def get_issue(self, issue_id_arg, tenant_id_arg):
            return issue

        async def get_project(self, project_id_arg, tenant_id_arg):
            return obj(id=project_id, tenant_id=tenant_id, name="Novakos Healthcare", domain="https://example.com")

        async def create_planner_run_for_fix(self, project_id_arg, tenant_id_arg):
            return planner_run

        async def upsert_fix_task(self, values):
            nonlocal task
            task = obj(id=uuid4(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
            return task, True

        async def latest_repo_scan(self, project_id_arg, tenant_id_arg):
            return None

        async def update_issue_links(self, issue_arg, **kwargs):
            issue_arg.status = kwargs["status"]
            return issue_arg

    service = IndexingService(FakeDB())
    service.repository = FakeRepository()

    response = await service.create_fix_plan(issue_id, tenant_id)

    assert response["issue"].status == GSCIndexingIssueStatus.fix_proposed
    assert response["planner_task"].task_type == SeoTaskType.content_refresh
    assert response["planner_task"].status == SeoTaskStatus.todo
    assert "pharma_b2b compliance review" in response["planner_task"].description


class FakeValidationRepository:
    def __init__(self, issue, raw):
        self.issue = issue
        self.raw = raw
        self.result = None
        self.run = None

    async def get_issue(self, issue_id, tenant_id):
        return self.issue

    async def create_validation_run(self, **kwargs):
        self.run = obj(
            id=uuid4(),
            status=GSCFixValidationRunStatus.queued,
            started_at=None,
            completed_at=None,
            created_at=datetime.utcnow(),
            **kwargs,
        )
        return self.run

    async def get_project(self, project_id, tenant_id):
        return obj(id=project_id, tenant_id=tenant_id, domain="https://example.com", name="Example")

    async def selected_property(self, project_id, tenant_id):
        return obj(id=uuid4(), connection_id=uuid4(), site_url="sc-domain:example.com")

    async def get_connection(self, connection_id, tenant_id):
        return obj(
            id=connection_id,
            tenant_id=tenant_id,
            encrypted_refresh_token=encrypt_secret("refresh-token"),
            status=GSCConnectionStatus.connected,
        )

    async def set_validation_run_status(self, run, status):
        run.status = status
        return run

    async def crawl_page_for_url(self, project_id, tenant_id, page_url):
        return None

    async def open_audit_issues_for_url(self, project_id, tenant_id, page_url, crawl_page_id=None):
        return []

    async def sitemap_entries_for_project(self, project):
        return []

    async def inbound_internal_link_count(self, project_id, tenant_id, page_url):
        return 1

    async def add_validation_result(self, values):
        self.result = obj(id=uuid4(), created_at=datetime.utcnow(), **values)
        return self.result

    async def set_issue_status(self, issue, status):
        issue.status = status
        return issue


class FakeInspectionClient:
    def __init__(self, raw):
        self.raw = raw

    async def inspect_url(self, **kwargs):
        return self.raw

    async def refresh_access_token(self, refresh_token):
        return {"access_token": "access-token", "expires_in": 3600}


@pytest.mark.asyncio
async def test_validation_run_marks_issue_fixed():
    tenant_id = uuid4()
    issue = obj(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=uuid4(),
        page_url="https://example.com/",
        issue_type=GSCIndexingIssueType.crawled_not_indexed,
        linked_patch_id=None,
    )
    raw = {"indexStatusResult": {"verdict": "PASS", "coverageState": "Submitted and indexed"}}
    service = IndexingService(FakeDB(), google_client=FakeInspectionClient(raw))
    service.repository = FakeValidationRepository(issue, raw)

    response = await service.validate_issue(issue.id, tenant_id)

    assert response["result"].fixed is True
    assert response["issue"].status == GSCIndexingIssueStatus.validated


@pytest.mark.asyncio
async def test_validation_run_marks_issue_still_failing():
    tenant_id = uuid4()
    issue = obj(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=uuid4(),
        page_url="https://example.com/",
        issue_type=GSCIndexingIssueType.blocked_by_robots,
        linked_patch_id=None,
    )
    raw = {"indexStatusResult": {"verdict": "FAIL", "coverageState": "Blocked by robots.txt", "robotsTxtState": "DISALLOWED"}}
    service = IndexingService(FakeDB(), google_client=FakeInspectionClient(raw))
    service.repository = FakeValidationRepository(issue, raw)

    response = await service.validate_issue(issue.id, tenant_id)

    assert response["result"].still_failing is True
    assert response["issue"].status == GSCIndexingIssueStatus.still_failing


def test_normalize_url_inspection_result_maps_api_fields():
    tenant_id = uuid4()
    project_id = uuid4()
    run_id = uuid4()
    raw = {
        "inspectionResultLink": "https://search.google.com/search-console/inspect",
        "indexStatusResult": {
            "verdict": "PASS",
            "coverageState": "Submitted and indexed",
            "googleCanonical": "https://example.com/",
            "userCanonical": "https://example.com/",
            "sitemap": ["https://example.com/sitemap.xml"],
            "lastCrawlTime": "2026-05-21T10:00:00Z",
        },
        "richResultsResult": {"verdict": "PASS"},
    }

    values = normalize_url_inspection_result(raw, tenant_id=tenant_id, project_id=project_id, inspection_run_id=run_id, page_url="https://example.com/")

    assert values["verdict"] == "PASS"
    assert values["sitemap_urls"] == ["https://example.com/sitemap.xml"]
    assert values["last_crawl_time"].year == 2026

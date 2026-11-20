"""The indexing monitor re-checks what it already found.

It inspected fresh URLs every week and reported a count of open issues, but
never asked Google whether the ones it had already raised were still broken. A
fix shipped last week stayed on the dashboard as an open issue indefinitely, so
the agent could not tell progress from a backlog that never moved — which is the
whole point of monitoring it on a schedule.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.indexing import GSCIndexingIssueStatus
from app.services.indexing import IndexingService


def service(issues_by_status, *, validate_error=None):
    svc = IndexingService.__new__(IndexingService)

    class Repo:
        async def list_issues(self, _p, _t, status=None, limit=100, **_):
            return list(issues_by_status.get(status, []))[:limit]

    async def validate_issue(issue_id, tenant_id, run_now=True):
        if validate_error:
            raise validate_error
        return {"result": "checked"}

    svc.repository = Repo()
    svc.validate_issue = validate_issue
    return svc


def issue(status):
    return SimpleNamespace(id=uuid4(), status=status)


@pytest.mark.asyncio
async def test_open_issues_are_re_checked():
    svc = service({GSCIndexingIssueStatus.open: [issue(GSCIndexingIssueStatus.open)] * 3})

    result = await svc.revalidate_open_issues(uuid4(), uuid4(), limit=10)

    assert result["checked"] == 3


@pytest.mark.asyncio
async def test_a_resolved_issue_is_counted_as_resolved():
    """Google confirming a fix is the only thing that should close an issue."""
    svc = service({GSCIndexingIssueStatus.fixed: [issue(GSCIndexingIssueStatus.validated)]})

    result = await svc.revalidate_open_issues(uuid4(), uuid4(), limit=10)

    assert result["resolved"] == 1
    assert result["still_failing"] == 0


@pytest.mark.asyncio
async def test_an_issue_google_still_rejects_is_counted_separately():
    svc = service({GSCIndexingIssueStatus.open: [issue(GSCIndexingIssueStatus.still_failing)]})

    result = await svc.revalidate_open_issues(uuid4(), uuid4(), limit=10)

    assert result["still_failing"] == 1
    assert result["resolved"] == 0


@pytest.mark.asyncio
async def test_one_throttled_url_does_not_stop_the_pass():
    """Google rate-limits inspection. Losing the whole pass to one throttled URL
    would mean the backlog never clears."""
    svc = service(
        {GSCIndexingIssueStatus.open: [issue(GSCIndexingIssueStatus.open)] * 3},
        validate_error=RuntimeError("429 rate limited"),
    )

    result = await svc.revalidate_open_issues(uuid4(), uuid4(), limit=10)

    assert result["checked"] == 3
    assert result["failed"] == 3


@pytest.mark.asyncio
async def test_the_quota_budget_is_respected():
    """Each re-check costs a URL inspection call against Google's quota."""
    svc = service({GSCIndexingIssueStatus.open: [issue(GSCIndexingIssueStatus.open)] * 50})

    result = await svc.revalidate_open_issues(uuid4(), uuid4(), limit=5)

    assert result["checked"] == 5
    assert result["budget"] == 5


def test_settled_states_are_not_re_checked():
    """Re-inspecting an ignored or already-validated issue spends quota that an
    unresolved one needs."""
    assert GSCIndexingIssueStatus.ignored not in IndexingService.REVALIDATION_STATUSES
    assert GSCIndexingIssueStatus.validated not in IndexingService.REVALIDATION_STATUSES
    assert GSCIndexingIssueStatus.still_failing not in IndexingService.REVALIDATION_STATUSES


def test_the_monitor_reports_what_revalidation_found():
    source = inspect.getsource(IndexingService.run_weekly_monitor)

    assert "revalidate_open_issues" in source
    assert '"revalidation": revalidation' in source

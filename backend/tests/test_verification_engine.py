"""Tests for the after-merge VerificationEngine comparison + status logic."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.verification import VerificationStatus
from app.services.verification import VerificationEngine


def test_category_mapping():
    m = VerificationEngine._category_for
    assert m("missing_schema") == "structured_data"
    assert m("json_ld") == "structured_data"
    assert m("canonical") == "technical"
    assert m("robots_update") == "technical"
    assert m("internal_link") == "links"
    assert m("image_optimization") == "performance"
    assert m("weak_metadata") == "metadata"


@pytest.mark.parametrize(
    "delta,resolved,regression,comparable,expected",
    [
        (5, True, False, True, VerificationStatus.verified_success),
        (0, True, False, True, VerificationStatus.partially_successful),
        (5, True, False, False, VerificationStatus.needs_human_review),   # no baseline
        (-4, False, False, True, VerificationStatus.failed),
        (2, False, True, True, VerificationStatus.needs_human_review),    # improved but new regressions & unresolved
    ],
)
def test_decide_status(delta, resolved, regression, comparable, expected):
    got = VerificationEngine._decide_status(SimpleNamespace(), delta, resolved, regression, comparable=comparable)
    assert got == expected


@pytest.mark.asyncio
async def test_finalize_marks_success_when_issue_resolved_and_score_up(monkeypatch):
    engine = VerificationEngine(db=object())
    baseline = SimpleNamespace(id=uuid4(), audit_id=uuid4())
    followup = SimpleNamespace(id=uuid4(), audit_id=uuid4())

    async def fake_snapshot(run):
        if run is baseline:
            return {"score": 80.0, "total": 5, "by_category": {"structured_data": 3, "metadata": 2}}
        return {"score": 88.0, "total": 2, "by_category": {"structured_data": 0, "metadata": 2}}

    monkeypatch.setattr(engine, "_audit_snapshot", fake_snapshot)
    v = SimpleNamespace(issue_type="missing_schema", patch_type="schema_addition",
                        baseline_score=None, followup_score=None)
    await engine._finalize(v, baseline, followup)

    assert v.issue_resolved is True                    # structured_data 3 -> 0
    assert v.followup_score == 88.0 and v.baseline_score == 80.0
    assert v.improvement_pct == 10.0                   # (88-80)/80
    assert v.status == VerificationStatus.verified_success
    assert v.details["score_delta"] == 8.0
    assert "structured_data" in v.details["resolved_categories"]
    assert v.details["regression"] is False


@pytest.mark.asyncio
async def test_finalize_flags_regression_and_unresolved_as_failed(monkeypatch):
    engine = VerificationEngine(db=object())
    baseline = SimpleNamespace(id=uuid4(), audit_id=uuid4())
    followup = SimpleNamespace(id=uuid4(), audit_id=uuid4())

    async def fake_snapshot(run):
        if run is baseline:
            return {"score": 80.0, "total": 3, "by_category": {"technical": 3}}
        # canonical issue NOT resolved and score dropped
        return {"score": 74.0, "total": 4, "by_category": {"technical": 3, "links": 1}}

    monkeypatch.setattr(engine, "_audit_snapshot", fake_snapshot)
    v = SimpleNamespace(issue_type="canonical", patch_type="metadata_update",
                        baseline_score=None, followup_score=None)
    await engine._finalize(v, baseline, followup)

    assert v.issue_resolved is False
    assert v.details["regression"] is True             # new 'links' category + score down
    assert v.status == VerificationStatus.failed


@pytest.mark.asyncio
async def test_finalize_without_baseline_needs_review(monkeypatch):
    engine = VerificationEngine(db=object())
    followup = SimpleNamespace(id=uuid4(), audit_id=uuid4())

    async def fake_snapshot(run):
        if run is None:
            return {"score": None, "total": 0, "by_category": {}}
        return {"score": 90.0, "total": 1, "by_category": {"metadata": 1}}

    monkeypatch.setattr(engine, "_audit_snapshot", fake_snapshot)
    v = SimpleNamespace(issue_type="weak_metadata", patch_type="metadata_update",
                        baseline_score=None, followup_score=None)
    await engine._finalize(v, None, followup)
    assert v.status == VerificationStatus.needs_human_review
    assert v.details["comparable"] is False

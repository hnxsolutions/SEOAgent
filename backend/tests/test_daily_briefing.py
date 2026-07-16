"""Tests for DailyBriefingService composition helpers and NotificationService."""
from uuid import uuid4

import pytest

from app.models.briefing import NotificationLevel
from app.services.daily_briefing import DailyBriefingService
from app.services.notifications import NotificationService


def test_severity_buckets_counts_by_severity():
    items = [
        {"severity": "critical"}, {"severity": "high"}, {"severity": "high"},
        {"severity": "medium"}, {"severity": "low"}, {"severity": "unknown"},
    ]
    b = DailyBriefingService._severity_buckets(items)
    assert b == {"critical": 1, "high": 2, "medium": 1, "low": 1}


def test_estimate_gains_scales_with_high_impact():
    high = [{"impact": "high", "code_fixable": True} for _ in range(3)]
    g = DailyBriefingService._estimate_gains(high)
    assert g["traffic"] == "+10-25%" and g["ranking"] == "significant" and g["roi"] == "high"
    low = [{"impact": "low", "code_fixable": False}]
    g2 = DailyBriefingService._estimate_gains(low)
    assert g2["traffic"] == "+0-5%" and g2["roi"] == "low"


def test_trend_direction():
    assert DailyBriefingService._trend(89, 84) == "up"
    assert DailyBriefingService._trend(80, 84) == "down"
    assert DailyBriefingService._trend(84, 84) == "flat"
    assert DailyBriefingService._trend(84, None) == "flat"


def test_recommended_actions_prioritizes():
    state = {"pending_approvals": {"proposed_patches": 2}}
    actions = DailyBriefingService._recommended_actions(state, {"critical": 1}, {"open": 3})
    joined = " ".join(actions)
    assert "3 open pull request" in joined
    assert "2 pending AI fix" in joined
    assert "1 critical issue" in joined


def test_recommended_actions_noop_when_clean():
    actions = DailyBriefingService._recommended_actions({"pending_approvals": {}}, {"critical": 0}, {"open": 0})
    assert "No action required" in actions[0]


@pytest.mark.asyncio
async def test_template_summary_mentions_key_facts():
    service = DailyBriefingService(db=object())
    sections = {
        "overall_health": 88, "seo_score": 89, "seo_score_prev": 84, "seo_score_trend": "up",
        "deployments": [{"status": "success"}, {"status": "failed"}],
        "critical_issues": 1, "estimated_traffic_gain": "+14%",
        "recommended_actions": ["Approve 2 pending AI fix(es)."],
    }
    text, source = await service._executive_summary({}, sections, use_llm=False)
    assert source == "template"
    assert "89" in text and "84" in text
    assert "1 critical" in text
    assert "+14%" in text


# -- NotificationService dedupe -----------------------------------------------

class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeDB:
    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.committed = False

    async def execute(self, _q):
        return _Result(self._results.pop(0) if self._results else [])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        return None


@pytest.mark.asyncio
async def test_notification_dedupe_skips_existing():
    existing = object()
    db = _FakeDB([[existing]])  # dedupe query finds an unread match
    svc = NotificationService(db)
    result = await svc.create(uuid4(), NotificationLevel.critical, "t", "m", dedupe_key="k")
    assert result is existing
    assert db.added == []          # nothing new created


@pytest.mark.asyncio
async def test_notification_created_when_no_dupe():
    db = _FakeDB([[]])             # dedupe query finds nothing
    svc = NotificationService(db)
    result = await svc.create(uuid4(), NotificationLevel.warning, "title", "msg", dedupe_key="k2")
    assert result is not None
    assert len(db.added) == 1
    assert db.committed is True

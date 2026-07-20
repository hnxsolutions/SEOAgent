"""Tests for closing the Core Web Vitals loop (planner + brain + delta)."""
from types import SimpleNamespace
from uuid import uuid4

from app.brain.classifier import BrainIssue, classify
from app.models.planner import SeoTaskSourceType, SeoTaskType
from app.services.pagespeed import PagespeedService
from app.services.planner import PlannerService


def _planner():
    class _DB:
        async def commit(self):
            return None
    return PlannerService(_DB())


def test_pagespeed_opportunities_become_technical_seo_tasks():
    svc = _planner()
    run_id = uuid4()
    opps = [
        {"id": "unused-javascript", "title": "Reduce unused JavaScript", "savings_ms": 1200, "run_id": run_id, "url": "https://x.com"},
        {"id": "offscreen-images", "title": "Defer offscreen images", "savings_ms": 300, "run_id": run_id, "url": "https://x.com"},
    ]
    tasks = svc._tasks_from_pagespeed(opps)
    assert len(tasks) == 2
    for t in tasks:
        assert t.task_type == SeoTaskType.technical_seo_fix
        assert t.source_type == SeoTaskSourceType.core_web_vitals
        assert t.source_reference_id is not None
    # Each opportunity gets a distinct, stable reference id (so they don't
    # collapse onto one planner task).
    assert tasks[0].source_reference_id != tasks[1].source_reference_id
    # Larger savings -> higher priority.
    assert tasks[0].priority_score > tasks[1].priority_score


def test_pagespeed_actions_use_human_readable_titles():
    svc = _planner()
    tasks = svc._tasks_from_pagespeed([{"id": "modern-image-formats", "savings_ms": 500, "run_id": uuid4()}])
    assert "WebP" in tasks[0].title


def test_empty_opportunities_yield_no_tasks():
    assert _planner()._tasks_from_pagespeed([]) == []
    assert _planner()._tasks_from_pagespeed(None) == []


def test_classifier_ranks_cwv_opportunities_by_category():
    render_blocking = classify(BrainIssue(source="pagespeed", issue_type="render-blocking-resources", severity="high", title="Eliminate render-blocking resources"))
    assert render_blocking.category == "performance"
    assert render_blocking.code_fixable is True   # deferring CSS/JS is code-fixable

    unused_js = classify(BrainIssue(source="pagespeed", issue_type="unused-javascript", severity="medium", title="Reduce unused JavaScript"))
    assert unused_js.category == "performance"
    assert unused_js.code_fixable is False         # high-effort, not auto-patchable


def test_pagespeed_delta_computes_before_after():
    before = SimpleNamespace(performance_score=55, accessibility_score=90, best_practices_score=80, seo_score=95,
                             lcp_ms=4200, cls=0.2, inp_ms=300, fcp_ms=1800, tbt_ms=500)
    after = SimpleNamespace(performance_score=78, accessibility_score=92, best_practices_score=83, seo_score=95,
                            lcp_ms=2600, cls=0.05, inp_ms=180, fcp_ms=1400, tbt_ms=210)
    d = PagespeedService.delta(before, after)
    assert d["performance_delta"] == 23      # improved
    assert d["lcp_ms_delta"] == -1600        # faster LCP (negative = better)
    assert d["cls_delta"] == -0.15
    assert d["seo_delta"] == 0


def test_pagespeed_delta_handles_missing_values():
    before = SimpleNamespace(performance_score=None, accessibility_score=90, best_practices_score=80, seo_score=95,
                             lcp_ms=None, cls=None, inp_ms=None, fcp_ms=None, tbt_ms=None)
    after = SimpleNamespace(performance_score=78, accessibility_score=None, best_practices_score=83, seo_score=95,
                            lcp_ms=2600, cls=0.05, inp_ms=180, fcp_ms=1400, tbt_ms=210)
    d = PagespeedService.delta(before, after)
    assert d["performance_delta"] is None
    assert d["lcp_ms_delta"] is None
    assert d["best_practices_delta"] == 3

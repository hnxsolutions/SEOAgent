"""Post-merge verification pipeline: comparison + learning logic (pure paths)."""
from types import SimpleNamespace as S

from app.models.deployment_verification import DeploymentVerification
from app.services.verification_pipeline import VerificationPipelineService


def _svc():
    return VerificationPipelineService(db=None)  # type: ignore[arg-type]


def test_verdict_higher_is_better():
    svc = _svc()
    assert svc._verdict(70, 85, lower_is_better=False) == "improved"
    assert svc._verdict(85, 70, lower_is_better=False) == "declined"
    assert svc._verdict(80, 80, lower_is_better=False) == "no_change"
    assert svc._verdict(None, 80, lower_is_better=False) == "no_data"


def test_verdict_lower_is_better_for_cwv():
    svc = _svc()
    # LCP dropping from 3000ms to 2000ms is an improvement
    assert svc._verdict(3000, 2000, lower_is_better=True) == "improved"
    assert svc._verdict(2000, 3000, lower_is_better=True) == "declined"


def test_compare_cwv_builds_verdicts_from_real_metrics():
    svc = _svc()
    dv = DeploymentVerification(timeline=[])
    dv.pagespeed_before = {"metrics": {"lcp_ms": 3000, "performance": 70}}
    dv.pagespeed_after = {"metrics": {"lcp_ms": 2000, "performance": 85}}
    svc._compare_cwv(dv)
    assert dv.cwv_comparison["lcp_ms"]["verdict"] == "improved"
    assert dv.cwv_comparison["performance"]["verdict"] == "improved"


def test_compare_seo_uses_measured_signals():
    svc = _svc()
    dv = DeploymentVerification(timeline=[])
    dv.seo_before, dv.seo_after = 80, 92
    dv.live_site = {"checks": {"has_title": True, "has_canonical": True, "has_sitemap": False}}
    dv.pagespeed_before = {"metrics": {"performance": 70}}
    dv.pagespeed_after = {"metrics": {"performance": 80}}
    svc._compare_seo(dv)
    assert dv.seo_comparison["seo_score"]["verdict"] == "improved"
    assert dv.seo_comparison["canonical"] == "present"
    assert dv.seo_comparison["pagespeed"]["verdict"] == "improved"


def test_pagespeed_snapshot_reads_run_fields():
    svc = _svc()
    mobile = S(status=S(value="completed"), performance_score=88, seo_score=95,
               accessibility_score=90, best_practices_score=92, lcp_ms=2100, cls=0.02,
               inp_ms=120, fcp_ms=1200, ttfb_ms=300)
    snap = svc._pagespeed_snapshot({"mobile": mobile, "desktop": None})
    assert snap["status"] == "completed" and snap["metrics"]["performance"] == 88
    assert snap["metrics"]["lcp_ms"] == 2100


def test_event_appends_timeline_entry():
    svc = _svc()
    dv = DeploymentVerification(timeline=[])
    svc._event(dv, "Verification started")
    svc._event(dv, "PageSpeed complete")
    assert [e["event"] for e in dv.timeline] == ["Verification started", "PageSpeed complete"]
    assert all("time" in e for e in dv.timeline)


def test_pagespeed_snapshot_no_data():
    svc = _svc()
    snap = svc._pagespeed_snapshot({"mobile": None, "desktop": None})
    assert snap["status"] == "no_data" and snap["metrics"] == {}

"""SEO Operations Engine pure-logic tests (health scoring, change detection)."""
from datetime import datetime, timedelta

from app.models.ops_snapshot import OpsHealthSnapshot
from app.services.seo_operations import LIFECYCLE_STAGES, SeoOperationsEngine


def _svc():
    return SeoOperationsEngine(db=None)  # type: ignore[arg-type]


def test_cwv_score_from_thresholds():
    svc = _svc()
    assert svc._cwv_score({"lcp_ms": 2000, "cls": 0.05, "inp_ms": 150}) == 90   # all good
    assert svc._cwv_score({"lcp_ms": 5000, "cls": 0.4, "inp_ms": 600}) == 30    # all poor
    assert svc._cwv_score({}) is None                                            # not measured


def test_grade_bands():
    svc = _svc()
    assert svc._grade(95) == "A" and svc._grade(80) == "B" and svc._grade(65) == "C"
    assert svc._grade(45) == "D" and svc._grade(20) == "F" and svc._grade(None) is None


def test_content_and_links_score_penalize_issues():
    svc = _svc()
    assert svc._content_score({"content": 0}) == 100
    assert svc._content_score({"content": 5}) == 60
    assert svc._content_score({}) is None  # no audit -> not measured


def test_change_direction_respects_metric_polarity():
    svc = _svc()
    # LCP lower is better
    assert svc._change_dir("lcp_ms", 3000, 2000) == "improved"
    assert svc._change_dir("lcp_ms", 2000, 3000) == "declined"
    # score higher is better
    assert svc._change_dir("seo_readiness", 70, 85) == "improved"
    # bool signal appearing
    assert svc._change_dir("has_schema", False, True) == "improved"
    assert svc._change_dir("has_sitemap", True, False) == "declined"


def test_diff_reports_overall_and_signal_changes():
    svc = _svc()
    prev = OpsHealthSnapshot(overall_score=70, dimensions={}, signals={"has_schema": False, "lcp_ms": 3000})
    curr = OpsHealthSnapshot(overall_score=82, dimensions={}, signals={"has_schema": True, "lcp_ms": 2400})
    changes = svc._diff(prev, curr)
    fields = {c["field"]: c for c in changes}
    assert fields["overall_health"]["direction"] == "improved" and fields["overall_health"]["delta"] == 12
    assert fields["has_schema"]["direction"] == "improved"
    assert fields["lcp_ms"]["direction"] == "improved"


def test_bucket_classifies_recency():
    svc = _svc()
    now = datetime.utcnow()
    assert svc._bucket(now) == "today"
    assert svc._bucket(now - timedelta(days=1)) == "yesterday"
    assert svc._bucket(now - timedelta(days=4)) == "this_week"
    assert svc._bucket(now - timedelta(days=20)) == "this_month"


def test_lifecycle_stage_order_is_complete():
    assert LIFECYCLE_STAGES[0] == "fingerprint" and LIFECYCLE_STAGES[-1] == "monitoring"
    assert "admin_review" in LIFECYCLE_STAGES and "deployment_verification" in LIFECYCLE_STAGES

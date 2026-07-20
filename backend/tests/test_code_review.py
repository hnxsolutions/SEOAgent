"""Code review analysis + approval lifecycle tests."""
from types import SimpleNamespace as S
from uuid import uuid4

import pytest

from app.code_review.analysis import (
    build_file_review,
    diff_lines,
    estimate_impact,
    explanation_for,
    expected_result_for,
    max_risk,
    risk_for_surface,
)
from app.models.code_review import ReviewRisk


def test_risk_mapping_matches_spec():
    assert risk_for_surface("metadata") == ReviewRisk.low
    assert risk_for_surface("schema") == ReviewRisk.low
    assert risk_for_surface("robots") == ReviewRisk.medium
    assert risk_for_surface("sitemap") == ReviewRisk.medium
    assert risk_for_surface("redirect") == ReviewRisk.high
    assert risk_for_surface("middleware") == ReviewRisk.high
    assert risk_for_surface("ui") == ReviewRisk.blocked


def test_max_risk_picks_highest():
    assert max_risk([ReviewRisk.low, ReviewRisk.medium, ReviewRisk.low]) == ReviewRisk.medium
    assert max_risk([ReviewRisk.low, ReviewRisk.high]) == ReviewRisk.high
    assert max_risk([]) == ReviewRisk.low


def test_explanation_is_reasoned_not_generic():
    e = explanation_for("canonical", "Next.js", "app/page.tsx")
    assert "duplicate" in (e["problem"] + e["consequence"]).lower()
    assert "canonical" in e["fix"].lower()
    # never a bare 'generated automatically'
    assert "generated automatically" not in " ".join(e.values()).lower()


def test_expected_result_is_labeled_prediction():
    r = expected_result_for("schema", 80)
    assert r["is_prediction"] is True and "prediction" in r["disclaimer"].lower()
    assert r["rich_result_improvement"] == "Improved"


def test_estimate_impact_predicts_after_from_before():
    est = estimate_impact(["metadata", "schema", "sitemap"], 80)
    assert est["is_prediction"] is True
    assert est["seo_before"] == 80
    assert est["seo_after_predicted"] > 80 and est["seo_after_predicted"] <= 100
    assert est["seo_impact_label"].startswith(("High", "Medium", "Low"))


def test_diff_marks_new_file_as_all_adds():
    lines = diff_lines("", "line1\nline2")
    assert all(l["type"] == "add" for l in lines) and len(lines) == 2


def test_diff_marks_added_and_context():
    lines = diff_lines("a\nb", "a\nb\nc")
    kinds = [l["type"] for l in lines]
    assert "context" in kinds and kinds[-1] == "add" and lines[-1]["text"] == "c"


def test_build_file_review_new_file_full_detail():
    patch = S(id=uuid4(), surface="robots", target_file="app/robots.ts", language="typescript",
              is_new_file=True, generated_code="export default function robots(){return {}}",
              confidence=85, validation_notes={"safety": "ok"})
    fr = build_file_review(patch, "nextjs", 90)
    assert fr["surface"] == "robots" and fr["risk"] == "medium"
    assert fr["lines_added"] >= 1 and fr["lines_removed"] == 0
    assert fr["explanation"]["fix"] and fr["expected_result"]["is_prediction"] is True

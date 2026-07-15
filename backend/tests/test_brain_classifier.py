"""Unit tests for the SEO brain issue classifier."""
from app.brain.classifier import (
    CATEGORY_CONTENT,
    CATEGORY_CRAWLABILITY,
    CATEGORY_INDEXABILITY,
    CATEGORY_METADATA,
    CATEGORY_STRUCTURED_DATA,
    BrainIssue,
    classify,
)


def test_critical_indexability_ranks_highest():
    critical = classify(BrainIssue("robots", "disallow_all", "critical", title="site blocked"))
    minor = classify(BrainIssue("sitemap", "duplicate_url", "low", title="dup"))
    assert critical.priority_score > minor.priority_score
    assert critical.severity == "critical"
    assert critical.category == CATEGORY_INDEXABILITY


def test_blocked_assets_are_code_fixable_and_crawlability():
    c = classify(BrainIssue("robots", "blocked_css", "high", title="blocked css"))
    assert c.category == CATEGORY_CRAWLABILITY
    assert c.code_fixable is True
    assert c.impact == "high"


def test_thin_content_not_code_fixable():
    c = classify(BrainIssue("audit", "thin_content", "medium", category="content", title="Thin content"))
    assert c.category == CATEGORY_CONTENT
    assert c.code_fixable is False
    assert c.difficulty == "high"


def test_metadata_is_low_effort_code_fixable():
    c = classify(BrainIssue("audit", "meta_description", "medium", category="metadata", title="Meta desc"))
    assert c.category == CATEGORY_METADATA
    assert c.code_fixable is True
    assert c.difficulty == "low"


def test_schema_is_structured_data():
    c = classify(BrainIssue("audit", "missing_schema", "medium", category="structured_data", title="Missing schema"))
    assert c.category == CATEGORY_STRUCTURED_DATA
    assert c.code_fixable is True


def test_low_effort_raises_priority_over_high_effort_same_severity():
    low_effort = classify(BrainIssue("audit", "meta_description", "high", title="meta"))
    high_effort = classify(BrainIssue("audit", "core_web_vitals", "high", title="cwv"))
    assert low_effort.priority_score > high_effort.priority_score


def test_traffic_and_ranking_bands_present():
    c = classify(BrainIssue("robots", "disallow_all", "critical", title="x"))
    assert c.expected_traffic_gain.startswith("+")
    assert isinstance(c.expected_ranking_gain, str) and c.expected_ranking_gain
    assert 0 <= c.confidence <= 100
    assert 0 <= c.priority_score <= 100


def test_unknown_issue_defaults_gracefully():
    c = classify(BrainIssue("audit", "totally_unknown_type", "medium", title="mystery"))
    assert c.category == "other"
    assert c.code_fixable is False
    assert c.priority_score > 0


def test_severity_dominates_ranking():
    crit = classify(BrainIssue("audit", "meta_description", "critical", title="m"))
    low = classify(BrainIssue("audit", "meta_description", "low", title="m"))
    assert crit.priority_score > low.priority_score

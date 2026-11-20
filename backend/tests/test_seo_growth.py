"""AI SEO Growth analysis tests (pure, no I/O)."""
from app.growth.analysis import (
    classify_intent,
    cluster_topics,
    estimate_traffic,
    growth_score,
    keyword_difficulty,
    priority_score,
    suggest_blog_post,
)


def test_classify_intent_covers_types():
    assert classify_intent("buy running shoes") == "transactional"
    assert classify_intent("best crm software") == "commercial"
    assert classify_intent("how to fix seo") == "question"
    assert classify_intent("dentist near me") in ("transactional", "local")  # "near me" is transactional-local
    assert classify_intent("acme corp", brand_terms=["acme"]) == "brand"
    assert classify_intent("healthcare plans for small remote teams") == "long_tail"
    assert classify_intent("seo") == "informational"


def test_keyword_difficulty_from_position_and_volume():
    assert keyword_difficulty(5, None) == "low"       # already page 1
    assert keyword_difficulty(15, None) == "medium"   # striking distance
    assert keyword_difficulty(None, 10000) == "high"  # high volume, not ranking
    assert keyword_difficulty(None, None) == "medium"


def test_priority_favors_commercial_lowdiff_striking_distance():
    hi = priority_score(intent="transactional", difficulty="low", impressions=2000, position=6, ctr=0.01)
    lo = priority_score(intent="informational", difficulty="high", impressions=None, position=None)
    assert hi > lo and 0 <= hi <= 100 and 0 <= lo <= 100


def test_estimate_traffic_is_labelled_estimate():
    e = estimate_traffic(1000, 15, 0.01)
    assert e["is_estimate"] is True
    assert e["estimated_monthly_clicks"] is not None and e["estimated_monthly_clicks"] > 0
    assert "estimate" in e["note"].lower()
    # no data -> honest null
    e2 = estimate_traffic(None, None)
    assert e2["estimated_monthly_clicks"] is None and e2["is_estimate"] is True


def test_suggest_blog_post_is_framework_aware():
    nextjs = suggest_blog_post("Best CRM for startups", "best crm", framework_key="nextjs",
                               domain="example.com", secondary=["crm pricing"])
    wp = suggest_blog_post("Best CRM for startups", "best crm", framework_key="wordpress", domain="example.com")
    assert nextjs["suggested_url"].startswith("https://example.com/blog/")
    assert "metadata API" in nextjs["suggested_schema"] or "server component" in nextjs["suggested_schema"]
    assert "Yoast" in wp["suggested_schema"] or "Rank Math" in wp["suggested_schema"]
    assert nextjs["search_intent"] == "commercial"


def test_cluster_topics_groups_by_pillar():
    clusters = cluster_topics(["dental implants", "dental crowns", "teeth whitening cost", "whitening near me"])
    pillars = {c["pillar"] for c in clusters}
    assert "implants" in pillars or "dental" in pillars
    assert any(c["article_count"] >= 1 for c in clusters)


def test_growth_score_composes_measured_dimensions():
    gs = growth_score({"keyword_coverage": 60, "topic_coverage": 40, "content_authority": 80, "content_pipeline": None})
    assert gs["overall"] == 60  # avg of 60,40,80 (None excluded)
    assert gs["measured_dimensions"] == 3

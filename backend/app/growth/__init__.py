"""AI SEO Growth analysis.

Pure, deterministic helpers that turn a project's existing signals (keywords,
Search Console opportunities, services, location, crawl) into growth
recommendations: keyword intent, difficulty, priority, traffic ESTIMATES,
framework-aware blog suggestions, and topic clustering. No I/O — the service
feeds these functions real data so they stay unit-testable, and every traffic
number is a clearly-labelled estimate (never fabricated as measured).
"""
from app.growth.analysis import (
    classify_intent,
    cluster_topics,
    estimate_traffic,
    growth_score,
    keyword_difficulty,
    priority_score,
    suggest_blog_post,
)

__all__ = [
    "classify_intent",
    "cluster_topics",
    "estimate_traffic",
    "growth_score",
    "keyword_difficulty",
    "priority_score",
    "suggest_blog_post",
]

"""Deterministic issue classifier for the autonomous SEO brain.

Pure functions only (no I/O, no DB). Given a normalized issue collected from any
existing module (audit, robots, sitemap, indexing, search console, planner), it
assigns the dimensions a senior SEO engineer would reason about:
severity, impact, difficulty, category, expected traffic/ranking gain,
confidence, estimated implementation time, business impact, whether it is
code-fixable (repo-agent addressable), and a composite priority score used to
rank one master plan.

These are transparent, defensible heuristics — not a black box and not fake AI.
An LLM refinement pass can be layered on later without changing this contract.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


# Normalized category buckets a senior SEO engineer triages by.
CATEGORY_INDEXABILITY = "indexability"
CATEGORY_CRAWLABILITY = "crawlability"
CATEGORY_METADATA = "metadata"
CATEGORY_STRUCTURED_DATA = "structured_data"
CATEGORY_CONTENT = "content"
CATEGORY_LINKS = "links"
CATEGORY_PERFORMANCE = "performance"
CATEGORY_OTHER = "other"

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class BrainIssue:
    """A normalized issue collected from any module."""
    source: str                      # audit | robots | sitemap | indexing | search_console | planner
    issue_type: str
    severity: str = "medium"
    category: Optional[str] = None
    title: str = ""
    description: str = ""
    url: Optional[str] = None
    reference_id: Optional[str] = None


@dataclass
class Classification:
    severity: str
    impact: str                      # low | medium | high
    difficulty: str                  # low | medium | high
    category: str
    code_fixable: bool
    estimated_minutes: int
    expected_traffic_gain: str       # human band, e.g. "+2-5%"
    expected_ranking_gain: str
    confidence: int                  # 0-100
    business_impact: str             # low | medium | high
    priority_score: float            # 0-100, higher = do first

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# issue_type keyword -> (category, difficulty, est_minutes, code_fixable, base_confidence)
# Matched by substring so the same table serves audit/robots/sitemap vocabularies.
_RULES = [
    # Indexability (highest leverage; often blocks everything downstream)
    ("disallow_all", CATEGORY_INDEXABILITY, "low", 10, True, 95),
    ("noindex", CATEGORY_INDEXABILITY, "low", 15, True, 85),
    ("canonical", CATEGORY_INDEXABILITY, "medium", 30, True, 80),
    ("soft_404", CATEGORY_INDEXABILITY, "medium", 45, False, 70),
    ("not_indexed", CATEGORY_INDEXABILITY, "medium", 45, False, 65),
    ("duplicate", CATEGORY_INDEXABILITY, "medium", 40, True, 70),
    # Crawlability
    ("blocked_css", CATEGORY_CRAWLABILITY, "low", 15, True, 90),
    ("blocked_js", CATEGORY_CRAWLABILITY, "low", 15, True, 90),
    ("blocked_images", CATEGORY_CRAWLABILITY, "low", 15, True, 80),
    ("robots", CATEGORY_CRAWLABILITY, "low", 15, True, 80),
    ("broken_wildcard", CATEGORY_CRAWLABILITY, "low", 15, True, 75),
    ("redirect", CATEGORY_CRAWLABILITY, "medium", 30, True, 70),
    ("crawl", CATEGORY_CRAWLABILITY, "medium", 30, False, 60),
    # Sitemap
    ("sitemap", CATEGORY_INDEXABILITY, "low", 20, True, 80),
    # Metadata
    ("title", CATEGORY_METADATA, "low", 15, True, 85),
    ("meta_description", CATEGORY_METADATA, "low", 15, True, 80),
    ("metadata", CATEGORY_METADATA, "low", 15, True, 80),
    ("open_graph", CATEGORY_METADATA, "low", 15, True, 75),
    ("twitter", CATEGORY_METADATA, "low", 15, True, 75),
    ("heading", CATEGORY_METADATA, "low", 20, True, 70),
    # Structured data
    ("schema", CATEGORY_STRUCTURED_DATA, "medium", 30, True, 75),
    ("json_ld", CATEGORY_STRUCTURED_DATA, "medium", 30, True, 75),
    ("faq", CATEGORY_STRUCTURED_DATA, "medium", 30, True, 70),
    ("breadcrumb", CATEGORY_STRUCTURED_DATA, "medium", 25, True, 70),
    ("hreflang", CATEGORY_STRUCTURED_DATA, "high", 60, True, 60),
    # Links
    ("internal_link", CATEGORY_LINKS, "medium", 30, True, 70),
    ("orphan", CATEGORY_LINKS, "medium", 40, True, 65),
    ("broken_link", CATEGORY_LINKS, "medium", 30, True, 75),
    # Content
    ("thin", CATEGORY_CONTENT, "high", 120, False, 60),
    ("content", CATEGORY_CONTENT, "high", 120, False, 55),
    ("alt", CATEGORY_CONTENT, "low", 20, True, 70),
    ("image", CATEGORY_PERFORMANCE, "medium", 40, True, 60),
    # Performance
    ("core_web_vitals", CATEGORY_PERFORMANCE, "high", 90, False, 60),
    ("performance", CATEGORY_PERFORMANCE, "high", 90, False, 55),
]

_IMPACT_BY_CATEGORY = {
    CATEGORY_INDEXABILITY: "high",
    CATEGORY_CRAWLABILITY: "high",
    CATEGORY_STRUCTURED_DATA: "medium",
    CATEGORY_METADATA: "medium",
    CATEGORY_CONTENT: "medium",
    CATEGORY_LINKS: "medium",
    CATEGORY_PERFORMANCE: "medium",
    CATEGORY_OTHER: "low",
}


def _match_rule(issue: BrainIssue):
    haystack = f"{issue.issue_type} {issue.category or ''} {issue.title}".lower()
    for keyword, category, difficulty, minutes, code_fixable, confidence in _RULES:
        if keyword in haystack:
            return category, difficulty, minutes, code_fixable, confidence
    return CATEGORY_OTHER, "medium", 30, False, 50


def _traffic_band(priority: float) -> str:
    if priority >= 80:
        return "+10-25%"
    if priority >= 65:
        return "+5-15%"
    if priority >= 45:
        return "+2-5%"
    return "+0-2%"


def _ranking_band(priority: float) -> str:
    if priority >= 80:
        return "significant (multiple positions)"
    if priority >= 55:
        return "moderate (1-3 positions)"
    return "minor"


def classify(issue: BrainIssue) -> Classification:
    severity = issue.severity if issue.severity in _SEVERITY_RANK else "medium"
    category, difficulty, minutes, code_fixable, confidence = _match_rule(issue)
    impact = _IMPACT_BY_CATEGORY.get(category, "low")

    # Composite priority: severity dominates, impact and low effort raise it,
    # low confidence tempers it. Kept on a 0-100 scale.
    sev_component = _SEVERITY_RANK[severity] / 4 * 55          # up to 55
    impact_component = {"low": 5, "medium": 12, "high": 22}[impact]
    effort_bonus = {"low": 15, "medium": 7, "high": 0}[difficulty]
    confidence_factor = confidence / 100
    priority = round((sev_component + impact_component + effort_bonus) * (0.6 + 0.4 * confidence_factor), 1)
    priority = max(0.0, min(100.0, priority))

    business_impact = "high" if (impact == "high" and severity in {"high", "critical"}) else (
        "medium" if severity in {"medium", "high", "critical"} else "low"
    )

    return Classification(
        severity=severity,
        impact=impact,
        difficulty=difficulty,
        category=category,
        code_fixable=code_fixable,
        estimated_minutes=minutes,
        expected_traffic_gain=_traffic_band(priority),
        expected_ranking_gain=_ranking_band(priority),
        confidence=confidence,
        business_impact=business_impact,
        priority_score=priority,
    )

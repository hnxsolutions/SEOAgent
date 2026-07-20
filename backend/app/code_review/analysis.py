"""Pure analysis for the human code-review workflow.

Everything here is deterministic and I/O-free so it is easy to test. Predictions
are clearly labelled as predictions — the module never fabricates a measured
result (real before/after comes from the Verification + PageSpeed engines only
after a merge + deploy)."""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from app.models.code_review import ReviewRisk

# Per-surface risk. UI/routing/middleware never reach here (safety refuses them);
# they are listed so the mapping is explicit and auditable.
SURFACE_RISK: Dict[str, ReviewRisk] = {
    "metadata": ReviewRisk.low,
    "og_twitter": ReviewRisk.low,
    "schema": ReviewRisk.low,
    "canonical": ReviewRisk.low,
    "hreflang": ReviewRisk.low,
    "sitemap": ReviewRisk.medium,
    "robots": ReviewRisk.medium,
    "redirect": ReviewRisk.high,
    "routing": ReviewRisk.high,
    "middleware": ReviewRisk.high,
    "ui": ReviewRisk.blocked,
}

_RISK_ORDER = {ReviewRisk.low: 0, ReviewRisk.medium: 1, ReviewRisk.high: 2, ReviewRisk.blocked: 3}

# Points each newly-added surface is expected to move the on-page SEO signal set.
_SURFACE_SEO_POINTS = {"metadata": 6, "schema": 5, "sitemap": 4, "robots": 3, "og_twitter": 4, "canonical": 5}


def risk_for_surface(surface: str) -> ReviewRisk:
    return SURFACE_RISK.get((surface or "").lower(), ReviewRisk.medium)


def max_risk(risks: List[ReviewRisk]) -> ReviewRisk:
    if not risks:
        return ReviewRisk.low
    return max(risks, key=lambda r: _RISK_ORDER.get(r, 0))


def explanation_for(surface: str, framework: str, target_file: str) -> Dict[str, str]:
    """WHY this code was generated — problem, consequence, and the fix. Never a
    bare 'generated automatically'."""
    fw = framework or "your framework"
    table = {
        "metadata": {
            "problem": "Pages need a clear title, meta description and canonical URL.",
            "consequence": "Without them Google may show poor snippets or index duplicate URLs.",
            "fix": f"This patch adds title/description/canonical using {fw}'s native metadata API in {target_file}.",
        },
        "og_twitter": {
            "problem": "Open Graph / Twitter Card tags are missing.",
            "consequence": "Shared links render without a rich title, description or image.",
            "fix": f"This patch adds Open Graph and Twitter Card meta tags in {target_file}.",
        },
        "schema": {
            "problem": "Structured data (Schema.org) is missing.",
            "consequence": "The site is less likely to earn rich results in search.",
            "fix": f"This patch adds JSON-LD Organization structured data via {target_file}.",
        },
        "sitemap": {
            "problem": "An XML sitemap helps search engines discover all pages.",
            "consequence": "New or deep pages may be crawled slowly or missed.",
            "fix": f"This patch adds a sitemap using {fw}'s sitemap convention in {target_file}.",
        },
        "robots": {
            "problem": "robots rules should allow crawling and point to the sitemap.",
            "consequence": "Crawlers may not find the sitemap, slowing indexation.",
            "fix": f"This patch adds robots rules + the sitemap directive in {target_file}.",
        },
        "canonical": {
            "problem": "Canonical tags are missing.",
            "consequence": "Google may index duplicate pages and split ranking signals.",
            "fix": f"This patch adds canonical metadata in {target_file}.",
        },
    }
    return table.get((surface or "").lower(), {
        "problem": "An SEO improvement was identified.",
        "consequence": "Missing SEO signals can reduce visibility.",
        "fix": f"This patch adds the relevant SEO code in {target_file}.",
    })


def expected_result_for(surface: str, seo_before: Optional[int]) -> Dict[str, Any]:
    """Predicted outcome — explicitly a prediction, not a measurement."""
    s = (surface or "").lower()
    crawling = "Improved" if s in ("robots", "sitemap") else "Neutral"
    rich = "Improved" if s == "schema" else ("Slightly improved" if s == "og_twitter" else "Neutral")
    metadata_quality = "Improved" if s in ("metadata", "canonical", "og_twitter") else "Neutral"
    indexability = "Improved" if s in ("robots", "sitemap", "canonical") else "Neutral"
    lighthouse = "Slightly improved" if s in ("metadata", "canonical") else "Neutral"
    return {
        "is_prediction": True,
        "disclaimer": "These are predictions. Real before/after is measured only after merge + deploy.",
        "crawling_improvement": crawling,
        "rich_result_improvement": rich,
        "metadata_quality": metadata_quality,
        "indexability": indexability,
        "lighthouse_seo": lighthouse,
    }


def estimate_impact(surfaces: List[str], seo_before: Optional[int]) -> Dict[str, Any]:
    points = sum(_SURFACE_SEO_POINTS.get((s or "").lower(), 2) for s in surfaces)
    before = seo_before if seo_before is not None else None
    after = min(100, before + points) if before is not None else None
    if points >= 12:
        label = f"High (+{points})"
    elif points >= 6:
        label = f"Medium (+{points})"
    else:
        label = f"Low (+{points})"
    perf = "Low" if all((s or "").lower() in ("metadata", "og_twitter", "schema", "canonical") for s in surfaces) else "Medium"
    return {
        "seo_impact_label": label,
        "performance_impact_label": perf,
        "seo_before": before,
        "seo_after_predicted": after,
        "is_prediction": True,
    }


def diff_lines(old: str, new: str) -> List[Dict[str, str]]:
    """Line-by-line diff: type in {add, remove, context}. New files are all adds."""
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    out: List[Dict[str, str]] = []
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for line in new_lines[j1:j2]:
                out.append({"type": "context", "text": line})
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                out.append({"type": "remove", "text": line})
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                out.append({"type": "add", "text": line})
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                out.append({"type": "remove", "text": line})
            for line in new_lines[j1:j2]:
                out.append({"type": "add", "text": line})
    return out


def build_file_review(patch, framework: str, seo_before: Optional[int]) -> Dict[str, Any]:
    """Full reviewer detail for one generated patch (old vs new + why + expected + risk)."""
    old_code = "" if getattr(patch, "is_new_file", True) else ""  # OLD unknown w/o repo -> new content
    new_code = patch.generated_code or ""
    surface = patch.surface
    risk = risk_for_surface(surface)
    lines = diff_lines(old_code, new_code)
    added = sum(1 for l in lines if l["type"] == "add")
    removed = sum(1 for l in lines if l["type"] == "remove")
    return {
        "id": str(patch.id),
        "surface": surface,
        "target_file": patch.target_file,
        "language": patch.language,
        "is_new_file": patch.is_new_file,
        "old_code": old_code,
        "new_code": new_code,
        "diff": lines,
        "lines_added": added,
        "lines_removed": removed,
        "risk": risk.value,
        "confidence": patch.confidence,
        "explanation": explanation_for(surface, framework, patch.target_file),
        "expected_result": expected_result_for(surface, seo_before),
        "validation_notes": patch.validation_notes,
    }

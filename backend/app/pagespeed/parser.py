"""Pure parser for the official Google PageSpeed Insights (Lighthouse) response.

No I/O. Extracts category scores, Core Web Vitals (lab + field), opportunities
and diagnostics from the documented PSI v5 schema so the service can persist them
and the brain can classify them. Never invents values — missing fields stay None.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _score(categories: Dict[str, Any], key: str) -> Optional[float]:
    cat = categories.get(key)
    if not cat:
        return None
    score = cat.get("score")
    return round(score * 100, 1) if isinstance(score, (int, float)) else None


def _numeric(audits: Dict[str, Any], audit_id: str) -> Optional[float]:
    audit = audits.get(audit_id)
    if not audit:
        return None
    value = audit.get("numericValue")
    return float(value) if isinstance(value, (int, float)) else None


def _first_numeric(audits: Dict[str, Any], ids: List[str]) -> Optional[float]:
    for aid in ids:
        v = _numeric(audits, aid)
        if v is not None:
            return v
    return None


def _field_metric(loading_exp: Dict[str, Any], key: str) -> Optional[float]:
    metrics = (loading_exp or {}).get("metrics") or {}
    m = metrics.get(key)
    if not m:
        return None
    p = m.get("percentile")
    return float(p) if isinstance(p, (int, float)) else None


def parse_pagespeed(response: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a PSI v5 response into a flat dict of metrics + opportunities."""
    lr = response.get("lighthouseResult") or {}
    categories = lr.get("categories") or {}
    audits = lr.get("audits") or {}
    loading_exp = response.get("loadingExperience") or {}

    scores = {
        "performance_score": _score(categories, "performance"),
        "accessibility_score": _score(categories, "accessibility"),
        "best_practices_score": _score(categories, "best-practices"),
        "seo_score": _score(categories, "seo"),
    }

    cwv = {
        "lcp_ms": _numeric(audits, "largest-contentful-paint"),
        "cls": _numeric(audits, "cumulative-layout-shift"),
        # INP audit id has changed across Lighthouse versions; try known ids.
        "inp_ms": _first_numeric(audits, ["interaction-to-next-paint", "experimental-interaction-to-next-paint"]),
        "tbt_ms": _numeric(audits, "total-blocking-time"),
        "fcp_ms": _numeric(audits, "first-contentful-paint"),
        "speed_index_ms": _numeric(audits, "speed-index"),
        "ttfb_ms": _numeric(audits, "server-response-time"),
    }

    field = {
        "field_lcp_ms": _field_metric(loading_exp, "LARGEST_CONTENTFUL_PAINT_MS"),
        # CrUX CLS percentile is CLS*100 (integer); normalise back to a ratio.
        "field_cls": (lambda v: round(v / 100, 3) if v is not None else None)(
            _field_metric(loading_exp, "CUMULATIVE_LAYOUT_SHIFT_SCORE")
        ),
        "field_inp_ms": _field_metric(loading_exp, "INTERACTION_TO_NEXT_PAINT"),
    }

    opportunities = extract_opportunities(audits)
    diagnostics = extract_diagnostics(audits)

    return {**scores, **cwv, **field, "opportunities": opportunities, "diagnostics": diagnostics}


def extract_opportunities(audits: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Audits with an 'opportunity' details section and real savings."""
    out: List[Dict[str, Any]] = []
    for aid, audit in audits.items():
        details = audit.get("details") or {}
        if details.get("type") != "opportunity":
            continue
        savings = details.get("overallSavingsMs")
        score = audit.get("score")
        # Only surface audits that are not already passing.
        if score is not None and score >= 0.9 and not savings:
            continue
        out.append({
            "id": aid,
            "title": audit.get("title"),
            "description": (audit.get("description") or "")[:400],
            "savings_ms": float(savings) if isinstance(savings, (int, float)) else None,
            "score": score,
            "display_value": audit.get("displayValue"),
        })
    out.sort(key=lambda o: (o["savings_ms"] or 0), reverse=True)
    return out


def extract_diagnostics(audits: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Non-opportunity, non-passing audits that carry a display value."""
    out: List[Dict[str, Any]] = []
    for aid, audit in audits.items():
        details = audit.get("details") or {}
        if details.get("type") == "opportunity":
            continue
        score = audit.get("score")
        if score is None or score >= 0.9:
            continue
        if not audit.get("displayValue"):
            continue
        out.append({
            "id": aid,
            "title": audit.get("title"),
            "display_value": audit.get("displayValue"),
            "score": score,
        })
    return out

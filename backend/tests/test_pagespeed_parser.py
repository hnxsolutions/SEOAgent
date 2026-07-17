"""Tests for the PageSpeed Insights parser against the real PSI v5 schema.

The fixture mirrors the documented Lighthouse response shape (field paths + units)
— it is a parser fixture, never presented as a real project's live metrics.
"""
from app.pagespeed.parser import extract_opportunities, parse_pagespeed


PSI_FIXTURE = {
    "loadingExperience": {
        "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3200},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 12},  # CrUX = CLS*100
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 240},
        }
    },
    "lighthouseResult": {
        "categories": {
            "performance": {"score": 0.62},
            "accessibility": {"score": 0.91},
            "best-practices": {"score": 0.83},
            "seo": {"score": 0.95},
        },
        "audits": {
            "largest-contentful-paint": {"numericValue": 4200.0, "displayValue": "4.2 s"},
            "cumulative-layout-shift": {"numericValue": 0.14, "displayValue": "0.14"},
            "interaction-to-next-paint": {"numericValue": 260.0},
            "total-blocking-time": {"numericValue": 510.0},
            "first-contentful-paint": {"numericValue": 1800.0},
            "speed-index": {"numericValue": 5200.0},
            "server-response-time": {"numericValue": 620.0, "displayValue": "Root document took 620 ms", "score": 0.5},
            "unused-javascript": {
                "title": "Reduce unused JavaScript", "description": "Remove unused JS...",
                "score": 0.3, "displayValue": "Potential savings of 120 KiB",
                "details": {"type": "opportunity", "overallSavingsMs": 900},
            },
            "modern-image-formats": {
                "title": "Serve images in next-gen formats", "score": 0.4,
                "details": {"type": "opportunity", "overallSavingsMs": 450},
            },
            "uses-long-cache-ttl": {
                "title": "Serve static assets with an efficient cache policy", "score": 0.5,
                "displayValue": "12 resources found",
                "details": {"type": "table"},
            },
            "passing-opportunity": {
                "title": "Already good", "score": 1.0,
                "details": {"type": "opportunity"},  # no savings, passing -> excluded
            },
        },
    },
}


def test_parses_category_scores_0_100():
    p = parse_pagespeed(PSI_FIXTURE)
    assert p["performance_score"] == 62.0
    assert p["accessibility_score"] == 91.0
    assert p["best_practices_score"] == 83.0
    assert p["seo_score"] == 95.0


def test_parses_core_web_vitals_lab():
    p = parse_pagespeed(PSI_FIXTURE)
    assert p["lcp_ms"] == 4200.0
    assert p["cls"] == 0.14
    assert p["inp_ms"] == 260.0
    assert p["tbt_ms"] == 510.0
    assert p["fcp_ms"] == 1800.0
    assert p["speed_index_ms"] == 5200.0
    assert p["ttfb_ms"] == 620.0


def test_parses_field_data_and_normalizes_cls():
    p = parse_pagespeed(PSI_FIXTURE)
    assert p["field_lcp_ms"] == 3200.0
    assert p["field_cls"] == 0.12  # 12 / 100
    assert p["field_inp_ms"] == 240.0


def test_opportunities_sorted_by_savings_and_excludes_passing():
    p = parse_pagespeed(PSI_FIXTURE)
    ids = [o["id"] for o in p["opportunities"]]
    assert ids[:2] == ["unused-javascript", "modern-image-formats"]  # 900 then 450
    assert "passing-opportunity" not in ids


def test_diagnostics_include_failing_audits_with_display_value():
    p = parse_pagespeed(PSI_FIXTURE)
    diag_ids = [d["id"] for d in p["diagnostics"]]
    assert "uses-long-cache-ttl" in diag_ids
    assert "server-response-time" in diag_ids


def test_missing_fields_stay_none_not_fabricated():
    p = parse_pagespeed({"lighthouseResult": {"categories": {}, "audits": {}}})
    assert p["performance_score"] is None
    assert p["lcp_ms"] is None
    assert p["opportunities"] == []
    assert p["diagnostics"] == []

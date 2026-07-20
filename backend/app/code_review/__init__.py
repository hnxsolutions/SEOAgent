"""Code review analysis helpers (pure, no I/O).

Turns a generated SEO patch into the reviewer-facing detail: a line-by-line diff,
the WHY reasoning, the predicted (never measured) SEO outcome, and a risk score.
"""
from app.code_review.analysis import (
    SURFACE_RISK,
    build_file_review,
    diff_lines,
    estimate_impact,
    explanation_for,
    expected_result_for,
    risk_for_surface,
)

__all__ = [
    "SURFACE_RISK",
    "build_file_review",
    "diff_lines",
    "estimate_impact",
    "explanation_for",
    "expected_result_for",
    "risk_for_surface",
]

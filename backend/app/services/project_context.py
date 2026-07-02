"""Shared project-context formatting helpers."""
from __future__ import annotations

from typing import Any


BUSINESS_CONTEXT_LABELS = {
    "business_name": "Business name",
    "industry": "Industry",
    "target_location": "Target location",
    "target_audience": "Target audience",
    "primary_services": "Services",
    "target_keywords": "Target keywords",
    "seo_goal": "SEO goal",
    "brand_tone": "Brand tone",
}


LIST_FIELDS = {"primary_services", "target_keywords", "competitor_urls", "keywords"}
MISSING_VALUE = "Not provided"


def project_business_context(project: Any, *, missing_value: str = MISSING_VALUE) -> dict[str, Any]:
    """Return deterministic client-facing business context for a project."""
    return {
        "business_name": _text(getattr(project, "business_name", None), missing_value),
        "industry": _text(getattr(project, "industry", None), missing_value),
        "target_location": _text(getattr(project, "target_location", None), missing_value),
        "target_audience": _text(getattr(project, "target_audience", None), missing_value),
        "primary_services": _list_or_missing(getattr(project, "primary_services", None), missing_value),
        "target_keywords": _list_or_missing(
            getattr(project, "target_keywords", None) or getattr(project, "keywords", None),
            missing_value,
        ),
        "seo_goal": _text(getattr(project, "seo_goal", None), missing_value),
        "brand_tone": _text(getattr(project, "brand_tone", None), missing_value),
    }


def has_business_context(context: dict[str, Any], *, missing_value: str = MISSING_VALUE) -> bool:
    for value in context.values():
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value and value != missing_value:
            return True
    return False


def business_context_items(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "label": BUSINESS_CONTEXT_LABELS.get(key, key.replace("_", " ").title()),
            "value": value,
        }
        for key, value in context.items()
    ]


def project_context_prompt(project: Any) -> str:
    """Return prompt-safe context text with explicit manual competitor limitations."""
    context = project_business_context(project)
    lines = ["Project context for this SEO run:"]
    for key, label in BUSINESS_CONTEXT_LABELS.items():
        value = context[key]
        if isinstance(value, list):
            rendered = ", ".join(value) if value else MISSING_VALUE
        else:
            rendered = value
        lines.append(f"- {label}: {rendered}")

    competitor_urls = _clean_list(getattr(project, "competitor_urls", None))
    if competitor_urls:
        lines.append("- Competitor URLs: " + ", ".join(competitor_urls))
        lines.append(
            "- Competitor limitation: these URLs are manually provided context only. "
            "Do not crawl them, analyze them, or claim competitor findings."
        )
    else:
        lines.append("- Competitor URLs: Not provided; no competitor analysis is available.")

    return "\n".join(lines)


def _text(value: Any, missing_value: str) -> str:
    text = str(value or "").strip()
    return text or missing_value


def _list_or_missing(value: Any, missing_value: str) -> list[str] | str:
    items = _clean_list(value)
    return items if items else missing_value


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = [value]
    return [str(item).strip() for item in raw_values if str(item or "").strip()]

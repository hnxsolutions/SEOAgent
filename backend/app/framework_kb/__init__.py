"""Framework Knowledge Base.

A declarative, queryable registry of how each web framework/CMS handles SEO. It
is the single source of truth for framework-aware decisions: the Planner, SEO
Brain, Framework Strategy Engine, and patch generator all *query* this KB rather
than hardcoding framework rules.

Nothing here executes I/O or mutates a site — it only describes capabilities so
the SEO engine can pick the right, SEO-safe approach for the detected stack.
"""
from app.framework_kb.registry import (
    FrameworkProfile,
    TaskAction,
    get_framework_profile,
    known_frameworks,
    normalize_framework_key,
    task_action_for,
)

__all__ = [
    "FrameworkProfile",
    "TaskAction",
    "get_framework_profile",
    "known_frameworks",
    "normalize_framework_key",
    "task_action_for",
]

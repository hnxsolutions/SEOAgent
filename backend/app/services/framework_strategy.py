"""Framework Strategy Engine.

Composes the Technology Fingerprint with the Framework Knowledge Base to produce,
automatically (no manual selection), the SEO strategy for a project:

  * primary / secondary framework + rendering mode + recommended SEO strategy
  * per-technology business insights (purpose, SEO impact ★, performance impact ★,
    recommended improvement)
  * framework recommendations ("already supports automatic metadata", "image
    optimization available but unused", ...)
  * explained readiness scores

This module holds no framework rules of its own — it *queries* the Knowledge
Base. It never modifies a site; it only decides which SEO-safe approach applies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.framework_kb import get_framework_profile, normalize_framework_key

# Human explanations for each readiness score.
_SCORE_EXPLANATIONS = {
    "framework_health": "How confidently we detected a well-supported framework — higher means the stack is well understood and patchable.",
    "seo_readiness": "How many core SEO signals (title, description, canonical, Open Graph, schema, sitemap, robots) are already present.",
    "performance_readiness": "Signals that the site loads fast — CDN, compression, caching and modern image formats.",
    "accessibility": "Basic accessibility signals visible in the HTML — language, viewport, image alt text and landmarks.",
    "security": "Transport and header security — HTTPS, HSTS, CSP and related protections.",
    "indexability": "Whether search engines are allowed to index the site — no blocking robots rules or noindex, and a reachable sitemap.",
    "maintainability": "How cleanly SEO changes can be made on this stack without risking design or business logic.",
}


class FrameworkStrategyEngine:
    """Pure composition of fingerprint data + Knowledge Base. No I/O."""

    def build(
        self,
        *,
        primary_framework: Optional[str],
        primary_cms: Optional[str],
        rendering: Optional[str],
        technologies: List[dict],
        scores: Dict[str, Any],
    ) -> Dict[str, Any]:
        primary_key = self._primary_key(primary_framework, primary_cms, technologies)
        secondary = self._secondary(primary_key, technologies)
        profile = get_framework_profile(primary_key) if primary_key else None

        strategy: Dict[str, Any] = {
            "primary_framework": profile.display_name if profile else (primary_framework or primary_cms),
            "primary_framework_key": primary_key,
            "secondary_framework": secondary,
            "rendering": (profile.rendering if profile else rendering),
            "recommended_strategy": self._recommended_strategy(profile),
            "profile": profile.as_dict() if profile else None,
            "recommendations": self._recommendations(profile, technologies, scores),
            "explained_scores": self._explained_scores(scores),
        }
        return strategy

    def technology_insights(self, technologies: List[dict]) -> List[dict]:
        """Attach business-language purpose + impact ratings to detected tech."""
        out: List[dict] = []
        for t in technologies:
            profile = None
            if t.get("category") in ("framework", "cms", "js_framework"):
                profile = get_framework_profile(t.get("name"))
            insight = {
                "category": t.get("category"),
                "name": t.get("name"),
                "confidence": t.get("confidence"),
                "evidence": t.get("evidence", []),
            }
            if profile:
                insight.update({
                    "purpose": profile.purpose,
                    "seo_impact": profile.seo_impact,
                    "performance_impact": profile.performance_impact,
                    "seo_impact_reason": profile.seo_impact_reason,
                    "performance_impact_reason": profile.performance_impact_reason,
                })
            else:
                insight.update(self._generic_insight(t.get("category"), t.get("name")))
            out.append(insight)
        return out

    # -- selection ----------------------------------------------------------

    @staticmethod
    def _primary_key(primary_framework, primary_cms, technologies) -> Optional[str]:
        # A CMS (WordPress/Shopify) is the controlling stack even if a JS lib is present.
        for candidate in (primary_cms, primary_framework):
            key = normalize_framework_key(candidate)
            if key:
                return key
        # Fall back to the highest-confidence framework/cms technology.
        ranked = sorted(
            [t for t in technologies if t.get("category") in ("cms", "framework")],
            key=lambda t: t.get("confidence", 0), reverse=True,
        )
        for t in ranked:
            key = normalize_framework_key(t.get("name"))
            if key:
                return key
        return None

    @staticmethod
    def _secondary(primary_key, technologies) -> Optional[str]:
        for t in sorted(technologies, key=lambda t: t.get("confidence", 0), reverse=True):
            if t.get("category") in ("framework", "js_framework", "cms"):
                key = normalize_framework_key(t.get("name"))
                if key and key != primary_key:
                    profile = get_framework_profile(key)
                    return profile.display_name if profile else t.get("name")
        return None

    @staticmethod
    def _recommended_strategy(profile) -> str:
        if not profile:
            return ("Stack not confidently identified — apply generic, head-only SEO changes and "
                    "keep everything gated behind manual review.")
        return (f"Use {profile.display_name}'s native SEO surfaces: {profile.metadata_system} "
                f"Sitemap via {profile.sitemap_system} Robots via {profile.robots_system}")

    # -- recommendations ----------------------------------------------------

    def _recommendations(self, profile, technologies, scores) -> List[str]:
        recs: List[str] = []
        if not profile:
            recs.append("Technology could not be confidently identified — SEO changes will stay head-only and manually reviewed.")
            return recs

        names = {(t.get("name") or "").lower() for t in technologies}
        has_image_opt = any(t.get("category") == "image_system" for t in technologies)
        has_schema = any(t.get("name") == "JSON-LD Schema.org" for t in technologies)
        has_sitemap = any(t.get("category") == "sitemap" for t in technologies)

        if profile.supports_auto_metadata:
            recs.append(f"This website already supports automatic metadata via {profile.metadata_system.split('.')[0].strip()}.")
        if profile.supports_ssr:
            recs.append("This framework supports server-side rendering, which helps Google crawl and index pages.")
        if profile.supports_image_optimization and not has_image_opt:
            recs.append("Image optimization is available on this stack but appears unused — enabling it will improve performance.")
        elif profile.supports_image_optimization and has_image_opt:
            recs.append("Image optimization is available and in use.")
        if profile.supports_structured_data and not has_schema:
            recs.append("This framework supports structured data (schema) — adding JSON-LD can win rich results.")
        elif profile.supports_structured_data and has_schema:
            recs.append("This framework already supports structured data and JSON-LD was detected.")
        if profile.supports_auto_sitemap and not has_sitemap:
            recs.append("Automatic sitemap generation is available but no sitemap was detected — enable it.")
        if scores.get("seo_readiness", 100) < 80:
            recs.append("Some core SEO tags are missing — the planner will generate framework-safe patches to add them.")
        return recs

    def _explained_scores(self, scores: Dict[str, Any]) -> List[dict]:
        out = []
        # Maintainability is derived from how safely this stack can be edited.
        for key in ("framework_health", "seo_readiness", "performance_readiness",
                    "accessibility", "security", "indexability"):
            if key in scores:
                out.append({
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "value": scores.get(key),
                    "explanation": _SCORE_EXPLANATIONS.get(key, ""),
                })
        return out

    @staticmethod
    def _generic_insight(category, name) -> dict:
        blurbs = {
            "hosting": (4, 4, "Where the site runs; good hosting means fast, reliable delivery to users and crawlers."),
            "cdn": (3, 5, "Serves content from servers near each visitor, improving load time worldwide."),
            "image_system": (3, 5, "Optimizes images so pages load faster — a Core Web Vitals win."),
            "analytics": (2, 2, "Measures traffic and behavior; no direct ranking impact but informs SEO decisions."),
            "seo": (5, 2, "A core on-page SEO signal search engines read directly."),
            "schema": (4, 2, "Structured data that can earn rich results in search."),
            "security": (3, 3, "Security signals like HTTPS are a lightweight ranking factor and build trust."),
            "caching": (2, 4, "Caching reduces server work and speeds up repeat visits."),
            "web_server": (2, 3, "The server software delivering pages."),
            "language": (2, 2, "The programming language powering the site."),
            "rendering": (5, 3, "How pages are built; server rendering helps search engines see full content."),
            "styling": (1, 2, "How the site is styled; minimal direct SEO impact."),
            "fonts": (1, 3, "Web fonts; optimizing their loading helps performance."),
        }
        seo, perf, purpose = blurbs.get(category, (2, 2, "Part of the website's technology stack."))
        return {"purpose": purpose, "seo_impact": seo, "performance_impact": perf,
                "seo_impact_reason": purpose, "performance_impact_reason": purpose}

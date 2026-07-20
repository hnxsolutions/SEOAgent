"""Framework Knowledge Base + Framework Strategy Engine tests (pure, no I/O)."""
from app.framework_kb import (
    get_framework_profile,
    known_frameworks,
    normalize_framework_key,
    task_action_for,
)
from app.services.framework_strategy import FrameworkStrategyEngine


# -- Knowledge Base -----------------------------------------------------------

def test_normalize_framework_aliases():
    assert normalize_framework_key("Next.js") == "nextjs"
    assert normalize_framework_key("nextjs_app_router") == "nextjs"
    assert normalize_framework_key("WordPress") == "wordpress"
    assert normalize_framework_key("Squarespace") == "custom"
    assert normalize_framework_key(None) is None
    assert normalize_framework_key("totally-unknown-xyz") is None


def test_task_action_is_framework_specific():
    nextjs = task_action_for("Next.js", "metadata_rewrite")
    wp = task_action_for("WordPress", "metadata_rewrite")
    assert nextjs and "generateMetadata" in nextjs.action
    assert wp and ("Yoast" in wp.action or "Rank Math" in wp.action)
    # Same generic task, different framework -> different action.
    assert nextjs.action != wp.action


def test_registry_profiles_are_complete():
    for key in known_frameworks():
        p = get_framework_profile(key)
        assert p and p.display_name and p.metadata_system
        assert 1 <= p.seo_impact <= 5 and 1 <= p.performance_impact <= 5
        assert isinstance(p.as_dict()["capabilities"], dict)


# -- Strategy Engine ----------------------------------------------------------

_NEXT_TECHS = [
    {"category": "framework", "name": "Next.js", "confidence": 97, "evidence": ["/_next/"]},
    {"category": "js_framework", "name": "React", "confidence": 95, "evidence": ["meta-framework"]},
    {"category": "image_system", "name": "next/image", "confidence": 90, "evidence": ["/_next/image"]},
    {"category": "hosting", "name": "Vercel", "confidence": 85, "evidence": ["X-Vercel-Id"]},
]


def test_strategy_selects_primary_and_recommends():
    engine = FrameworkStrategyEngine()
    s = engine.build(
        primary_framework="Next.js", primary_cms=None, rendering="SSR/SSG",
        technologies=_NEXT_TECHS,
        scores={"seo_readiness": 100, "performance_readiness": 80, "framework_health": 97},
    )
    assert s["primary_framework"] == "Next.js"
    assert s["primary_framework_key"] == "nextjs"
    assert s["secondary_framework"] in ("React",)
    assert "generateMetadata" in s["recommended_strategy"] or "Metadata API" in s["recommended_strategy"]
    joined = " ".join(s["recommendations"]).lower()
    assert "server-side rendering" in joined
    assert "structured data" in joined  # supports schema; none detected -> recommend adding


def test_cms_wins_over_js_library_as_primary():
    engine = FrameworkStrategyEngine()
    s = engine.build(
        primary_framework=None, primary_cms="WordPress", rendering="Server-rendered",
        technologies=[{"category": "cms", "name": "WordPress", "confidence": 96, "evidence": []}],
        scores={},
    )
    assert s["primary_framework_key"] == "wordpress"


def test_technology_insights_have_impact_ratings():
    engine = FrameworkStrategyEngine()
    insights = engine.technology_insights(_NEXT_TECHS)
    nextjs = next(i for i in insights if i["name"] == "Next.js")
    assert nextjs["seo_impact"] == 5 and nextjs["purpose"]
    # non-framework tech still gets a generic rating
    hosting = next(i for i in insights if i["name"] == "Vercel")
    assert 1 <= hosting["seo_impact"] <= 5


def test_explained_scores_are_labeled():
    engine = FrameworkStrategyEngine()
    s = engine.build(primary_framework="Astro", primary_cms=None, rendering="SSG",
                     technologies=[], scores={"seo_readiness": 90, "security": 40})
    labels = {e["key"] for e in s["explained_scores"]}
    assert "seo_readiness" in labels and "security" in labels
    for e in s["explained_scores"]:
        assert e["explanation"]


def test_unknown_stack_degrades_gracefully():
    engine = FrameworkStrategyEngine()
    s = engine.build(primary_framework=None, primary_cms=None, rendering=None,
                     technologies=[], scores={})
    assert s["primary_framework_key"] is None
    assert s["recommendations"]  # explains it stays head-only / manual

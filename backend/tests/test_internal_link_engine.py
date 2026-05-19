from uuid import uuid4

from app.internal_links.engine import (
    AuditSignal,
    InternalLinkRulesEngine,
    LinkEdge,
    LinkPage,
    SemanticPair,
)
from app.models.internal_linking import InternalLinkRecommendationType


def make_page(path, **overrides):
    values = {
        "id": uuid4(),
        "url": f"https://example.com{path}",
        "normalized_url": f"https://example.com{path}",
        "title": path.strip("/").replace("-", " ").title() or "Home",
        "h1": [path.strip("/").replace("-", " ").title() or "Home"],
        "word_count": 450,
        "internal_links": 2,
        "depth": 1,
        "text_content": "This is a detailed source page with enough editorial context for a link.",
    }
    values.update(overrides)
    return LinkPage(**values)


def test_orphan_pages_are_prioritized():
    source = make_page("/source", depth=0)
    target = make_page("/target", depth=2)
    pair = SemanticPair(source_page_id=source.id, target_page_id=target.id, similarity=0.86)

    recommendations = InternalLinkRulesEngine().generate([source, target], [], [], [pair])

    assert recommendations
    assert recommendations[0].target_page_id == target.id
    assert recommendations[0].recommendation_type == InternalLinkRecommendationType.orphan_support
    assert recommendations[0].priority_score >= 60


def test_existing_internal_links_are_not_recommended():
    source = make_page("/source")
    target = make_page("/target")
    link = LinkEdge(source_page_id=source.id, normalized_url=target.normalized_url, link_text="Target")
    pair = SemanticPair(source_page_id=source.id, target_page_id=target.id, similarity=0.95)

    recommendations = InternalLinkRulesEngine().generate([source, target], [link], [], [pair])

    assert all(
        not (rec.source_page_id == source.id and rec.target_page_id == target.id)
        for rec in recommendations
    )


def test_semantic_related_recommendation_generation():
    source = make_page("/source", depth=0)
    target = make_page("/target")
    linker_one = make_page("/one")
    linker_two = make_page("/two")
    links = [
        LinkEdge(source_page_id=linker_one.id, normalized_url=target.normalized_url, link_text="Target"),
        LinkEdge(source_page_id=linker_two.id, normalized_url=target.normalized_url, link_text="Target"),
    ]
    pair = SemanticPair(source_page_id=source.id, target_page_id=target.id, similarity=0.91)

    recommendations = InternalLinkRulesEngine().generate(
        [source, target, linker_one, linker_two],
        links,
        [],
        [pair],
    )

    semantic_recommendation = next(
        rec for rec in recommendations
        if rec.source_page_id == source.id and rec.target_page_id == target.id
    )
    assert semantic_recommendation.recommendation_type == InternalLinkRecommendationType.semantic_related
    assert semantic_recommendation.confidence_score > 70


def test_duplicate_recommendation_keys_are_prevented():
    source = make_page("/source", depth=0)
    target = make_page("/target", depth=2)
    pair = SemanticPair(source_page_id=source.id, target_page_id=target.id, similarity=0.9)
    existing_key = {(source.id, target.id, InternalLinkRecommendationType.orphan_support)}

    recommendations = InternalLinkRulesEngine().generate(
        [source, target],
        [],
        [],
        [pair],
        existing_recommendation_keys=existing_key,
    )

    assert recommendations == []


def test_audit_issue_support_type_is_used_for_audit_signals():
    source = make_page("/source", depth=0)
    target = make_page("/deep-target", depth=3)
    pair = SemanticPair(source_page_id=source.id, target_page_id=target.id, similarity=0.82)
    signal = AuditSignal(page_id=target.id, issue_type="weak_internal_link_depth")

    recommendations = InternalLinkRulesEngine().generate([source, target], [], [signal], [pair])

    assert recommendations[0].recommendation_type == InternalLinkRecommendationType.audit_issue_support
    assert "weak_internal_link_depth" in recommendations[0].reason


def test_anchor_text_uses_meaningful_slug_segment():
    target = make_page(
        "/tag/change/page/1/",
        title="Quotes to Scrape",
        h1=["Quotes to Scrape"],
    )

    assert InternalLinkRulesEngine().suggest_anchor_text(target) == "Change"

from uuid import uuid4

from app.audit.rules import AuditLink, AuditPage, SEOAuditRulesEngine


def make_page(**overrides):
    values = {
        "id": uuid4(),
        "url": "https://example.com/page",
        "normalized_url": "https://example.com/page",
        "title": "A useful and unique title for search",
        "title_length": 36,
        "meta_description": "This is a useful meta description with enough detail for the page.",
        "meta_description_length": 65,
        "h1": ["Useful page"],
        "canonical_url_normalized": "https://example.com/page",
        "noindex": False,
        "word_count": 500,
        "total_images": 1,
        "images_without_alt": 0,
        "external_links": 3,
        "has_schema_markup": True,
        "has_og_tags": True,
        "depth": 1,
        "status_code": 200,
    }
    values.update(overrides)
    return AuditPage(**values)


def issue_types(result):
    return {issue.issue_type for issue in result.issues}


def test_rule_detection_for_core_page_issues():
    page = make_page(
        title="",
        title_length=0,
        meta_description="",
        meta_description_length=0,
        h1=[],
        canonical_url_normalized=None,
        noindex=True,
        word_count=120,
        total_images=3,
        images_without_alt=2,
        external_links=120,
        has_schema_markup=False,
        has_og_tags=False,
    )
    result = SEOAuditRulesEngine().analyze([page], [], seed_url=page.url)

    assert {
        "missing_title",
        "missing_meta_description",
        "missing_h1",
        "missing_canonical",
        "noindex_page",
        "thin_content",
        "missing_image_alt_text",
        "excessive_external_links",
        "missing_schema",
        "missing_open_graph_tags",
    }.issubset(issue_types(result))
    assert result.page_scores[0].score < 50


def test_scoring_penalizes_by_issue_severity():
    page = make_page(
        title="Tiny",
        title_length=4,
        meta_description="short",
        meta_description_length=5,
        word_count=50,
        has_schema_markup=False,
        has_og_tags=False,
    )
    result = SEOAuditRulesEngine().analyze([page], [], seed_url=page.url)

    assert result.page_scores[0].score == max(0, 100 - sum(issue.score_impact for issue in result.issues))
    assert result.site_score == result.page_scores[0].score


def test_duplicate_titles_and_meta_descriptions_are_detected():
    page_one = make_page(url="https://example.com/a", normalized_url="https://example.com/a")
    page_two = make_page(url="https://example.com/b", normalized_url="https://example.com/b")

    result = SEOAuditRulesEngine().analyze([page_one, page_two], [], seed_url=page_one.url)

    duplicate_issues = [issue for issue in result.issues if issue.issue_type in {"duplicate_title", "duplicate_meta_description"}]
    assert len([issue for issue in duplicate_issues if issue.issue_type == "duplicate_title"]) == 2
    assert len([issue for issue in duplicate_issues if issue.issue_type == "duplicate_meta_description"]) == 2


def test_orphan_pages_and_weak_internal_depth_are_detected():
    seed = make_page(url="https://example.com/", normalized_url="https://example.com/", depth=0)
    deep_page = make_page(
        url="https://example.com/deep",
        normalized_url="https://example.com/deep",
        depth=3,
    )

    result = SEOAuditRulesEngine().analyze([seed, deep_page], [], seed_url=seed.url)

    assert "orphan_page" in issue_types(result)
    assert "weak_internal_link_depth" in issue_types(result)


def test_broken_internal_links_are_detected_on_source_page():
    source = make_page(url="https://example.com/", normalized_url="https://example.com/", depth=0)
    target = make_page(url="https://example.com/missing", normalized_url="https://example.com/missing")
    link = AuditLink(
        source_page_id=source.id,
        normalized_url=target.normalized_url,
        link_type="internal",
        status_code=404,
        is_broken=True,
    )

    result = SEOAuditRulesEngine().analyze([source, target], [link], seed_url=source.url)

    broken_issue = next(issue for issue in result.issues if issue.issue_type == "broken_internal_links")
    assert broken_issue.page_id == source.id
    assert broken_issue.severity.value == "critical"

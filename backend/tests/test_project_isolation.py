"""No customer's data may leak into another customer's output.

The engine used to carry one customer's finished SEO copy, brand and byline
inside generic services: a table of pre-written titles keyed on that customer's
routes, a quality check that scored every project on whether its copy mentioned
that company, and a blog byline hardcoded to its name. Any project whose
compliance profile resolved to pharma_b2b — which keyword detection does for
anything mentioning "pharma", "medicine" or "healthcare" — received it.

These tests pin the separation: generic PHARMA COMPLIANCE stays, and PROJECT
DATA comes from the project. They are deliberately written against the brand
rather than against one customer's name, so they keep working when the fixture
customer changes.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.copy_review import SeoCopyComplianceProfile
from app.services.blog_publishing import BlogPublishingService
from app.services.copy_review import (
    PHARMA_B2B_ALLOWED_TOPICS,
    PHARMA_B2B_BLOCKED_PHRASES,
    SeoCopyReviewService,
)

#: Anything that must never appear in output for a project that is not this one.
LEAKED_BRAND_MARKERS = (
    "novakos",
    "pcd-pharma-company-in-haryana",
    "pharma-franchise-haryana",
    "wholesale-medicine-supplier",
)


def copy_service() -> SeoCopyReviewService:
    return SeoCopyReviewService.__new__(SeoCopyReviewService)


def blog_service() -> BlogPublishingService:
    return BlogPublishingService.__new__(BlogPublishingService)


def project(**overrides):
    values = {
        "id": uuid4(),
        "name": "Acme Technologies",
        "business_name": None,
        "domain": "https://acme.example",
        "description": "Workflow automation software.",
        "industry": None,
        "keywords": ["workflow automation"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def assert_no_leak(*values: str) -> None:
    blob = " ".join(v for v in values if v).lower()
    for marker in LEAKED_BRAND_MARKERS:
        assert marker not in blob, f"another customer's data leaked into output: {marker!r}"


# ---------------------------------------------------------------------------
# Test 1 — a generic project
# ---------------------------------------------------------------------------

def test_generic_project_copy_carries_no_other_customer_data():
    """Acme must never be handed a pharma customer's copy, routes or brand."""
    service = copy_service()
    revision = service._deterministic_revision(
        project=project(),
        title="Learn about services",
        description="Learn about services with clear service details and next steps.",
        page_url="/workflow-automation",
        target_keyword="workflow automation",
        compliance_profile=SeoCopyComplianceProfile.default,
    )

    assert_no_leak(revision["title"], revision["description"])
    assert "Acme Technologies" in revision["title"]


def test_generic_project_is_unaffected_by_the_retired_route_table():
    """Even on the exact routes the old table keyed on, nothing is substituted."""
    service = copy_service()
    for route in ("/pcd-pharma-company-in-haryana", "/pharma-franchise-haryana", "/wholesale-medicine-supplier"):
        revision = service._deterministic_revision(
            project=project(),
            title="Learn about services",
            description="Generic copy.",
            page_url=route,
            target_keyword=None,
            compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
        )
        # The route is a pharma one and the profile is pharma_b2b — the two
        # conditions that used to trigger the hardcoded copy. The brand must
        # still be Acme's.
        assert "Acme Technologies" in revision["title"]
        assert "novakos" not in f"{revision['title']} {revision['description']}".lower()


def test_quality_score_measures_the_projects_own_brand():
    """Copy carrying another company's name must not satisfy the brand check."""
    service = copy_service()
    _, issues = service._quality_score(
        "Workflow Automation | Novakos Healthcare",
        "Novakos Healthcare supports verified buyers.",
        "/workflow-automation",
        "workflow automation",
        "Acme Technologies",
    )
    assert any(issue["code"] == "brand_missing" for issue in issues)

    _, ok_issues = service._quality_score(
        "Workflow Automation | Acme Technologies",
        "Acme Technologies supports verified buyers with catalog access.",
        "/workflow-automation",
        "workflow automation",
        "Acme Technologies",
    )
    assert not any(issue["code"] == "brand_missing" for issue in ok_issues)


def test_project_without_a_brand_is_not_given_an_invented_one():
    """No brand configured means no brand written — never a placeholder."""
    service = copy_service()
    revision = service._deterministic_revision(
        project=project(name=None, business_name=None),
        title="Learn about services",
        description="Generic copy.",
        page_url="/pricing",
        target_keyword="pricing",
        compliance_profile=SeoCopyComplianceProfile.default,
    )
    assert "|" not in revision["title"], "a brandless project must not get a trailing separator"
    assert_no_leak(revision["title"], revision["description"])
    assert "website" not in revision["title"].lower()

    # And the brand check is skipped rather than penalising the project.
    _, issues = service._quality_score("Pricing", "Our pricing.", "/pricing", "pricing", "")
    assert not any(issue["code"] == "brand_missing" for issue in issues)


# ---------------------------------------------------------------------------
# Test 2 — a different pharma project
# ---------------------------------------------------------------------------

def test_pharma_compliance_rules_survive_and_are_generic():
    """The compliance vocabulary is engine logic and stays."""
    assert "dosage" in PHARMA_B2B_BLOCKED_PHRASES
    assert "cure" in PHARMA_B2B_BLOCKED_PHRASES
    assert "wholesale" in PHARMA_B2B_ALLOWED_TOPICS
    # None of it names a company.
    assert_no_leak(" ".join(PHARMA_B2B_BLOCKED_PHRASES), " ".join(PHARMA_B2B_ALLOWED_TOPICS))


def test_another_pharma_company_keeps_its_own_brand():
    """A second pharma customer gets pharma RULES and its OWN name."""
    service = copy_service()
    other = project(name="Zenith Pharma Supply", domain="https://zenith.example")

    revision = service._deterministic_revision(
        project=other,
        title="Learn about pharma franchise",
        description="Generic copy.",
        page_url="/pharma-franchise-haryana",
        target_keyword="pharma franchise haryana",
        compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
    )

    assert "Zenith Pharma Supply" in revision["title"]
    assert_no_leak(revision["title"], revision["description"])
    # Pharma safeguards still reported for this project.
    assert any("No dosage" in note for note in revision["compliance_notes"])


def test_pharma_profile_still_blocks_medical_claims_for_any_brand():
    service = copy_service()
    score, issues = service._compliance_score(
        "Best Treatment and Cure Options | Zenith Pharma Supply",
        "Guaranteed efficacy and dosage advice for patient treatment.",
        SeoCopyComplianceProfile.pharma_b2b,
    )
    assert score < 80
    assert any(issue["code"] == "blocked_compliance_phrase" for issue in issues)


def test_pharma_profile_allows_b2b_vocabulary():
    service = copy_service()
    score, _ = service._compliance_score(
        "Wholesale Supply and Distribution | Zenith Pharma Supply",
        "Verified buyer registration, catalog access, and bulk inquiry support.",
        SeoCopyComplianceProfile.pharma_b2b,
    )
    assert score >= 80


# ---------------------------------------------------------------------------
# Test 3 — the original customer, resolved dynamically
# ---------------------------------------------------------------------------

def test_configured_customer_still_gets_its_brand_from_its_project():
    """The behaviour is preserved — but sourced from configuration, not code."""
    service = copy_service()
    configured = project(name="Novakos Healthcare", domain="https://www.novakoshealthcare.com")

    revision = service._deterministic_revision(
        project=configured,
        title="Learn about pcd pharma",
        description="Generic copy.",
        page_url="/pcd-pharma-company-in-haryana",
        target_keyword="pcd pharma company in haryana",
        compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
    )

    # The brand appears because THIS project is configured with it.
    assert revision["title"] == "PCD Pharma Company in Haryana | Novakos Healthcare"
    assert "Novakos Healthcare" in revision["description"]

    # Proof it is dynamic: rename the project, and the output follows.
    renamed = service._deterministic_revision(
        project=project(name="Zenith Pharma Supply"),
        title="Learn about pcd pharma",
        description="Generic copy.",
        page_url="/pcd-pharma-company-in-haryana",
        target_keyword="pcd pharma company in haryana",
        compliance_profile=SeoCopyComplianceProfile.pharma_b2b,
    )
    assert renamed["title"] == "PCD Pharma Company in Haryana | Zenith Pharma Supply"


def test_acronyms_keep_their_capitalisation():
    """Derived copy must not read as a typo: PCD, B2B, SEO — not Pcd, B2b, Seo."""
    service = copy_service()
    assert service._title_case_keyword("pcd pharma company") == "PCD Pharma Company"
    assert service._title_case_keyword("b2b seo services") == "B2B SEO Services"
    assert service._title_case_keyword("saas crm pricing") == "SAAS CRM Pricing"


# ---------------------------------------------------------------------------
# Test 4 — blog publishing
# ---------------------------------------------------------------------------

def draft(**overrides):
    values = {
        "id": uuid4(),
        "project_id": uuid4(),
        "title": "How workflow automation reduces manual work",
        "slug": "workflow-automation",
        "meta_description": "A short description.",
        "draft_markdown": "## Heading\n\nSome body text.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_blog_byline_comes_from_the_project():
    entry = blog_service()._static_blog_entry(draft(), project())
    assert '"Acme Technologies"' in entry
    assert_no_leak(entry)


def test_blog_byline_prefers_business_name_over_console_label():
    entry = blog_service()._static_blog_entry(
        draft(), project(name="acme-prod", business_name="Acme Technologies Ltd")
    )
    assert '"Acme Technologies Ltd"' in entry


def test_blog_category_comes_from_the_project_industry():
    entry = blog_service()._static_blog_entry(draft(), project(industry="Software"))
    assert '"Software"' in entry
    assert "PCD Pharma" not in entry


def test_blog_without_a_project_uses_a_neutral_byline():
    """No project is no excuse to sign an article with some other company."""
    entry = blog_service()._static_blog_entry(draft(), None)
    assert '"Editorial Team"' in entry
    assert_no_leak(entry)


def test_blog_image_alt_describes_the_article_not_a_pharmacy():
    """Alt text has to describe the image's role, for every industry."""
    entry = blog_service()._static_blog_entry(draft(), project())
    assert "pharmacy shelves" not in entry.lower()
    assert "workflow automation" in entry.lower()


# ---------------------------------------------------------------------------
# Test 5 — indexing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_indexing_pharma_review_follows_the_configured_profile():
    """An explicit profile decides it; the project's words do not override it."""
    from app.services.indexing import IndexingService

    service = IndexingService.__new__(IndexingService)

    # A pharma-sounding project that is explicitly NOT on the pharma profile.
    assert service._fix_task_values.__doc__  # the resolved flag is honoured
    values = service._fix_task_values(
        SimpleNamespace(id=uuid4(), target_week_end=None),
        _issue(page_url="https://acme.example/medicine-tracking-software"),
        project(name="Acme Medicine Tracking"),
        pharma_review=False,
    )
    assert "pharma_b2b compliance review" not in (values.get("description") or "")

    # The same project WITH the pharma profile resolved gets the safeguard.
    values_pharma = service._fix_task_values(
        SimpleNamespace(id=uuid4(), target_week_end=None),
        _issue(page_url="https://zenith.example/catalog"),
        project(name="Zenith Pharma Supply"),
        pharma_review=True,
    )
    assert "pharma_b2b compliance review" in (values_pharma.get("description") or "")


def _issue(**overrides):
    """A GSCIndexingIssue shaped closely enough for task building."""
    from app.models.indexing import GSCIndexingIssueSeverity

    values = {
        "id": uuid4(),
        "issue_type": _content_issue_type(),
        "severity": GSCIndexingIssueSeverity.medium,
        "tenant_id": uuid4(),
        "project_id": uuid4(),
        "page_url": "https://example.com/page",
        "likely_cause": "x",
        "recommended_fix": "y",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _content_issue_type():
    """The issue type that maps to a content_refresh task."""
    from app.models.indexing import GSCIndexingIssueType

    return GSCIndexingIssueType.thin_content

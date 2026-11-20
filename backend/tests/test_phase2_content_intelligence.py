"""Phase 2: profile provenance, cluster graph, cannibalisation verdicts, workflows.

The properties pinned here are the ones that make the difference between an
agent that is trusted and one that is not: inference is never presented as a
stated fact, a weak guess never overwrites a human, no path reaches `published`
without an approval, and a refresh proposal cannot skip the human in the middle.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.blog import (
    BLOG_DRAFT_TRANSITIONS,
    BlogDraftStatus,
    can_transition,
)
from app.models.content_refresh import RefreshStatus
from app.models.website_profile import ProfileFieldSource
from app.services.content_clusters import CannibalisationVerdict, ContentClusterService
from app.services.content_refresh import TRANSITIONS, RefreshTransitionError
from app.services.website_profile import WebsiteProfileService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    async def flush(self):
        return None

    def add(self, _obj):
        return None


def page(url, title=None, description=None):
    return SimpleNamespace(url=url, title=title, meta_description=description)


# --------------------------------------------------------------------------
# 9-state blog workflow
# --------------------------------------------------------------------------

def test_all_nine_states_exist():
    for name in (
        "idea", "researched", "outline", "draft", "seo_validated",
        "pending_approval", "approved", "published", "monitoring",
    ):
        assert hasattr(BlogDraftStatus, name), f"{name} missing from the workflow"


def test_the_four_original_states_keep_their_spelling():
    """Existing rows must stay valid; a renamed value would need a backfill."""
    assert BlogDraftStatus.draft.value == "draft"
    assert BlogDraftStatus.approved.value == "approved"
    assert BlogDraftStatus.rejected.value == "rejected"
    assert BlogDraftStatus.published.value == "published"


def test_nothing_reaches_published_except_from_approved():
    """The safety property: no autonomous path can publish."""
    sources = [s for s, targets in BLOG_DRAFT_TRANSITIONS.items() if "published" in targets]
    assert sources == ["approved"]


@pytest.mark.parametrize("illegal", [
    ("draft", "published"),
    ("idea", "draft"),
    ("outline", "approved"),
    ("seo_validated", "published"),
    ("rejected", "draft"),
    ("published", "draft"),
])
def test_illegal_transitions_are_refused(illegal):
    assert can_transition(*illegal) is False


@pytest.mark.parametrize("legal", [
    ("idea", "researched"),
    ("researched", "outline"),
    ("outline", "draft"),
    ("draft", "seo_validated"),
    ("seo_validated", "pending_approval"),
    ("pending_approval", "approved"),
    ("approved", "published"),
    ("published", "monitoring"),
])
def test_the_happy_path_is_walkable(legal):
    assert can_transition(*legal) is True


def test_rejection_is_reachable_from_every_working_state():
    for state in ("idea", "researched", "outline", "draft", "seo_validated", "pending_approval", "approved"):
        assert "rejected" in BLOG_DRAFT_TRANSITIONS[state]


def test_rejected_is_terminal():
    assert BLOG_DRAFT_TRANSITIONS["rejected"] == set()


def test_unknown_states_are_never_legal():
    assert can_transition("nonsense", "published") is False


# --------------------------------------------------------------------------
# Refresh proposal workflow
# --------------------------------------------------------------------------

def test_a_refresh_can_only_be_applied_after_approval():
    """The reason this workflow exists: no unattended rewrite of live content."""
    sources = [s for s, targets in TRANSITIONS.items() if RefreshStatus.applied.value in targets]
    assert sources == [RefreshStatus.approved.value]


def test_refresh_cannot_skip_the_human():
    assert RefreshStatus.applied.value not in TRANSITIONS[RefreshStatus.detected.value]
    assert RefreshStatus.applied.value not in TRANSITIONS[RefreshStatus.pending_approval.value]


@pytest.mark.asyncio
async def test_illegal_refresh_transition_explains_itself():
    service = ContentRefreshServiceStub()
    with pytest.raises(RefreshTransitionError) as exc:
        await service.transition_check(RefreshStatus.detected.value, RefreshStatus.verified)
    assert "cannot go from detected to verified" in str(exc.value)


class ContentRefreshServiceStub:
    """Exercises the transition rule without a database."""

    async def transition_check(self, current, target):
        if target.value not in TRANSITIONS.get(current, set()):
            raise RefreshTransitionError(
                f"A refresh proposal cannot go from {current} to {target.value}."
            )
        return True


# --------------------------------------------------------------------------
# Website knowledge profile
# --------------------------------------------------------------------------

def test_profile_reads_page_roles_from_urls():
    service = WebsiteProfileService(FakeDB())
    roles = service._page_roles([
        page("https://x.com/"),
        page("https://x.com/about", "About Us"),
        page("https://x.com/services", "Our Services"),
        page("https://x.com/contact", "Contact"),
        page("https://x.com/blog/some-post", "A post"),
    ])
    assert "about" in roles
    assert "services" in roles
    assert "contact" in roles
    assert "blog" in roles


def test_brand_terms_need_repetition_not_a_single_mention():
    """One title is a coincidence; the same suffix on three is the brand."""
    service = WebsiteProfileService(FakeDB())
    assert service._brand_terms(["Home | Acme Dental", "Services | Acme Dental"]) == ["Acme Dental"]
    assert service._brand_terms(["Home | Acme Dental"]) == []


def test_locations_are_not_claimed_from_one_mention():
    """A single footer mention is not evidence a business serves a city."""
    service = WebsiteProfileService(FakeDB())
    project = SimpleNamespace(target_location=None)
    once = service._locations([page("https://x.com/", "Dentist in Chandigarh")], project)
    assert once == []

    twice = service._locations([
        page("https://x.com/a", "Dentist in Chandigarh"),
        page("https://x.com/b", "Implants in Chandigarh"),
    ], project)
    assert twice == ["Chandigarh"]


def test_stated_location_is_used_without_inference():
    service = WebsiteProfileService(FakeDB())
    project = SimpleNamespace(target_location="Mohali")
    assert service._locations([], project) == ["Mohali"]


def test_content_hash_ignores_body_churn_but_tracks_metadata():
    """Body text changes on every build of a dynamic site; titles do not."""
    service = WebsiteProfileService(FakeDB())
    first = service._hash([page("https://x.com/", "Home", "Welcome")])
    same = service._hash([page("https://x.com/", "Home", "Welcome")])
    changed = service._hash([page("https://x.com/", "Home", "A new description")])

    assert first == same, "an unchanged site must reuse its profile"
    assert first != changed, "a changed description must trigger a rebuild"


def test_hash_is_order_independent():
    service = WebsiteProfileService(FakeDB())
    a = service._hash([page("https://x.com/a", "A"), page("https://x.com/b", "B")])
    b = service._hash([page("https://x.com/b", "B"), page("https://x.com/a", "A")])
    assert a == b


def test_profile_field_sources_are_the_three_honest_options():
    assert {s.value for s in ProfileFieldSource} == {"user", "inferred", "unknown"}


def test_to_dict_marks_confirmed_separately_from_inferred():
    service = WebsiteProfileService(FakeDB())
    profile = SimpleNamespace(
        id=uuid4(), version=2, status="completed", confidence=0.8, used_llm="yes",
        generated_at=None,
        business_name="Acme", business_type="Dental clinic", industry="Healthcare",
        niche=None, description=None, services=["implants"], products=[], locations=[],
        primary_topics=[], brand_terms=[], target_audience=None, important_pages=[],
        field_sources={"industry": "user", "business_type": "inferred"},
        field_confidence={"business_type": 0.72},
        field_evidence={"business_type": "Homepage + About"},
    )
    out = service.to_dict(profile)

    assert out["fields"]["industry"]["confirmed"] is True
    assert out["fields"]["industry"]["confidence"] is None
    assert out["fields"]["business_type"]["confirmed"] is False
    assert out["fields"]["business_type"]["confidence"] == 0.72
    assert out["fields"]["business_type"]["evidence"] == "Homepage + About"
    # A field nobody has established reads as unknown, not as an empty fact.
    assert out["fields"]["niche"]["source"] == "unknown"


# --------------------------------------------------------------------------
# Cannibalisation verdicts
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_when_nothing_covers_the_topic():
    service = ContentClusterService(FakeDB())
    service._draft_titles = _async([])
    service._topic_titles = _async([])
    service._page_titles = _async([])

    result = await service.check_cannibalisation(uuid4(), uuid4(), "a brand new subject")

    assert result["verdict"] == CannibalisationVerdict.CLEAR
    assert result["conflict"] is None


@pytest.mark.asyncio
async def test_clash_with_published_article_is_cannibalisation():
    """Two live URLs for one search is the expensive case, and is named so."""
    service = ContentClusterService(FakeDB())
    service._draft_titles = _async([
        ("Local SEO guide for small business", "/local-seo", BlogDraftStatus.published)
    ])
    service._topic_titles = _async([])
    service._page_titles = _async([])

    result = await service.check_cannibalisation(uuid4(), uuid4(), "local seo guide small businesses")

    assert result["verdict"] == CannibalisationVerdict.POTENTIAL_CANNIBALIZATION
    assert result["conflict"]["kind"] == "published article"
    assert "Update" in result["recommended_action"]


@pytest.mark.asyncio
async def test_clash_with_a_queued_topic_is_only_a_duplicate():
    """Nothing is live yet, so this is queue hygiene, not a ranking problem."""
    service = ContentClusterService(FakeDB())
    service._draft_titles = _async([])
    service._topic_titles = _async([("Local SEO guide for small business", None)])
    service._page_titles = _async([])

    result = await service.check_cannibalisation(uuid4(), uuid4(), "local seo guide small businesses")

    assert result["verdict"] == CannibalisationVerdict.UPDATE_EXISTING_CONTENT
    assert result["conflict"]["kind"] == "queued topic"


@pytest.mark.asyncio
async def test_existing_page_is_checked_too():
    service = ContentClusterService(FakeDB())
    service._draft_titles = _async([])
    service._topic_titles = _async([])
    service._page_titles = _async([("Dental implants cost", "https://x.com/implants-cost")])

    result = await service.check_cannibalisation(uuid4(), uuid4(), "cost of dental implants")

    # A live page is as real a competitor as a published article — both are
    # URLs Google can already rank, so both are cannibalisation, not a queue
    # duplicate. Telling someone to "drop this, it is already queued" about a
    # page that has been live for two years is useless advice.
    assert result["verdict"] == CannibalisationVerdict.POTENTIAL_CANNIBALIZATION
    assert result["conflict"]["kind"] == "existing page"
    assert result["conflict"]["reference"] == "https://x.com/implants-cost"
    assert "Update the existing page" in result["recommended_action"]


@pytest.mark.asyncio
async def test_verdict_reports_how_much_was_checked():
    service = ContentClusterService(FakeDB())
    service._draft_titles = _async([("A", None, BlogDraftStatus.draft)])
    service._topic_titles = _async([("B", None)])
    service._page_titles = _async([("C", "u")])

    result = await service.check_cannibalisation(uuid4(), uuid4(), "something unrelated entirely")
    assert result["checked_against"] == 3


def _async(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner

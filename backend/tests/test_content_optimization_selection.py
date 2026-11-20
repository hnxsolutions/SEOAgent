"""Which pages are worth a local model call.

The stage used to generate for every crawled page in sequence. One call costs
tens of seconds of CPU, so a hundred-page site spent over an hour — longer than
the crawl that fed it — much of it re-deriving advice for pages with nothing
wrong, or producing suggestions that were then discarded as duplicates.

These fix the selection rules, because the risk of a filter is that it quietly
drops work that mattered.
"""
from __future__ import annotations

from uuid import uuid4

from app.models.content_optimization import ContentOptimizationSuggestionType
from app.models.content_optimization import ContentOptimizationSuggestionType as T
from app.services.content_optimization import ContentOptimizationService


class FakePage:
    """A page good enough that nothing about it needs rewriting."""

    def __init__(self, **overrides):
        self.id = uuid4()
        self.url = "https://example.com/services"
        self.status_code = 200
        self.noindex = False
        self.word_count = 900
        self.title = "Custom Software Development Services for Teams"
        self.meta_description = (
            "We design and build custom software, web applications and internal "
            "tools for growing teams that need them to work."
        )
        self.h1 = ["Custom software built around your workflow"]
        self.h2 = []
        self.h3 = []
        self.schema_markup = {"@type": "Service"}
        self.schema_types = ["Service"]
        self.has_schema_markup = True
        self.text_content = "word " * 900
        for key, value in overrides.items():
            setattr(self, key, value)


class FakeLinkRec:
    def __init__(self):
        self.target_url = "https://example.com/pricing"
        self.suggested_anchor_text = "see pricing"


def service() -> ContentOptimizationService:
    return ContentOptimizationService.__new__(ContentOptimizationService)


def skip_reason(page, issue_types=frozenset(), link_recs=(), existing=frozenset()):
    svc = service()
    pending = svc._pending_types(page, set(issue_types), list(link_recs), set(existing))
    return svc._skip_reason(page, set(issue_types), list(link_recs), pending)


def test_a_healthy_page_is_not_sent_to_the_model():
    """The case that made the stage slow: nothing is wrong, so nothing is asked."""
    assert skip_reason(FakePage()) == "no_deficiency"


def test_an_audit_issue_is_always_worth_a_call():
    assert skip_reason(FakePage(), issue_types={"missing_h1"}) is None


def test_metadata_outside_the_bounds_the_validator_enforces_is_worth_a_call():
    assert skip_reason(FakePage(title="Home")) is None
    assert skip_reason(FakePage(meta_description=None)) is None
    assert skip_reason(FakePage(h1=[])) is None
    assert skip_reason(FakePage(h1=["One", "Two"])) is None
    assert skip_reason(FakePage(has_schema_markup=False)) is None


def test_internal_link_recommendations_are_worth_a_call():
    assert skip_reason(FakePage(), link_recs=[FakeLinkRec()]) is None


def test_a_page_google_will_not_index_is_skipped():
    """Better copy cannot help a page that is not in the index. A 404 needs
    fixing, not rewriting, and the audit already says so."""
    assert skip_reason(FakePage(status_code=404, title="Home")) == "not_200"
    assert skip_reason(FakePage(noindex=True, title="Home")) == "noindex"


def test_a_page_with_almost_no_text_is_skipped():
    """The prompt is built from the page's own words. With none, what comes back
    is invention, and this product must never invent."""
    assert skip_reason(FakePage(word_count=4, title="Home")) == "too_little_content"


def test_a_page_whose_suggestions_all_exist_is_skipped():
    """Those suggestions would be discarded as duplicates after the call, so the
    call bought nothing. On a scheduled re-run this is most pages."""
    page = FakePage(title="Home")
    svc = service()
    issue_types: set[str] = set()
    every_key = {
        (page.id, suggestion_type, svc._content_hash(
            page, suggestion_type, svc._current_value(page, suggestion_type, []), issue_types
        ))
        for suggestion_type in svc._target_types(page, issue_types, [])
    }

    assert skip_reason(page, existing=every_key) == "already_suggested"


def test_one_stale_suggestion_brings_the_page_back():
    """Edit a page and its hash changes, so it is analysed again. A filter that
    could not do this would freeze the site's suggestions forever."""
    page = FakePage(title="Home")
    svc = service()
    pending = svc._pending_types(page, set(), [], set())

    assert ContentOptimizationSuggestionType.seo_title in pending
    assert skip_reason(page) is None


def requested(page, issue_types=frozenset(), link_recs=()):
    svc = service()
    return set(svc._target_types(page, set(issue_types), list(link_recs)))


def test_a_thin_page_is_asked_to_grow_not_to_add_an_faq():
    """On a 120-word page an FAQ would be answers invented rather than drawn
    from the page, which is the one thing this product must not produce. The
    useful advice there is that the page needs more content."""
    types = requested(FakePage(word_count=120, text_content="word " * 120))

    assert T.content_refresh in types
    assert T.faq not in types
    assert T.answer_block not in types


def test_a_substantial_page_is_offered_the_aeo_additions():
    types = requested(FakePage())

    assert T.faq in types
    assert T.answer_block in types


def test_a_page_that_already_has_faq_markup_is_not_asked_for_another():
    page = FakePage()
    page.schema_types = ["FAQPage", "Service"]

    assert T.faq not in requested(page)


def test_a_good_page_is_asked_for_far_less_than_everything():
    """The saving that makes the stage affordable: the model writes three or
    four sections for a healthy page instead of all nine."""
    types = requested(FakePage())

    assert T.seo_title not in types
    assert T.meta_description not in types
    assert T.schema not in types
    assert len(types) < 5

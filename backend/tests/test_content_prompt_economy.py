"""The prompt must not pay for output that is thrown away.

On CPU-only hardware the number of tokens the model emits *is* the runtime of
the content stage, so every field asked for has to be a field that gets used.
Two were not: `_reason()` returns a fixed sentence for titles, descriptions and
schema and never looks at what the model wrote, and the FAQ shape was unbounded
so the model wrote four or five pairs where two are stored and read.

Measured with no competing load: 417 output tokens and 14.4s per page before,
313 and 10.8s after.
"""
from __future__ import annotations

import pytest

from app.models.content_optimization import ContentOptimizationSuggestionType as T
from app.services.content_optimization import (
    SUGGESTION_JSON_SHAPES,
    ContentOptimizationService,
)

#: Types whose `reason` `_reason()` replaces with a fixed sentence.
REASON_IS_DISCARDED = ("seo_title", "meta_description", "schema")

#: Types whose `reason` is surfaced to the operator.
REASON_IS_USED = ("h1", "headings", "faq", "content_refresh", "answer_block", "internal_link_context")


@pytest.mark.parametrize("name", REASON_IS_DISCARDED)
def test_no_reason_is_requested_where_it_is_discarded(name):
    assert '"reason"' not in SUGGESTION_JSON_SHAPES[name], (
        f"{name} asks the model for a reason that _reason() overwrites"
    )


@pytest.mark.parametrize("name", REASON_IS_USED)
def test_a_reason_is_still_requested_where_it_is_shown(name):
    assert '"reason"' in SUGGESTION_JSON_SHAPES[name]


@pytest.mark.parametrize("name", REASON_IS_USED)
def test_every_requested_reason_is_bounded(name):
    """Left open the model writes a paragraph; the UI shows a line."""
    assert "under 12 words" in SUGGESTION_JSON_SHAPES[name]


def test_the_faq_asks_for_a_fixed_number_of_pairs():
    """The largest single block of output on a typical page."""
    shape = SUGGESTION_JSON_SHAPES["faq"]

    assert shape.count('"question":') == 2
    assert shape.count('"answer":') == 2


def test_the_discarded_reasons_match_what_the_code_actually_does():
    """Guards the pairing itself: if _reason() ever starts using the model's text
    for one of these, the prompt has to start asking for it again."""
    svc = ContentOptimizationService.__new__(ContentOptimizationService)
    item = {"reason": "a reason the model wrote"}

    for suggestion_type in (T.seo_title, T.meta_description, T.schema):
        reason = svc._reason(suggestion_type, item, set(), None)
        assert reason != item["reason"], f"{suggestion_type} now uses the model's reason"

    used = svc._reason(T.answer_block, item, set(), None)
    assert used == item["reason"]

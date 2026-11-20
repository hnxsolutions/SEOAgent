"""No suggestion is better than a fabricated one.

When the model's title or description failed the length check, this service
substituted a fixed sentence — "Explore {topic} with concise details, helpful
context, and related resources for visitors" — and stored it as the agent's
recommendation. Thirteen of twenty-four pages in one run received near-identical
copy that said nothing about them. It also hid a worse problem: the model was
often returning the prompt's own placeholder text, and the filler made that
indistinguishable from a real answer.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.content_optimization import (
    META_MAX_LENGTH,
    META_MIN_LENGTH,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
    ContentOptimizationService,
)

PAGE = SimpleNamespace(title="Services", h1=["Services"], url="https://example.com/services")


def svc() -> ContentOptimizationService:
    return ContentOptimizationService.__new__(ContentOptimizationService)


# --- the salvage case: this is the one that was silently losing good copy -----

def test_a_description_slightly_over_the_limit_is_trimmed_not_discarded():
    """Measured: the model returned 164 characters of good copy for a 160 limit
    and it was thrown away for filler, because the length test sat in the reject
    branch and the truncation below it could only ever reach the replacement."""
    long_but_good = (
        "Explore the full range of web, SaaS, CRM and mobile services we build for "
        "growing companies, with dedicated pages describing each one in practical, "
        "unhurried detail."
    )
    assert len(long_but_good) > META_MAX_LENGTH

    result = svc()._validate_meta(long_but_good, PAGE)

    assert result
    assert len(result) <= META_MAX_LENGTH
    assert result.startswith("Explore the full range of web")


def test_a_title_over_the_limit_is_trimmed_not_discarded():
    long_title = "Custom Software, CRM, AI Automation and Mobile App Development Services"
    assert len(long_title) > TITLE_MAX_LENGTH

    result = svc()._validate_title(long_title, PAGE)

    assert result
    assert len(result) <= TITLE_MAX_LENGTH


# --- the drop cases: nothing usable, so nothing is claimed --------------------

@pytest.mark.parametrize("value", ["Short", "", "   "])
def test_an_unusably_short_description_produces_no_suggestion(value):
    assert svc()._validate_meta(value, PAGE) == ""


def test_an_unusably_short_title_produces_no_suggestion():
    assert svc()._validate_title("Tiny", PAGE) == ""


def test_a_returned_prompt_slot_produces_no_suggestion():
    """Three of six measured replies were the placeholder itself. A returned slot
    is the absence of an answer and must not be stored as one."""
    assert svc()._validate_meta("50-160 char meta description", PAGE) == ""
    assert svc()._validate_meta("<your description here, 50-160 characters>", PAGE) == ""
    assert svc()._validate_title("<your title here, 30-60 characters>", PAGE) == ""


def test_keyword_stuffing_produces_no_suggestion():
    stuffed = "seo seo seo seo services for seo and seo and more seo for your seo needs today"

    assert svc()._validate_meta(stuffed, PAGE) == ""


def test_no_output_ever_contains_the_old_filler_sentence():
    """The sentence itself is gone. If it ever comes back, it comes back here."""
    for value in ("Short", "", "50-160 char meta description"):
        assert "concise details" not in svc()._validate_meta(value, PAGE)


# --- and good copy is left alone ---------------------------------------------

def test_a_valid_description_passes_through_unchanged():
    good = "A practical guide to the services on this page, who they suit, and how to begin."
    assert META_MIN_LENGTH <= len(good) <= META_MAX_LENGTH

    assert svc()._validate_meta(good, PAGE) == good


def test_a_valid_title_passes_through_unchanged():
    good = "Custom CRM and Web Development Services"
    assert TITLE_MIN_LENGTH <= len(good) <= TITLE_MAX_LENGTH

    assert svc()._validate_title(good, PAGE) == good

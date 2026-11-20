"""The prompt asks for what will be stored, and nothing else.

On a CPU-only Ollama the length of the reply is the runtime of this stage: a 3B
model emits a few tokens a second, so a flat nine-section request with a 1200
token budget cost minutes per page — most of it generating sections that
`_suggestion_records` then dropped because they were not among the page's
pending types.
"""
from __future__ import annotations

from uuid import uuid4

from app.models.content_optimization import ContentOptimizationSuggestionType as T
from app.services.content_optimization import (
    MIN_PREDICT_TOKENS,
    SUGGESTION_JSON_SHAPES,
    TOKENS_PER_SUGGESTION,
    ContentOptimizationService,
)


class FakePage:
    def __init__(self):
        self.id = uuid4()
        self.url = "https://example.com/pricing"
        self.title = "Pricing"
        self.meta_description = None
        self.h1 = ["Pricing"]
        self.h2 = []
        self.h3 = []
        self.word_count = 400
        self.text_content = "pricing " * 400


def build(requested):
    svc = ContentOptimizationService.__new__(ContentOptimizationService)
    return svc._build_prompt(FakePage(), [], None, [], "", requested_types=requested)


def test_only_the_requested_sections_appear():
    prompt = build([T.seo_title, T.meta_description])

    assert '"seo_title"' in prompt
    assert '"meta_description"' in prompt
    for absent in ("faq", "schema", "answer_block", "content_refresh", "headings"):
        assert f'"{absent}":' not in prompt


def test_a_narrow_request_is_much_shorter_than_the_full_one():
    """The saving has to be real, not cosmetic."""
    narrow = build([T.seo_title])
    full = build(list(T))

    assert len(narrow) < len(full) * 0.75


def test_no_request_still_asks_for_everything():
    """Callers that do not pass a set must keep the old behaviour rather than
    silently asking for nothing."""
    prompt = build(None)

    for name in SUGGESTION_JSON_SHAPES:
        assert f'"{name}"' in prompt


def test_the_token_budget_has_a_floor():
    """A one-section reply still needs room to close its JSON; truncated output
    fails to parse and loses the page entirely."""
    assert MIN_PREDICT_TOKENS > TOKENS_PER_SUGGESTION

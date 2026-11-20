"""What happens when the local model returns something that is not clean JSON.

A 3B model asked for JSON mostly returns JSON — and sometimes returns it wrapped
in prose, or two objects run together, or one cut off by the token budget. Every
one of those used to escape the parser as a bare JSONDecodeError and fail the
whole content stage, discarding every page already generated. A run that had
done real work for an hour recorded nothing.
"""
from __future__ import annotations

import pytest

from app.services.content_optimization import (
    ContentOptimizationService,
    UnusableModelResponse,
)


def parse(text: str):
    svc = ContentOptimizationService.__new__(ContentOptimizationService)
    return svc._parse_llm_json(text)


GOOD = '{"seo_title": {"suggested_value": "A Clear Page Title", "confidence_score": 80}}'


def test_plain_json():
    assert parse(GOOD)["seo_title"]["suggested_value"] == "A Clear Page Title"


def test_fenced_json():
    assert parse(f"```json\n{GOOD}\n```")["seo_title"]


def test_json_wrapped_in_prose():
    """Models like to explain themselves either side of the answer."""
    assert parse(f"Here is the JSON you asked for:\n{GOOD}\nHope that helps!")["seo_title"]


def test_two_objects_run_together():
    """The old extract took the first brace to the last, which spans both and
    parses as nothing."""
    assert parse(f"{GOOD}\n{GOOD}")["seo_title"]


def test_a_reply_cut_off_by_the_token_budget_keeps_what_completed():
    """The budget is a cap, so a long reply can stop mid-field. The fields that
    did complete are still worth having — losing a truncated FAQ should not cost
    the title and description that came before it."""
    truncated = (
        '{"seo_title": {"suggested_value": "A Clear Page Title", "confidence_score": 80},'
        ' "meta_description": {"suggested_value": "A description that is long enough to be useful.",'
        ' "confidence_score": 70},'
        ' "faq": {"suggested_value": [{"question": "What is thi'
    )
    data = parse(truncated)

    assert data["seo_title"]["suggested_value"] == "A Clear Page Title"
    assert "meta_description" in data


def test_unusable_output_raises_the_handled_error_not_a_decode_error():
    """The caller skips a page on this type and only this type. A raw
    JSONDecodeError went straight past that and failed the run; an
    OllamaRequestError would have been too broad, because that also means the
    model is unreachable — which must still fail the run."""
    with pytest.raises(UnusableModelResponse):
        parse("I'm sorry, I can't help with that.")


def test_an_object_wrapped_in_an_array_is_recovered():
    """A model that answers `[{...}]` did give us the object, and the suggestion
    types are read by name either way. Refusing it would discard a usable reply
    on a technicality, which is the opposite of what the rest of this parser is
    for."""
    data = parse('[{"seo_title": {"suggested_value": "A Clear Page Title"}}]')

    assert data["seo_title"]["suggested_value"] == "A Clear Page Title"


def test_empty_output():
    with pytest.raises(UnusableModelResponse):
        parse("")


def test_an_unusable_reply_is_not_an_ollama_transport_error():
    """The whole point of the separate type.

    `OllamaRequestError` means the model could not be reached or refused the
    request, and that must fail the run — a dead Ollama quietly producing a
    "completed" run with no suggestions would be worse than an error. An
    unusable reply means the model answered and this service could not read it,
    which is one page's loss. If `UnusableModelResponse` ever became a subclass
    of the transport error, the per-page skip would start swallowing outages.
    """
    from app.services.local_llm import LocalLLMError, OllamaRequestError

    assert not issubclass(UnusableModelResponse, OllamaRequestError)
    assert not issubclass(UnusableModelResponse, LocalLLMError)

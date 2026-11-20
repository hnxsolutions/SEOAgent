"""What the Core Web Vitals card says when PageSpeed Insights does not answer.

The dashboard showed two useless things at once: a wall of raw JSON for one
strategy and a bare "PageSpeed request failed:" with nothing after the colon for
the other. Both are covered here, because an error message is the whole product
when the upstream is down — it is the only thing the operator gets.
"""
from __future__ import annotations

import httpx
import pytest

from app.services.pagespeed import describe_exception, describe_upstream_error

LIGHTHOUSE_TIMEOUT = (
    '{"error": {"code": 500, "message": "Lighthouse returned error: '
    'PROTOCOL_TIMEOUT. Waiting for DevTools protocol response has exceeded the '
    'allotted time. (Method: CSS.stopRuleUsageTracking)"}}'
)


def test_a_timeout_says_what_timed_out():
    """`str()` on an httpx timeout is the empty string, which is how the card
    came to read "PageSpeed request failed:" and stop."""
    message = describe_exception(httpx.ReadTimeout(""), 120.0)

    assert message.strip()
    assert "120" in message
    assert not message.rstrip().endswith(":")


def test_other_transport_errors_keep_their_type():
    message = describe_exception(httpx.ConnectError("name resolution failed"), 120.0)

    assert "ConnectError" in message
    assert "name resolution failed" in message


def test_lighthouse_timeout_is_explained_not_pasted():
    """The operator needs to know Google gave up analysing, not reading JSON."""
    message = describe_upstream_error(500, LIGHTHOUSE_TIMEOUT)

    assert "timed out" in message.lower()
    assert '{"error"' not in message
    assert "code" not in message.split("(Google reported:")[0]


def test_an_unreachable_page_is_distinguished_from_a_slow_one():
    """Different operator action: fix reachability, versus lighten the page."""
    message = describe_upstream_error(
        500, '{"error": {"message": "Lighthouse returned error: ERRORED_DOCUMENT_REQUEST"}}'
    )

    assert "could not load" in message.lower()


def test_an_unrecognised_failure_still_reads_as_a_sentence():
    """Google's generic 'Something went wrong' must not fall through to a blank."""
    message = describe_upstream_error(
        500, '{"error": {"message": "Lighthouse returned error: Something went wrong."}}'
    )

    assert message.startswith("PageSpeed Insights could not analyse")
    assert "Something went wrong" in message


def test_a_non_json_body_does_not_raise():
    message = describe_upstream_error(502, "<html>502 Bad Gateway</html>")

    assert "502" in message

"""The Failure Center shows what is wrong now, not everything that ever broke.

With no window, a one-off failure from July sat at the top of the panel months
later, indistinguishable from something broken this morning. Three of the five
entries on display were from July and October 5th; the one live problem — 51
occurrences, the most recent minutes old — was buried underneath them. An
operator reading that panel could not tell what needed attention, which is the
only thing it is for.
"""
from __future__ import annotations

import inspect

from app.services.seo_run import SeoRunService
from app.services.telemetry_query import TelemetryQuery


def test_failures_are_limited_to_a_recent_window():
    source = inspect.getsource(TelemetryQuery.failures)

    assert "cutoff" in source
    assert "started_at >= cutoff" in source


def test_the_window_is_short_enough_to_mean_now():
    """A week would put last Tuesday's resolved blip beside this morning's
    outage, which is the problem this fixes."""
    assert TelemetryQuery.FAILURE_WINDOW_HOURS <= 48


def test_the_window_can_be_widened_deliberately():
    """Looking further back is a choice a caller makes, not the default."""
    assert "within_hours" in inspect.signature(TelemetryQuery.failures).parameters


def test_a_missing_run_names_both_ids():
    """Recorded 51 times as the bare words "SEO run not found", with no run id
    and no tenant attached — nothing to look up, nothing to act on."""
    source = inspect.getsource(SeoRunService.execute_run)

    assert "f\"SEO run {run_id} was not found for tenant {tenant_id}" in source


def test_the_missing_run_message_explains_the_usual_cause():
    source = inspect.getsource(SeoRunService.execute_run)

    assert "deleted" in source

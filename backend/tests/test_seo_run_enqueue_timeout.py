"""A full SEO run must not be enqueued on the generic job timeout.

The queue's default is 30 minutes, which suits the short jobs it was written
for. A full run is a pipeline — crawl, audit, embed every page, then a local
LLM call per page that needs one — and on CPU-only hardware that is hours. Run
under the default, RQ killed the work-horse part way through the content stage
and left the row saying "running" with nothing executing it, which is exactly
what the dashboard kept showing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import settings

ENQUEUE_SITES = [
    Path("app/api/v1/routes/seo_runs.py"),
    Path("app/api/v1/routes/projects.py"),
    # The brain cycle runs the whole pipeline before robots and sitemap work.
    # It was missed the first time and sat on the 30-minute default.
    Path("app/api/v1/routes/brain.py"),
]


def test_the_run_timeout_is_far_larger_than_the_generic_one():
    assert settings.SEO_RUN_JOB_TIMEOUT_SECONDS >= settings.QUEUE_JOB_TIMEOUT_SECONDS * 4


def test_the_run_timeout_covers_a_realistic_run():
    """Measured on a 99-page site: ~8 min crawl, ~20 min embedding, ~1.6 h of
    content generation. Two hours is the shape of the work, not a guess."""
    assert settings.SEO_RUN_JOB_TIMEOUT_SECONDS >= 2 * 60 * 60


@pytest.mark.parametrize("path", ENQUEUE_SITES, ids=lambda p: p.name)
def test_every_enqueue_site_passes_the_run_timeout(path: Path):
    """Guards the thing that actually broke: one of these forgetting the
    argument silently reinstates the 30-minute kill."""
    source = path.read_text(encoding="utf-8")

    for match in re.finditer(r"enqueue_or_background\((.*?)\n    \)", source, re.S):
        block = match.group(1)
        if "run_seo_run" in block or "run_brain_cycle" in block:
            assert "SEO_RUN_JOB_TIMEOUT_SECONDS" in block, f"{path} enqueues a run without the timeout"

    assert "run_seo_run" in source or "run_brain_cycle" in source
    assert "SEO_RUN_JOB_TIMEOUT_SECONDS" in source

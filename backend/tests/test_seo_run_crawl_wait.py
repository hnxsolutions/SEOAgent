"""The crawl wait is what failed two real SEO runs, so it is tested directly.

Both runs crawled a healthy site successfully and were still marked failed,
because the orchestrator measured elapsed time against a constant instead of
asking whether the crawl was getting anywhere. These cover the three outcomes
that constant could not distinguish: finishing late, stalling with pages in
hand, and stalling with nothing.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.models.crawl import CrawlStatus
from app.services.seo_run import SeoRunError, SeoRunService


class FakeCrawl:
    def __init__(self, max_pages=100, status=CrawlStatus.running, crawled=0):
        self.id = uuid4()
        self.max_pages = max_pages
        self.status = status
        self.total_pages_crawled = crawled
        self.total_pages_failed = 0
        self.error_message = None


class FakeCrawlService:
    """Replays a scripted sequence of job states, one per poll."""

    def __init__(self, states):
        self._states = list(states)
        self.cancelled = False

    async def get_crawl_job(self, crawl_id, tenant_id):
        return self._states.pop(0) if len(self._states) > 1 else self._states[0]

    async def cancel_crawl(self, job_id, tenant_id=None):
        self.cancelled = True
        job = self._states[-1]
        job.status = CrawlStatus.cancelled
        return job


class FakeDb:
    def expire_all(self):
        pass


def make_service(**kwargs):
    service = SeoRunService.__new__(SeoRunService)
    service.db = FakeDb()
    service.poll_interval_seconds = 0.001
    service.crawl_stall_timeout_seconds = kwargs.get("stall", 0.05)
    service.crawl_seconds_per_page = kwargs.get("per_page", 12.0)
    service.crawl_min_timeout_seconds = kwargs.get("minimum", 600)
    return service


@pytest.mark.asyncio
async def test_slow_but_progressing_crawl_is_not_cut_off():
    """The actual regression: a crawl that keeps saving pages keeps its budget.

    Each poll advances the page count by one and takes longer than the whole
    stall window, which is exactly the shape that used to trip the old fixed
    deadline. Progress, not elapsed time, has to be what counts.
    """
    states = [FakeCrawl(crawled=n) for n in range(1, 6)]
    states.append(FakeCrawl(status=CrawlStatus.completed, crawled=6))
    service = make_service(stall=0.05)

    crawl, note = await service._wait_for_crawl(FakeCrawlService(states), uuid4(), uuid4())

    assert crawl.status == CrawlStatus.completed
    assert note is None


@pytest.mark.asyncio
async def test_stalled_crawl_keeps_the_pages_it_collected():
    """A crawl that goes quiet is abandoned, not failed: 40 real pages are worth
    auditing, and throwing them away is what produced two useless runs."""
    stuck = FakeCrawl(crawled=40)
    service = make_service(stall=0.02)
    crawl_service = FakeCrawlService([stuck])

    crawl, note = await service._wait_for_crawl(crawl_service, uuid4(), uuid4())

    assert crawl_service.cancelled
    assert "40 pages" in note


@pytest.mark.asyncio
async def test_stalled_crawl_with_no_pages_is_a_failure():
    """Nothing was collected, so there is nothing to audit. This is the one
    case that should still fail the run rather than pretend to have data."""
    service = make_service(stall=0.02)

    with pytest.raises(SeoRunError):
        await service._wait_for_crawl(FakeCrawlService([FakeCrawl(crawled=0)]), uuid4(), uuid4())


def test_the_ceiling_scales_with_the_page_budget():
    """One constant cannot serve a 5-page site and a 5,000-page one."""
    service = make_service(per_page=12.0, minimum=600)

    assert service._crawl_ceiling_seconds(5) == 600      # floor applies
    assert service._crawl_ceiling_seconds(100) == 1200
    assert service._crawl_ceiling_seconds(1000) == 12000

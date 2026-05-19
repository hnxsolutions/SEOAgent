from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.crawl import CrawlPriority, CrawlStatus
from app.services.crawl import CrawlService


class DummyDB:
    async def commit(self):
        return None

    async def refresh(self, instance):
        return None


class FakeRepository:
    def __init__(self):
        self.values = None

    async def create_job(self, **values):
        self.values = values
        return SimpleNamespace(id=uuid4(), **values)


@pytest.mark.asyncio
async def test_create_crawl_job_normalizes_url_and_defaults_allowed_domain():
    service = CrawlService(DummyDB())
    fake_repository = FakeRepository()
    service.repository = fake_repository

    job = await service.create_crawl_job(
        url="https://Example.com/start?utm_source=test#section",
        tenant_id=uuid4(),
        max_pages=25,
        depth=3,
    )

    assert job.url == "https://example.com/start"
    assert job.status == CrawlStatus.pending
    assert job.allowed_domains == ["example.com"]
    assert job.max_pages == 25
    assert job.max_depth == 3


@pytest.mark.asyncio
async def test_enqueue_crawl_job_creates_redis_task(monkeypatch):
    queued_tasks = []

    class FakeQueue:
        def __init__(self, redis_url, queue_name):
            self.redis_url = redis_url
            self.queue_name = queue_name

        async def connect(self):
            return None

        async def disconnect(self):
            return None

        async def enqueue_task(self, task):
            queued_tasks.append(task)
            return True

    monkeypatch.setattr("app.services.crawl.CrawlQueueManager", FakeQueue)

    tenant_id = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=None,
        url="https://example.com",
        status=CrawlStatus.pending,
        priority=CrawlPriority.normal,
        max_pages=10,
        max_depth=2,
        allowed_domains=["example.com"],
        excluded_paths=[],
        follow_subdomains=False,
        respect_robots_txt=True,
        sitemap_urls=[],
        render_javascript=True,
        request_timeout=30,
        crawl_delay=1.0,
        user_agent=None,
        max_retries=2,
        queue_name=None,
        total_pages_discovered=0,
    )

    service = CrawlService(DummyDB())

    async def fake_get_crawl_job(job_id, tenant_id=None):
        return job

    service.get_crawl_job = fake_get_crawl_job

    queued_job = await service.enqueue_crawl_job(job.id, tenant_id=tenant_id)

    assert queued_job.status == CrawlStatus.queued
    assert queued_job.queue_name == "default"
    assert len(queued_tasks) == 1
    assert queued_tasks[0].url == "https://example.com"
    assert queued_tasks[0].metadata["max_pages"] == 10

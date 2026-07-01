from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.crawl import CrawlPriority, CrawlStatus
from app.core.redis import REDIS_UNAVAILABLE_MESSAGE, RedisUnavailableError
from app.crawler.queue_manager import CrawlQueueManager
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


def test_crawl_queue_dedup_is_scoped_per_job():
    queue = CrawlQueueManager(queue_name="default")
    url_hash = queue._hash_url("https://example.com/")

    first_job_key = queue._dedup_key(url_hash, "job-1")
    second_job_key = queue._dedup_key(url_hash, "job-2")

    assert first_job_key != second_job_key
    assert first_job_key.endswith(f":job-1:{url_hash}")
    assert second_job_key.endswith(f":job-2:{url_hash}")


@pytest.mark.asyncio
async def test_enqueue_crawl_job_fails_gracefully_when_redis_missing_in_dev(monkeypatch):
    class FailingQueue:
        def __init__(self, redis_url, queue_name):
            self.redis_url = redis_url
            self.queue_name = queue_name

        async def connect(self):
            raise ConnectionError("localhost:6379 connection refused")

        async def disconnect(self):
            return None

    monkeypatch.setattr("app.services.crawl.CrawlQueueManager", FailingQueue)
    monkeypatch.setattr("app.services.crawl.settings.REDIS_REQUIRED", False)

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

    class FakeRepository:
        async def set_job_status(self, job, status, error_message=None, worker_id=None):
            job.status = status
            job.error_message = error_message
            return job

    service.get_crawl_job = fake_get_crawl_job
    service.repository = FakeRepository()

    with pytest.raises(RedisUnavailableError) as exc:
        await service.enqueue_crawl_job(job.id, tenant_id=tenant_id)

    assert str(exc.value) == REDIS_UNAVAILABLE_MESSAGE
    assert job.status == CrawlStatus.failed
    assert job.error_message == REDIS_UNAVAILABLE_MESSAGE

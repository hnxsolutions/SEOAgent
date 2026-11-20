"""Only one content generation per crawl at a time.

Triggering a resume twice started two runs over the same 171 pages. They did not
finish any sooner — both drive one CPU-bound model, so each took roughly twice as
long — and they raced to write the same suggestions. The visible symptom was a
stage that appeared stalled and a dashboard whose counters kept resetting as the
two runs overwrote each other's progress.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.content_optimization import (
    ContentOptimizationService,
    ContentRunAlreadyRunning,
)


class Repo:
    def __init__(self, active=None):
        self.active = active
        self.created = False

    async def get_crawl(self, *_):
        return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), project_id=uuid4())

    async def list_crawl_pages(self, *_):
        return [SimpleNamespace(id=uuid4())]

    async def find_active_run(self, *_):
        return self.active

    async def create_run(self, *_, **__):
        self.created = True
        return SimpleNamespace(id=uuid4())


class Db:
    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass


def service(repo) -> ContentOptimizationService:
    svc = ContentOptimizationService.__new__(ContentOptimizationService)
    svc.repository = repo
    svc.db = Db()
    return svc


@pytest.mark.asyncio
async def test_a_second_run_is_refused_while_one_is_in_flight():
    repo = Repo(active=SimpleNamespace(id=uuid4(), progress=42))

    with pytest.raises(ContentRunAlreadyRunning) as exc:
        await service(repo).start_generation(uuid4(), uuid4())

    assert not repo.created
    assert "42%" in str(exc.value), "the message should say how far the existing run has got"


@pytest.mark.asyncio
async def test_a_run_starts_normally_when_nothing_is_in_flight():
    repo = Repo(active=None)

    await service(repo).start_generation(uuid4(), uuid4())

    assert repo.created


def test_the_refusal_is_its_own_type():
    """So the orchestrator can tell "someone already started this" from a real
    failure, instead of marking the stage broken."""
    assert issubclass(ContentRunAlreadyRunning, RuntimeError)
    from app.services.content_optimization import UnusableModelResponse

    assert not issubclass(ContentRunAlreadyRunning, UnusableModelResponse)

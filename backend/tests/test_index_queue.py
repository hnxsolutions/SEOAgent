"""Tests for the Auto Index Queue eligibility + graceful submission."""
from types import SimpleNamespace as S
from uuid import uuid4

import pytest

from app.services.index_queue import IndexQueueService


def test_validate_page_eligible_when_200_indexable_self_canonical():
    ok, reason = IndexQueueService._validate_page(
        S(status_code=200, noindex=False, canonical_url_normalized="https://x.com/a",
          normalized_url="https://x.com/a", url="https://x.com/a")
    )
    assert ok is True and reason is None


def test_validate_page_rejects_non_200():
    ok, reason = IndexQueueService._validate_page(
        S(status_code=404, noindex=False, canonical_url_normalized=None, normalized_url="u", url="u")
    )
    assert ok is False and "404" in reason


def test_validate_page_rejects_noindex():
    ok, reason = IndexQueueService._validate_page(
        S(status_code=200, noindex=True, canonical_url_normalized=None, normalized_url="u", url="u")
    )
    assert ok is False and "noindex" in reason.lower()


def test_validate_page_rejects_alternate_canonical():
    ok, reason = IndexQueueService._validate_page(
        S(status_code=200, noindex=False, canonical_url_normalized="https://x.com/canonical",
          normalized_url="https://x.com/dupe", url="https://x.com/dupe")
    )
    assert ok is False and "canonical" in reason.lower()


# -- graceful submission when Search Console is not connected ------------------

class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeDB:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _q):
        return _Result(self._results.pop(0) if self._results else [])

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_submit_nothing_when_no_approved():
    db = _FakeDB([[]])  # no approved urls
    result = await IndexQueueService(db).submit_approved(uuid4(), uuid4())
    assert result["status"] == "nothing_to_submit"
    assert result["submitted"] == 0


@pytest.mark.asyncio
async def test_submit_degrades_gracefully_when_not_connected(monkeypatch):
    approved = [S(id=uuid4(), status=None, submitted_via=None, submitted_at=None)]
    project = S(id=uuid4(), domain="example.com", tenant_id=uuid4())
    db = _FakeDB([approved, [project]])

    class _FailSitemap:
        def __init__(self, _db):
            pass

        async def submit(self, *a, **k):
            raise RuntimeError("Google Search Console OAuth is disabled. Missing property/token.")

    import app.services.index_queue as mod
    monkeypatch.setattr("app.services.sitemap.SitemapIntelligenceService", _FailSitemap, raising=False)

    result = await IndexQueueService(db).submit_approved(uuid4(), uuid4())
    assert result["status"] == "not_connected"     # gated, not fabricated success
    assert result["submitted"] == 0
    assert "no official api" in result["note"].lower()

"""Content engine orchestration: drafting decisions and draft validation.

The behaviour worth pinning here is what the engine *refuses* to do — draft a
duplicate, draft when nothing is worth writing, consume a topic when the model
is down, or pass a draft that has no FAQ and no schema. Those are the decisions
that keep a site from filling up with articles nobody wanted.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.content_engine import MIN_TOPIC_SCORE, ContentEngineService


class FakeDB:
    def __init__(self, get_result=None):
        self.committed = 0
        self._get_result = get_result

    async def commit(self):
        self.committed += 1

    async def flush(self):
        return None

    def add(self, _obj):
        return None

    async def get(self, _model, _pk):
        return self._get_result


def draft(**overrides):
    base = dict(
        tenant_id=None,
        title="A reasonable article",
        slug="a-reasonable-article",
        meta_title="A reasonable article title that fits",
        meta_description=(
            "A meta description of a sensible length that describes the article "
            "clearly for searchers and sits inside the usual limit."
        ),
        draft_markdown="\n\n".join(
            ["Opening answer paragraph."]
            + [f"## Section heading {i}?\n\n" + ("word " * 180) for i in range(4)]
        ),
        faq_json=[{"q": "What is it?", "a": "It is this."}],
        schema_json={"@type": "Article"},
        internal_link_plan=[{"to": "/services"}],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------
# Draft validation
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_complete_draft_passes_both_gates():
    tenant = uuid4()
    service = ContentEngineService(FakeDB(get_result=draft(tenant_id=tenant)))

    result = await service.validate_draft(uuid4(), tenant)

    assert result["passed"] is True
    assert result["seo_issues"] == []
    assert result["aeo_issues"] == []
    assert result["seo_score"] == 100
    assert result["aeo_score"] == 100


@pytest.mark.asyncio
async def test_thin_content_fails_seo():
    tenant = uuid4()
    thin = draft(tenant_id=tenant, draft_markdown="## One heading\n\nToo short.")
    service = ContentEngineService(FakeDB(get_result=thin))

    result = await service.validate_draft(uuid4(), tenant)

    assert result["passed"] is False
    assert any("words" in issue for issue in result["seo_issues"])
    assert any("H2" in issue for issue in result["seo_issues"])


@pytest.mark.asyncio
async def test_missing_faq_and_schema_fails_aeo():
    """These are exactly what answer engines lift, so their absence is an AEO fail."""
    tenant = uuid4()
    service = ContentEngineService(
        FakeDB(get_result=draft(tenant_id=tenant, faq_json=None, schema_json=None))
    )

    result = await service.validate_draft(uuid4(), tenant)

    assert result["aeo_score"] < 100
    assert any("FAQ" in issue for issue in result["aeo_issues"])
    assert any("structured data" in issue for issue in result["aeo_issues"])


@pytest.mark.asyncio
async def test_overlong_meta_title_is_flagged():
    tenant = uuid4()
    service = ContentEngineService(
        FakeDB(get_result=draft(tenant_id=tenant, meta_title="x" * 90))
    )

    result = await service.validate_draft(uuid4(), tenant)
    assert any("Meta title" in issue for issue in result["seo_issues"])


@pytest.mark.asyncio
async def test_validation_refuses_a_draft_from_another_tenant():
    service = ContentEngineService(FakeDB(get_result=draft(tenant_id=uuid4())))

    result = await service.validate_draft(uuid4(), uuid4())

    assert result["seo_score"] is None
    assert "Draft not found." in result["issues"]


# --------------------------------------------------------------------------
# Drafting decisions
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_draft_next_skips_when_there_is_no_plan():
    service = ContentEngineService(FakeDB())
    service._project = _async(SimpleNamespace(id=uuid4(), name="x", domain="x.com"))
    service._active_plan = _async(None)

    result = await service.draft_next(uuid4(), uuid4())

    assert result["drafted"] is False
    assert "opportunity scan" in result["reason"]


@pytest.mark.asyncio
async def test_draft_next_skips_rather_than_writing_something_worthless():
    """An empty queue is a skip, not a failure and not a filler article."""
    service = ContentEngineService(FakeDB())
    service._project = _async(SimpleNamespace(id=uuid4()))
    service._active_plan = _async(SimpleNamespace(id=uuid4()))
    service._next_topic = _async(None)

    result = await service.draft_next(uuid4(), uuid4())

    assert result["drafted"] is False
    assert "not worth publishing" in result["reason"]


@pytest.mark.asyncio
async def test_draft_next_refuses_to_cannibalise_a_published_article():
    topic = SimpleNamespace(
        id=uuid4(), title="Local SEO guide for small businesses",
        status=None, reason=None, priority_score=80,
    )
    db = FakeDB()
    service = ContentEngineService(db)
    service._project = _async(SimpleNamespace(id=uuid4()))
    service._active_plan = _async(SimpleNamespace(id=uuid4()))
    service._next_topic = _async(topic)
    service._published_titles = _async([("Local SEO guide small business", "/local-seo")])

    result = await service.draft_next(uuid4(), uuid4())

    assert result["drafted"] is False
    assert result["cannibalised_by"] == "Local SEO guide small business"
    # The topic is closed out with an explanation, not silently dropped.
    assert "Update that article instead" in topic.reason
    assert db.committed == 1


@pytest.mark.asyncio
async def test_a_failing_model_leaves_the_topic_for_next_time(monkeypatch):
    """An Ollama outage must not consume the slot's topic."""
    topic = SimpleNamespace(id=uuid4(), title="Something new entirely", status=None, reason=None)
    service = ContentEngineService(FakeDB())
    service._project = _async(SimpleNamespace(id=uuid4()))
    service._active_plan = _async(SimpleNamespace(id=uuid4()))
    service._next_topic = _async(topic)
    service._published_titles = _async([])

    class BrokenBlogService:
        def __init__(self, _db):
            pass

        async def draft_topic(self, *_args, **_kwargs):
            raise ConnectionError("ollama unreachable")

    import app.services.blogs as blogs_module

    monkeypatch.setattr(blogs_module, "BlogService", BrokenBlogService)

    result = await service.draft_next(uuid4(), uuid4())

    assert result["drafted"] is False
    assert "unavailable" in result["reason"]
    assert topic.status is None, "the topic must remain draftable next slot"


# --------------------------------------------------------------------------
# Performance review
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_performance_review_with_nothing_published():
    service = ContentEngineService(FakeDB())
    service._published_drafts = _async([])

    result = await service.review_performance(uuid4(), uuid4())

    assert result["articles"] == 0
    assert "Nothing published" in result["note"]


@pytest.mark.asyncio
async def test_articles_without_gsc_data_are_not_judged():
    """No data must read as NO_DATA_YET, never as a failing article."""
    published = [SimpleNamespace(id=uuid4(), slug="brand-new", title="Brand new", published_at=None)]
    service = ContentEngineService(FakeDB())
    service._published_drafts = _async(published)
    service._gsc_by_page = _async({})

    result = await service.review_performance(uuid4(), uuid4())

    assert result["classifications"] == {"NO_DATA_YET": 1}
    assert result["refresh_proposals"] == []
    assert result["measured"] == 0


def test_min_topic_score_is_a_real_bar():
    """Set to zero this engine would draft anything it found."""
    assert MIN_TOPIC_SCORE > 0


def _async(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner

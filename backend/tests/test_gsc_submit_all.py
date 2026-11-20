"""One action that submits everything Search Console should receive.

By hand this is four calls in a fixed order, and the order matters. The part
worth testing is the pre-flight: Google refuses every write on a property you
are not a verified owner of, with a bare 403 per call. Submitting blind returned
a pile of identical permission errors and never once mentioned verification,
which is the only thing the operator could act on.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.gsc_submit_all import OWNER_PERMISSIONS, GscSubmitAllService


def service(selected, *, sitemaps=(), submit_error=None, sync_error=None):
    svc = GscSubmitAllService.__new__(GscSubmitAllService)

    class Console:
        async def selected_project_property(self, *_):
            return {"selected_property": selected}

        async def sync_project(self, *_):
            if sync_error:
                raise sync_error
            return SimpleNamespace(id=uuid4())

    class Sitemaps:
        async def detect(self, *_):
            return list(sitemaps)

        async def list_sitemaps(self, *_):
            return list(sitemaps)

        async def submit(self, *_):
            if submit_error:
                raise submit_error
            return SimpleNamespace()

    svc.console, svc.sitemaps = Console(), Sitemaps()
    return svc


def prop(permission, url="sc-domain:example.com"):
    return SimpleNamespace(site_url=url, permission_level=permission)


@pytest.mark.asyncio
async def test_an_unverified_property_blocks_before_anything_is_attempted():
    """The measured case: Google reported 'siteUnverifiedUser' and every write
    failed 403. Stopping here turns four identical errors into one sentence."""
    result = await service(prop("siteUnverifiedUser")).run(uuid4(), uuid4())

    assert result["status"] == "blocked"
    assert result["reason"] == "not_verified_owner"
    assert result["steps"] == [], "nothing should be attempted"
    assert "verify the domain" in result["message"].lower()


@pytest.mark.asyncio
async def test_no_selected_property_blocks_with_its_own_reason():
    result = await service(None).run(uuid4(), uuid4())

    assert result["status"] == "blocked"
    assert result["reason"] == "no_property_selected"


@pytest.mark.parametrize("permission", sorted(OWNER_PERMISSIONS))
@pytest.mark.asyncio
async def test_an_owner_runs_every_step(permission):
    sitemaps = [SimpleNamespace(sitemap_url="https://example.com/sitemap.xml")]
    result = await service(prop(permission), sitemaps=sitemaps).run(uuid4(), uuid4())

    assert result["status"] == "completed"
    assert [s["step"] for s in result["steps"]] == [
        "detect_sitemaps",
        "submit_sitemaps",
        "sync_performance_data",
    ]


@pytest.mark.asyncio
async def test_a_rejected_sitemap_does_not_stop_the_sync():
    """The steps are independent, and partial progress is worth keeping."""
    sitemaps = [SimpleNamespace(sitemap_url="https://example.com/sitemap.xml")]
    result = await service(
        prop("siteOwner"), sitemaps=sitemaps, submit_error=RuntimeError("Google said no")
    ).run(uuid4(), uuid4())

    steps = {s["step"]: s for s in result["steps"]}
    assert steps["submit_sitemaps"]["status"] == "failed"
    assert steps["sync_performance_data"]["status"] == "ok"
    assert result["status"] == "partial"


@pytest.mark.asyncio
async def test_no_sitemap_is_skipped_with_advice_not_failed():
    """Having no sitemap is a thing to fix on the site, not an error here."""
    result = await service(prop("siteOwner"), sitemaps=[]).run(uuid4(), uuid4())

    step = next(s for s in result["steps"] if s["step"] == "submit_sitemaps")
    assert step["status"] == "skipped"
    assert "robots.txt" in step["detail"]


def test_unverified_is_not_treated_as_an_owner():
    assert "siteUnverifiedUser" not in OWNER_PERMISSIONS

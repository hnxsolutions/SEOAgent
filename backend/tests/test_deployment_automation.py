"""Tests for deployment provider adapters + site validation helpers."""
from app.deployment.adapters import (
    NetlifyAdapter,
    UnconfiguredAdapter,
    VercelAdapter,
    get_adapter,
    provider_health,
)
from app.models.deployment import DeploymentProvider, DeploymentStatus
from app.services.site_validation import SiteValidationService


def test_provider_health_lists_all_providers_unconfigured_without_creds():
    health = {p["provider"]: p["configured"] for p in provider_health()}
    assert set(health) == {"vercel", "netlify", "cloudflare_pages", "aws_amplify"}
    # No credentials configured in the test environment.
    assert all(v is False for v in health.values())


def test_get_adapter_returns_unconfigured_without_creds():
    adapter = get_adapter(DeploymentProvider.vercel)
    assert isinstance(adapter, UnconfiguredAdapter)


def test_vercel_state_mapping():
    m = VercelAdapter._map_state
    assert m("READY") == DeploymentStatus.success
    assert m("BUILDING") == DeploymentStatus.building
    assert m("QUEUED") == DeploymentStatus.pending
    assert m("ERROR") == DeploymentStatus.failed
    assert m("CANCELED") == DeploymentStatus.failed
    assert m(None) == DeploymentStatus.pending


def test_netlify_state_mapping():
    m = NetlifyAdapter._map_state
    assert m("ready") == DeploymentStatus.success
    assert m("building") == DeploymentStatus.building
    assert m("error") == DeploymentStatus.failed
    assert m("new") == DeploymentStatus.pending


import pytest


@pytest.mark.asyncio
async def test_unconfigured_adapter_never_fabricates():
    adapter = UnconfiguredAdapter(DeploymentProvider.vercel)
    assert adapter.configured is False
    assert await adapter.get_by_commit("abc1234") is None


def test_site_validation_normalize_domain():
    n = SiteValidationService._normalize
    assert n("example.com") == "https://example.com"
    assert n("https://www.example.com/") == "https://www.example.com"
    assert n("http://foo.test/path") == "http://foo.test/path"

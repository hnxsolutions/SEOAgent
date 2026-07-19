"""Deployment provider adapters (common interface).

Each adapter maps a provider's deployment API onto one DeploymentInfo shape. When
a provider token is absent the adapter reports ``configured == False`` and
returns None — it never fabricates provider data. Real API calls are made only
when credentials are present (Credential Gated otherwise).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from app.core.config import settings
from app.models.deployment import DeploymentProvider, DeploymentStatus

logger = structlog.get_logger(__name__)


@dataclass
class DeploymentInfo:
    deployment_id: Optional[str]
    status: DeploymentStatus
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    logs_url: Optional[str] = None
    deployment_url: Optional[str] = None
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    environment: Optional[str] = None


class DeploymentProviderAdapter:
    provider: DeploymentProvider = DeploymentProvider.unknown

    @property
    def configured(self) -> bool:
        return False

    async def get_by_commit(self, commit_sha: str) -> Optional[DeploymentInfo]:
        """Return the latest deployment for a commit, or None if not configured
        / not found. Must never fabricate data."""
        return None


class UnconfiguredAdapter(DeploymentProviderAdapter):
    """Used when a provider has no credentials — honest no-op."""

    def __init__(self, provider: DeploymentProvider):
        self.provider = provider

    async def get_by_commit(self, commit_sha: str) -> Optional[DeploymentInfo]:
        return None


class VercelAdapter(DeploymentProviderAdapter):
    provider = DeploymentProvider.vercel

    @property
    def configured(self) -> bool:
        return bool(settings.VERCEL_TOKEN)

    async def get_by_commit(self, commit_sha: str) -> Optional[DeploymentInfo]:
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                params = {"limit": 20}
                if settings.VERCEL_PROJECT_ID:
                    params["projectId"] = settings.VERCEL_PROJECT_ID
                r = await client.get(
                    "https://api.vercel.com/v6/deployments",
                    headers={"Authorization": f"Bearer {settings.VERCEL_TOKEN}"},
                    params=params,
                )
                r.raise_for_status()
                for d in r.json().get("deployments", []):
                    meta = d.get("meta", {}) or {}
                    if (meta.get("githubCommitSha") or "").startswith(commit_sha[:7]) or commit_sha.startswith((meta.get("githubCommitSha") or "")[:7] or "\x00"):
                        return DeploymentInfo(
                            deployment_id=d.get("uid"),
                            status=self._map_state(d.get("state") or d.get("readyState")),
                            deployment_url=("https://" + d["url"]) if d.get("url") else None,
                            commit_sha=meta.get("githubCommitSha"),
                            branch=meta.get("githubCommitRef"),
                            environment=d.get("target") or "production",
                            logs_url=f"https://vercel.com/deployments/{d.get('uid')}" if d.get("uid") else None,
                        )
        except httpx.HTTPError as exc:
            logger.warning("vercel_adapter_error", error=str(exc))
        return None

    @staticmethod
    def _map_state(state: Optional[str]) -> DeploymentStatus:
        s = (state or "").upper()
        return {
            "QUEUED": DeploymentStatus.pending,
            "INITIALIZING": DeploymentStatus.building,
            "BUILDING": DeploymentStatus.building,
            "READY": DeploymentStatus.success,
            "ERROR": DeploymentStatus.failed,
            "CANCELED": DeploymentStatus.failed,
        }.get(s, DeploymentStatus.pending)


class NetlifyAdapter(DeploymentProviderAdapter):
    provider = DeploymentProvider.netlify

    @property
    def configured(self) -> bool:
        return bool(settings.NETLIFY_TOKEN and settings.NETLIFY_SITE_ID)

    async def get_by_commit(self, commit_sha: str) -> Optional[DeploymentInfo]:
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    f"https://api.netlify.com/api/v1/sites/{settings.NETLIFY_SITE_ID}/deploys",
                    headers={"Authorization": f"Bearer {settings.NETLIFY_TOKEN}"},
                    params={"per_page": 20},
                )
                r.raise_for_status()
                for d in r.json():
                    if (d.get("commit_ref") or "").startswith(commit_sha[:7]):
                        return DeploymentInfo(
                            deployment_id=d.get("id"),
                            status=self._map_state(d.get("state")),
                            deployment_url=d.get("deploy_ssl_url") or d.get("url"),
                            commit_sha=d.get("commit_ref"),
                            branch=d.get("branch"),
                            environment=d.get("context") or "production",
                            logs_url=d.get("admin_url"),
                        )
        except httpx.HTTPError as exc:
            logger.warning("netlify_adapter_error", error=str(exc))
        return None

    @staticmethod
    def _map_state(state: Optional[str]) -> DeploymentStatus:
        s = (state or "").lower()
        return {
            "new": DeploymentStatus.pending,
            "building": DeploymentStatus.building,
            "ready": DeploymentStatus.success,
            "error": DeploymentStatus.failed,
        }.get(s, DeploymentStatus.pending)


class CloudflarePagesAdapter(DeploymentProviderAdapter):
    """Interface stub — real polling requires CLOUDFLARE_API_TOKEN + account/project."""
    provider = DeploymentProvider.cloudflare_pages

    @property
    def configured(self) -> bool:
        return bool(settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_PAGES_PROJECT)

    async def get_by_commit(self, commit_sha: str) -> Optional[DeploymentInfo]:
        # Documented interface; live polling is a follow-up once credentials exist.
        return None


class AwsAmplifyAdapter(DeploymentProviderAdapter):
    """Interface stub — real polling requires AWS credentials + AWS_AMPLIFY_APP_ID."""
    provider = DeploymentProvider.aws_amplify

    @property
    def configured(self) -> bool:
        return bool(settings.AWS_AMPLIFY_APP_ID and settings.AWS_REGION)

    async def get_by_commit(self, commit_sha: str) -> Optional[DeploymentInfo]:
        return None


_ADAPTERS = {
    DeploymentProvider.vercel: VercelAdapter,
    DeploymentProvider.netlify: NetlifyAdapter,
    DeploymentProvider.cloudflare_pages: CloudflarePagesAdapter,
    DeploymentProvider.aws_amplify: AwsAmplifyAdapter,
}


def get_adapter(provider) -> DeploymentProviderAdapter:
    """Adapter for a provider; UnconfiguredAdapter for unknown / missing creds."""
    key = provider if isinstance(provider, DeploymentProvider) else None
    if key is None:
        try:
            key = DeploymentProvider(getattr(provider, "value", provider))
        except (ValueError, TypeError):
            key = DeploymentProvider.unknown
    cls = _ADAPTERS.get(key)
    if not cls:
        return UnconfiguredAdapter(key)
    adapter = cls()
    return adapter if adapter.configured else UnconfiguredAdapter(key)


def provider_health() -> list:
    """Configured/unconfigured state of every provider adapter (no secrets)."""
    out = []
    for provider, cls in _ADAPTERS.items():
        out.append({"provider": provider.value, "configured": cls().configured})
    return out

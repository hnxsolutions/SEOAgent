"""Deployment intelligence engine.

Bridges a merged repo-agent PR to after-merge verification: it records the
deployment, and when the deployment succeeds it accelerates the linked
verifications so SEO is re-measured against the now-live site. If no deployment
signal ever arrives, verification still runs on its fallback delay so the loop
never stalls. Reuses the existing VerificationEngine — no verification logic is
duplicated.

Live provider polling (Vercel/Netlify/Cloudflare/Amplify APIs) is credential
gated; without credentials, deployment status arrives via the generic webhook or
the admin 'simulate deploy' action, and everything degrades gracefully.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.deployment import Deployment, DeploymentProvider, DeploymentStatus
from app.models.repo_agent import PullRequestRecord
from app.models.verification import AiFixVerification, VerificationStatus

logger = structlog.get_logger(__name__)

_TERMINAL_DEPLOY = {DeploymentStatus.success, DeploymentStatus.failed, DeploymentStatus.skipped}


class DeploymentEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_pending_for_pr(
        self,
        pr: PullRequestRecord,
        tenant_id: UUID,
        provider: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> Deployment:
        """Record a pending deployment for a just-merged PR (idempotent)."""
        existing = (await self.db.execute(
            select(Deployment).where(
                Deployment.pull_request_id == pr.id,
                Deployment.tenant_id == tenant_id,
            )
        )).scalars().first()
        if existing:
            return existing
        deployment = Deployment(
            tenant_id=tenant_id,
            project_id=pr.project_id,
            pull_request_id=pr.id,
            provider=self._coerce_provider(provider or settings.DEPLOYMENT_DEFAULT_PROVIDER),
            status=DeploymentStatus.pending,
            commit_sha=commit_sha or getattr(pr, "commit_sha", None),
            started_at=datetime.utcnow(),
        )
        self.db.add(deployment)
        await self.db.flush()
        return deployment

    async def update_status(
        self,
        deployment_id: UUID,
        tenant_id: UUID,
        status: str,
        *,
        deployment_url: Optional[str] = None,
        logs: Optional[str] = None,
        commit_sha: Optional[str] = None,
        external_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Deployment:
        deployment = (await self.db.execute(
            select(Deployment).where(
                Deployment.id == deployment_id, Deployment.tenant_id == tenant_id
            )
        )).scalars().first()
        if not deployment:
            raise ValueError("Deployment not found")

        new_status = self._coerce_status(status)
        deployment.status = new_status
        if deployment_url:
            deployment.deployment_url = deployment_url
        if logs:
            deployment.logs = logs
        if commit_sha:
            deployment.commit_sha = commit_sha
        if external_id:
            deployment.external_id = external_id
        if error_message:
            deployment.error_message = error_message

        if new_status in _TERMINAL_DEPLOY:
            deployment.completed_at = datetime.utcnow()
            if deployment.started_at:
                deployment.duration_seconds = int((deployment.completed_at - deployment.started_at).total_seconds())

        if new_status == DeploymentStatus.success:
            await self._accelerate_verifications(deployment.pull_request_id, tenant_id)
            await self._run_site_validation(deployment, tenant_id)
        elif new_status == DeploymentStatus.failed:
            # The fix never went live; it cannot be measured automatically.
            await self._flag_verifications_needs_review(deployment.pull_request_id, tenant_id)

        await self.db.commit()
        await self.db.refresh(deployment)
        logger.info("deployment_status_updated", deployment_id=str(deployment.id), status=new_status.value)
        return deployment

    async def _accelerate_verifications(self, pull_request_id: Optional[UUID], tenant_id: UUID) -> int:
        if not pull_request_id:
            return 0
        verifs = (await self.db.execute(
            select(AiFixVerification).where(
                AiFixVerification.pull_request_id == pull_request_id,
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.status == VerificationStatus.pending,
            )
        )).scalars().all()
        due = datetime.utcnow()
        for v in verifs:
            v.scheduled_at = due  # deployment is live -> verification is due now
        return len(verifs)

    async def _flag_verifications_needs_review(self, pull_request_id: Optional[UUID], tenant_id: UUID) -> int:
        if not pull_request_id:
            return 0
        verifs = (await self.db.execute(
            select(AiFixVerification).where(
                AiFixVerification.pull_request_id == pull_request_id,
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.status == VerificationStatus.pending,
            )
        )).scalars().all()
        for v in verifs:
            v.status = VerificationStatus.needs_human_review
            v.details = {**(v.details or {}), "deployment": "failed"}
        return len(verifs)

    async def _run_site_validation(self, deployment: Deployment, tenant_id: UUID) -> None:
        """Validate the live site once a deployment is Ready (best-effort)."""
        try:
            from app.services.site_validation import SiteValidationService

            await SiteValidationService(self.db).validate(
                deployment.project_id, tenant_id,
                url=deployment.deployment_url, deployment_id=deployment.id,
            )
        except Exception:  # pragma: no cover - never break the deploy flow
            logger.warning("deployment_site_validation_failed", deployment_id=str(deployment.id))

    async def poll_deployment(self, deployment_id: UUID, tenant_id: UUID) -> Deployment:
        """Poll the provider adapter for a deployment's live status and update it.

        Credential-gated: when the provider has no token the adapter returns None
        and the deployment is left unchanged (never fabricated)."""
        deployment = await self.get_deployment(deployment_id, tenant_id)
        if not deployment:
            raise ValueError("Deployment not found")
        if deployment.status in _TERMINAL_DEPLOY:
            return deployment

        from app.deployment.adapters import get_adapter

        adapter = get_adapter(deployment.provider)
        if not adapter.configured or not deployment.commit_sha:
            return deployment  # gracefully leave as-is
        info = await adapter.get_by_commit(deployment.commit_sha)
        if not info:
            return deployment
        return await self.update_status(
            deployment_id, tenant_id, info.status.value,
            deployment_url=info.deployment_url, external_id=info.deployment_id,
        )

    async def poll_active_deployments(self, tenant_id: Optional[UUID] = None, limit: int = 25) -> int:
        """Scheduler entry: poll every non-terminal deployment via its adapter."""
        query = select(Deployment).where(Deployment.status.in_([DeploymentStatus.pending, DeploymentStatus.building]))
        if tenant_id:
            query = query.where(Deployment.tenant_id == tenant_id)
        active = (await self.db.execute(query.limit(limit))).scalars().all()
        polled = 0
        for d in active:
            try:
                await self.poll_deployment(d.id, d.tenant_id)
                polled += 1
            except Exception:  # pragma: no cover
                logger.warning("poll_deployment_failed", deployment_id=str(d.id))
        return polled

    async def deployment_stats(self, tenant_id: UUID) -> Dict[str, Any]:
        """Production evidence for the learning engine + Mission Control."""
        rows = (await self.db.execute(
            select(Deployment.status, func.count(Deployment.id), func.avg(Deployment.duration_seconds))
            .where(Deployment.tenant_id == tenant_id)
            .group_by(Deployment.status)
        )).all()
        by_status: Dict[str, int] = {}
        durations = []
        for status, count, avg_dur in rows:
            by_status[self._status_value(status)] = int(count)
            if avg_dur is not None:
                durations.append(float(avg_dur))
        success = by_status.get("success", 0)
        failed = by_status.get("failed", 0)
        finalized = success + failed
        # Per-provider reliability.
        prov_rows = (await self.db.execute(
            select(Deployment.provider, Deployment.status, func.count(Deployment.id))
            .where(Deployment.tenant_id == tenant_id)
            .group_by(Deployment.provider, Deployment.status)
        )).all()
        providers: Dict[str, Dict[str, int]] = {}
        for provider, status, count in prov_rows:
            p = providers.setdefault(self._status_value(provider), {"success": 0, "failed": 0, "total": 0})
            sv = self._status_value(status)
            if sv in ("success", "failed"):
                p[sv] += int(count)
            p["total"] += int(count)
        for p in providers.values():
            fin = p["success"] + p["failed"]
            p["reliability"] = round(p["success"] / fin * 100, 1) if fin else None
        return {
            "by_status": by_status,
            "success_rate": round(success / finalized * 100, 1) if finalized else None,
            "failure_rate": round(failed / finalized * 100, 1) if finalized else None,
            "avg_duration_seconds": round(sum(durations) / len(durations)) if durations else None,
            "provider_reliability": providers,
        }

    @staticmethod
    def _status_value(v):
        return getattr(v, "value", v)

    async def list_deployments(self, project_id: UUID, tenant_id: UUID, limit: int = 50) -> List[Deployment]:
        rows = await self.db.execute(
            select(Deployment).where(
                Deployment.project_id == project_id, Deployment.tenant_id == tenant_id
            ).order_by(Deployment.created_at.desc()).limit(limit)
        )
        return list(rows.scalars().all())

    async def get_deployment(self, deployment_id: UUID, tenant_id: UUID) -> Optional[Deployment]:
        return (await self.db.execute(
            select(Deployment).where(
                Deployment.id == deployment_id, Deployment.tenant_id == tenant_id
            )
        )).scalars().first()

    @staticmethod
    def _coerce_provider(value) -> DeploymentProvider:
        try:
            return DeploymentProvider(getattr(value, "value", value))
        except (ValueError, TypeError):
            return DeploymentProvider.unknown

    @staticmethod
    def _coerce_status(value) -> DeploymentStatus:
        try:
            return DeploymentStatus(getattr(value, "value", value))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid deployment status: {value}")

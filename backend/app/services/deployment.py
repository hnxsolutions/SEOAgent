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
from sqlalchemy import select
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

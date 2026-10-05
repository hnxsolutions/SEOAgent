"""Turns a measured decline into an approvable proposal, and nothing more.

Phase 1 could detect that an article had lost impressions; the finding lived in
a scheduled job's summary and was gone as soon as nobody was reading the log.
This persists it, with the evidence attached, and routes it through a human.

**The agent never edits a published article on its own.** `apply` is reachable
only from `approved`, and `approve` is an explicit human action. An article
somebody wrote is not something to rewrite on the strength of a 28-day dip.

Duplicate suppression is a partial unique index rather than a service check:
the weekly job will raise "impressions are down" every Friday until somebody
acts, and the queue has to stay readable. Once a proposal is resolved the index
no longer covers it, so a genuine recurrence months later can be raised again.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_refresh import (
    ContentRefreshProposal,
    RefreshReason,
    RefreshStatus,
)

logger = structlog.get_logger(__name__)


#: Moves allowed on a proposal. `applied` is reachable only via `approved`,
#: which is the whole safety property.
TRANSITIONS: Dict[str, set] = {
    RefreshStatus.detected.value: {RefreshStatus.pending_approval.value, RefreshStatus.rejected.value},
    RefreshStatus.pending_approval.value: {RefreshStatus.approved.value, RefreshStatus.rejected.value},
    RefreshStatus.approved.value: {RefreshStatus.applied.value, RefreshStatus.rejected.value},
    RefreshStatus.applied.value: {RefreshStatus.verified.value},
    RefreshStatus.verified.value: set(),
    RefreshStatus.rejected.value: set(),
}


class RefreshTransitionError(ValueError):
    """An illegal move on a proposal, named so the API can return it verbatim."""


class ContentRefreshService:
    """Creates, lists and advances refresh proposals."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def propose(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        title: str,
        reason: RefreshReason,
        summary: str,
        evidence: Dict[str, Any],
        proposed_changes: List[Dict[str, Any]],
        priority: float,
        blog_draft_id: Optional[UUID] = None,
        page_url: Optional[str] = None,
        commit: bool = True,
    ) -> Optional[ContentRefreshProposal]:
        """Record a proposal, or return None if one is already open for this reason."""
        proposal = ContentRefreshProposal(
            tenant_id=tenant_id,
            project_id=project_id,
            blog_draft_id=blog_draft_id,
            page_url=page_url,
            title=title[:500],
            reason=reason,
            status=RefreshStatus.pending_approval,
            summary=summary,
            evidence=evidence or {},
            proposed_changes=proposed_changes or [],
            priority=max(0.0, min(100.0, float(priority))),
            detected_at=datetime.utcnow(),
        )
        try:
            async with self.db.begin_nested():
                self.db.add(proposal)
        except IntegrityError:
            # The partial unique index did its job: a proposal for this article
            # and reason is already waiting. Raising it again would only make
            # the queue longer, not more informative.
            logger.info(
                "refresh_proposal_already_open",
                project_id=str(project_id), reason=reason.value,
            )
            return None

        if commit:
            await self.db.commit()
            await self.db.refresh(proposal)
        return proposal

    async def list_proposals(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        status: Optional[RefreshStatus] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = select(ContentRefreshProposal).where(
            ContentRefreshProposal.project_id == project_id,
            ContentRefreshProposal.tenant_id == tenant_id,
        )
        if status is not None:
            query = query.where(ContentRefreshProposal.status == status)
        result = await self.db.execute(
            query.order_by(ContentRefreshProposal.priority.desc()).limit(limit)
        )
        return [self.to_dict(p) for p in result.scalars().all()]

    async def get(self, proposal_id: UUID, tenant_id: UUID) -> Optional[ContentRefreshProposal]:
        result = await self.db.execute(
            select(ContentRefreshProposal).where(
                ContentRefreshProposal.id == proposal_id,
                ContentRefreshProposal.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def transition(
        self,
        proposal_id: UUID,
        tenant_id: UUID,
        target: RefreshStatus,
        *,
        actor: str = "system",
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Advance a proposal, refusing any move the workflow does not allow."""
        proposal = await self.get(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("Refresh proposal not found")

        current = proposal.status.value if hasattr(proposal.status, "value") else str(proposal.status)
        if target.value not in TRANSITIONS.get(current, set()):
            raise RefreshTransitionError(
                f"A refresh proposal cannot go from {current} to {target.value}. "
                f"Allowed from {current}: {sorted(TRANSITIONS.get(current, set())) or 'nothing — this is a final state'}."
            )

        now = datetime.utcnow()
        proposal.status = target
        proposal.reviewed_by = actor
        proposal.reviewed_at = now

        if target is RefreshStatus.approved:
            proposal.approved_at = now
        elif target is RefreshStatus.rejected:
            proposal.rejection_reason = (reason or "")[:2000]
        elif target is RefreshStatus.applied:
            proposal.applied_at = now
        elif target is RefreshStatus.verified:
            proposal.verified_at = now

        await self.db.commit()
        await self.db.refresh(proposal)
        logger.info(
            "refresh_proposal_transitioned",
            proposal_id=str(proposal_id), **{"from": current, "to": target.value}, actor=actor,
        )
        return self.to_dict(proposal)

    def to_dict(self, proposal: ContentRefreshProposal) -> Dict[str, Any]:
        def enum_value(value):
            return value.value if hasattr(value, "value") else value

        return {
            "id": str(proposal.id),
            "title": proposal.title,
            "page_url": proposal.page_url,
            "blog_draft_id": str(proposal.blog_draft_id) if proposal.blog_draft_id else None,
            "reason": enum_value(proposal.reason),
            "status": enum_value(proposal.status),
            "summary": proposal.summary,
            "evidence": proposal.evidence or {},
            "proposed_changes": proposal.proposed_changes or [],
            "priority": proposal.priority,
            "detected_at": proposal.detected_at.isoformat() if proposal.detected_at else None,
            "approved_at": proposal.approved_at.isoformat() if proposal.approved_at else None,
            "reviewed_by": proposal.reviewed_by,
            "rejection_reason": proposal.rejection_reason,
            "next_actions": sorted(TRANSITIONS.get(enum_value(proposal.status), set())),
        }

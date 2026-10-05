"""Refresh proposals — a decline detected, written down, and waiting for a human.

Phase 1 could already tell that an article had lost impressions. It said so in
a scheduled job's summary and then forgot, which meant the finding existed for
exactly as long as somebody was looking at the log. A proposal has to outlive
the job that produced it to be actionable.

**Nothing here edits an article.** The default path is
DETECTED → PENDING_APPROVAL → (human) → APPROVED → APPLIED → VERIFIED, and
`APPLIED` is only ever reached through an explicit approval. Overwriting a
published article that someone wrote, on the strength of a 28-day impression
dip, is not a decision an agent should make unattended.

The evidence that triggered a proposal is stored alongside it. A reviewer asked
to approve a rewrite needs to see the numbers that prompted it, months later,
without re-running the query that found them.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class RefreshStatus(str, enum.Enum):
    detected = "detected"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"
    verified = "verified"


class RefreshReason(str, enum.Enum):
    """Why the article was flagged. One per proposal, the strongest signal."""

    declining_impressions = "declining_impressions"
    declining_clicks = "declining_clicks"
    position_drop = "position_drop"
    low_ctr = "low_ctr"
    new_queries = "new_queries"          # ranking for things it does not cover
    thin_coverage = "thin_coverage"
    cannibalisation = "cannibalisation"
    outdated = "outdated"


class ContentRefreshProposal(Base):
    """One proposal to update one published article."""

    __tablename__ = "content_refresh_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: The article. A draft that was published, or a crawled page when the
    #: content predates this system.
    blog_draft_id = Column(
        UUID(as_uuid=True), ForeignKey("blog_drafts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    page_url = Column(String(2048), nullable=True)
    title = Column(String(500), nullable=False)

    reason = Column(SQLEnum(RefreshReason), nullable=False, index=True)
    status = Column(
        SQLEnum(RefreshStatus), nullable=False, default=RefreshStatus.detected, index=True
    )

    #: Plain-language statement of what was observed, for the approval screen.
    summary = Column(Text, nullable=False)
    #: The measurements behind it: impressions/clicks/position, both windows.
    #: Stored so the decision is auditable long after the window has rolled.
    evidence = Column(JSONB, nullable=False, default=dict)
    #: What the agent suggests changing: [{section, action, why}].
    proposed_changes = Column(JSONB, nullable=False, default=list)

    #: 0-100, from the size of the decline and the traffic at stake.
    priority = Column(Float, nullable=False, default=0.0)

    reviewed_by = Column(String(255), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # One open proposal per article per reason. Without this, a weekly job
        # raises the same "impressions are down" proposal every Friday until
        # somebody acts, and the queue becomes unreadable.
        Index(
            "uq_refresh_open_per_article_reason",
            "project_id", "blog_draft_id", "reason",
            unique=True,
            postgresql_where=text("status IN ('detected', 'pending_approval')"),
        ),
        Index("ix_refresh_tenant_status", "tenant_id", "status"),
        Index("ix_refresh_project_priority", "project_id", "priority"),
    )

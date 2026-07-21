"""Post-merge deployment & verification models.

A DeploymentVerification records the after-merge engineering loop for an approved
code review: detect deployment -> verify the REAL live site -> PageSpeed / Core
Web Vitals -> Search Console -> compare before vs after (measured, never
predicted) -> feed the Learning Engine. It also carries the project activity
timeline for the dashboard.

This model only VERIFIES a deployed site; it never modifies production.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class VerificationRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    gated = "gated"          # measurable parts ran; merge/deploy/GSC need credentials


class DeploymentVerification(Base):
    __tablename__ = "deployment_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    review_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    status = Column(SQLEnum(VerificationRunStatus), default=VerificationRunStatus.pending, nullable=False, index=True)

    # deployment
    deployment_provider = Column(String(64), nullable=True)
    deployment_status = Column(String(64), nullable=True)
    deployment_url = Column(String(1024), nullable=True)
    deployment_id = Column(UUID(as_uuid=True), nullable=True)

    # live-site verification (real checks against the deployed URL)
    live_site = Column(JSONB, nullable=True)          # {reachable, http_status, checks{...}}

    # measured before/after
    pagespeed_before = Column(JSONB, nullable=True)
    pagespeed_after = Column(JSONB, nullable=True)
    cwv_comparison = Column(JSONB, nullable=True)      # {lcp, cls, inp: {before, after, verdict}}
    seo_before = Column(Integer, nullable=True)
    seo_after = Column(Integer, nullable=True)
    seo_comparison = Column(JSONB, nullable=True)      # per-dimension improved/declined/no_change

    gsc_status = Column(String(64), nullable=True)

    # evidence-based learning outcome
    learning_outcome = Column(JSONB, nullable=True)    # {direction, confidence_delta, reason}

    timeline = Column(JSONB, nullable=False, default=list)   # [{time, event}]
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DeploymentVerification {self.project_id} {self.status}>"

"""After-merge verification models.

One AiFixVerification row is created per applied patch when its pull request is
merged. It captures the baseline SEO run, the follow-up (post-merge) SEO run and
the measured outcome, and doubles as the historical record the learning /
confidence engine aggregates over. Foreign keys reuse existing entities
(patches, issues, PRs, SEO runs) — no data is duplicated.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class VerificationStatus(str, enum.Enum):
    pending = "pending"                  # queued, waiting for the delay / follow-up run
    running = "running"                  # follow-up analysis in progress
    verified_success = "verified_success"
    partially_successful = "partially_successful"
    failed = "failed"
    needs_human_review = "needs_human_review"


class AiFixVerification(Base):
    __tablename__ = "ai_fix_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    # Traceability (reused FKs).
    patch_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_patches.id"), nullable=False, index=True)
    pull_request_id = Column(UUID(as_uuid=True), ForeignKey("pull_request_records.id"), nullable=True, index=True)
    issue_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_issues.id"), nullable=True, index=True)
    # Denormalized type strings for cheap learning aggregation (not new facts).
    patch_type = Column(String(64), nullable=False, index=True)
    issue_type = Column(String(64), nullable=True, index=True)

    status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.pending, nullable=False, index=True)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    verified_at = Column(DateTime, nullable=True)

    baseline_seo_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_runs.id"), nullable=True)
    followup_seo_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_runs.id"), nullable=True)
    baseline_score = Column(Float, nullable=True)
    followup_score = Column(Float, nullable=True)

    issue_resolved = Column(Boolean, nullable=True)
    improvement_pct = Column(Float, nullable=True)
    details = Column(JSONB, nullable=True)  # resolved / still-existing / new issue counts, before/after
    merged_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_ai_fix_verifications_project_status", "project_id", "status"),
        Index("ix_ai_fix_verifications_patchtype_status", "patch_type", "status"),
    )

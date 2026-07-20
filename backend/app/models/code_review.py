"""Code review / human approval models.

A CodeReview is the human approval gate for a set of framework-safe generated SEO
patches. Nothing reaches production until an admin approves it here — the AI
prepares the review (validate -> branch -> commit -> draft PR) and then WAITS.
Approve is an explicit admin action that merges the PR; nothing merges
automatically.

Only SEO-safe files are ever part of a review; the generator + pipeline already
refuse UI / business-logic / auth / payments / CRM / database targets.
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


class CodeReviewStatus(str, enum.Enum):
    ready_for_review = "ready_for_review"
    approved = "approved"       # admin approved; merge attempted
    merged = "merged"           # PR merged into base
    rejected = "rejected"
    archived = "archived"


class ReviewRisk(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    blocked = "blocked"         # should never occur — safety refuses these first


class CodeReview(Base):
    __tablename__ = "code_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    pipeline_id = Column(UUID(as_uuid=True), nullable=True)  # PatchPipeline that built the PR (if any)

    framework = Column(String(64), nullable=True)
    technology = Column(String(255), nullable=True)   # human-readable stack summary
    status = Column(SQLEnum(CodeReviewStatus), default=CodeReviewStatus.ready_for_review, nullable=False, index=True)
    risk_level = Column(SQLEnum(ReviewRisk), default=ReviewRisk.low, nullable=False, index=True)

    confidence = Column(Integer, nullable=True)       # avg confidence of the patches
    files_count = Column(Integer, default=0)

    estimated_seo_impact = Column(String(64), nullable=True)          # e.g. "High (+8-12)"
    estimated_performance_impact = Column(String(64), nullable=True)
    seo_before = Column(Integer, nullable=True)
    seo_after_predicted = Column(Integer, nullable=True)

    pr_url = Column(String(1024), nullable=True)
    pr_status = Column(String(64), nullable=True)
    commit_sha = Column(String(64), nullable=True)
    merge_sha = Column(String(64), nullable=True)
    deployment_status = Column(String(64), nullable=True)

    # Snapshot of the GeneratedSeoPatch ids under review (stable review contents).
    patch_ids = Column(JSONB, nullable=False, default=list)

    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by = Column(String(255), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CodeReview {self.project_id} {self.status} risk={self.risk_level}>"

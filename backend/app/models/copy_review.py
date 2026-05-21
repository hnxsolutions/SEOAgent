"""SEO copy quality and compliance review models."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class SeoCopySourceType(str, enum.Enum):
    repo_patch = "repo_patch"
    content_suggestion = "content_suggestion"
    blog_draft = "blog_draft"
    faq_suggestion = "faq_suggestion"
    schema_suggestion = "schema_suggestion"
    metadata = "metadata"


class SeoCopyApprovalReadiness(str, enum.Enum):
    ready = "ready"
    needs_revision = "needs_revision"
    manual_review = "manual_review"
    rejected = "rejected"


class SeoCopyComplianceProfile(str, enum.Enum):
    default = "default"
    healthcare = "healthcare"
    pharma_b2b = "pharma_b2b"
    finance = "finance"
    legal = "legal"
    ecommerce = "ecommerce"


class SeoCopyRevisionStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class SeoCopyReview(Base):
    """A persisted review of SEO copy quality and compliance."""

    __tablename__ = "seo_copy_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    source_type = Column(SQLEnum(SeoCopySourceType), nullable=False, index=True)
    source_reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    page_url = Column(String(2048), nullable=True, index=True)
    target_keyword = Column(String(1000), nullable=True, index=True)
    original_title = Column(Text, nullable=True)
    original_description = Column(Text, nullable=True)
    reviewed_title = Column(Text, nullable=True)
    reviewed_description = Column(Text, nullable=True)
    quality_score = Column(Float, nullable=False, default=0)
    compliance_score = Column(Float, nullable=False, default=0)
    approval_readiness = Column(
        SQLEnum(SeoCopyApprovalReadiness),
        nullable=False,
        default=SeoCopyApprovalReadiness.needs_revision,
        index=True,
    )
    issues = Column(JSONB, nullable=True)
    revision_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_seo_copy_reviews_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_copy_reviews_source", "source_type", "source_reference_id"),
        Index("ix_seo_copy_reviews_readiness", "approval_readiness", "created_at"),
    )


class SeoCopyPolicy(Base):
    """Project-level SEO copy compliance policy."""

    __tablename__ = "seo_copy_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    compliance_profile = Column(
        SQLEnum(SeoCopyComplianceProfile),
        nullable=False,
        default=SeoCopyComplianceProfile.default,
        index=True,
    )
    blocked_phrases = Column(JSONB, nullable=True)
    allowed_topics = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_seo_copy_policies_tenant_project", "tenant_id", "project_id"),
    )


class SeoCopyRevision(Base):
    """A proposed or accepted revision created from a copy review."""

    __tablename__ = "seo_copy_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    review_id = Column(UUID(as_uuid=True), ForeignKey("seo_copy_reviews.id"), nullable=False, index=True)
    source_type = Column(SQLEnum(SeoCopySourceType), nullable=False, index=True)
    source_reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    revised_title = Column(Text, nullable=True)
    revised_description = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    compliance_notes = Column(JSONB, nullable=True)
    status = Column(
        SQLEnum(SeoCopyRevisionStatus),
        nullable=False,
        default=SeoCopyRevisionStatus.pending,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_seo_copy_revisions_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_copy_revisions_source", "source_type", "source_reference_id"),
    )

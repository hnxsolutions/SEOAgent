"""Models for deterministic internal linking recommendations."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class InternalLinkRecommendationStatus(str, enum.Enum):
    suggested = "suggested"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"


class InternalLinkRecommendationType(str, enum.Enum):
    semantic_related = "semantic_related"
    orphan_support = "orphan_support"
    weak_page_support = "weak_page_support"
    hub_spoke = "hub_spoke"
    audit_issue_support = "audit_issue_support"


class InternalLinkRecommendation(Base):
    """A deterministic internal link recommendation for crawled pages."""

    __tablename__ = "internal_link_recommendations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    source_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=False, index=True)
    source_url = Column(String(2048), nullable=False)
    target_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=False, index=True)
    target_url = Column(String(2048), nullable=False)

    suggested_anchor_text = Column(String(255), nullable=False)
    suggested_context_snippet = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)
    confidence_score = Column(Float, nullable=False)
    priority_score = Column(Float, nullable=False)
    status = Column(
        SQLEnum(InternalLinkRecommendationStatus),
        default=InternalLinkRecommendationStatus.suggested,
        nullable=False,
        index=True,
    )
    recommendation_type = Column(SQLEnum(InternalLinkRecommendationType), nullable=False, index=True)
    semantic_similarity = Column(Float, nullable=True)
    evidence = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_internal_link_recs_tenant_crawl", "tenant_id", "crawl_job_id"),
        Index("ix_internal_link_recs_source_target", "source_page_id", "target_page_id"),
        Index(
            "ix_internal_link_recs_dedupe",
            "tenant_id",
            "crawl_job_id",
            "source_page_id",
            "target_page_id",
            "recommendation_type",
            unique=True,
        ),
        Index("ix_internal_link_recs_priority", "priority_score"),
    )

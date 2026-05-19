"""Models for GEO/AEO scoring and recommendations."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class GeoAeoRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class GeoAeoRecommendationType(str, enum.Enum):
    answer_block = "answer_block"
    faq = "faq"
    schema = "schema"
    entity_clarity = "entity_clarity"
    factual_claims = "factual_claims"
    trust_signal = "trust_signal"
    internal_link_support = "internal_link_support"
    topical_gap = "topical_gap"


class GeoAeoRecommendationStatus(str, enum.Enum):
    suggested = "suggested"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"


class GeoAeoRun(Base):
    """A deterministic GEO/AEO scoring run for a completed crawl."""

    __tablename__ = "geo_aeo_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    status = Column(SQLEnum(GeoAeoRunStatus), default=GeoAeoRunStatus.pending, nullable=False, index=True)
    progress = Column(Integer, default=0)
    model = Column(String(255), nullable=True)

    total_pages = Column(Integer, default=0)
    total_recommendations = Column(Integer, default=0)
    average_geo_score = Column(Float, default=0)
    average_aeo_score = Column(Float, default=0)
    average_citation_readiness_score = Column(Float, default=0)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    page_scores = relationship("GeoAeoPageScore", back_populates="run", cascade="all, delete-orphan")
    recommendations = relationship("GeoAeoRecommendation", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_geo_aeo_runs_tenant_crawl", "tenant_id", "crawl_id"),
        Index("ix_geo_aeo_runs_created", "created_at", postgresql_using="brin"),
    )


class GeoAeoPageScore(Base):
    """Page-level AI-search readiness and answer-engine score."""

    __tablename__ = "geo_aeo_page_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("geo_aeo_runs.id"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    crawl_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=False, index=True)

    url = Column(String(2048), nullable=False)
    geo_score = Column(Float, nullable=False)
    aeo_score = Column(Float, nullable=False)
    citation_readiness_score = Column(Float, nullable=False)
    answer_block_score = Column(Float, nullable=False)
    entity_clarity_score = Column(Float, nullable=False)
    schema_readiness_score = Column(Float, nullable=False)
    trust_signal_score = Column(Float, nullable=False)
    topical_completeness_score = Column(Float, nullable=False)

    score_breakdown = Column(JSONB, nullable=True)
    extracted_entities = Column(JSONB, nullable=True)
    extracted_claims = Column(JSONB, nullable=True)
    evidence = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    run = relationship("GeoAeoRun", back_populates="page_scores")

    __table_args__ = (
        Index("ix_geo_aeo_page_scores_run_page", "run_id", "page_id", unique=True),
        Index("ix_geo_aeo_page_scores_tenant_crawl", "tenant_id", "crawl_id"),
        Index("ix_geo_aeo_page_scores_geo", "geo_score"),
        Index("ix_geo_aeo_page_scores_aeo", "aeo_score"),
    )


class GeoAeoRecommendation(Base):
    """A GEO/AEO improvement recommendation that never auto-applies content."""

    __tablename__ = "geo_aeo_recommendations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("geo_aeo_runs.id"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    crawl_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=False, index=True)

    recommendation_type = Column(SQLEnum(GeoAeoRecommendationType), nullable=False, index=True)
    recommendation_text = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    priority_score = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    status = Column(
        SQLEnum(GeoAeoRecommendationStatus),
        default=GeoAeoRecommendationStatus.suggested,
        nullable=False,
        index=True,
    )
    content_hash = Column(String(64), nullable=False, index=True)
    evidence = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    run = relationship("GeoAeoRun", back_populates="recommendations")

    __table_args__ = (
        Index("ix_geo_aeo_recs_tenant_crawl", "tenant_id", "crawl_id"),
        Index("ix_geo_aeo_recs_page_type", "page_id", "recommendation_type"),
        Index(
            "ix_geo_aeo_recs_dedupe",
            "tenant_id",
            "crawl_id",
            "page_id",
            "recommendation_type",
            "content_hash",
            unique=True,
        ),
        Index("ix_geo_aeo_recs_priority", "priority_score"),
    )

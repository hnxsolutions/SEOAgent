"""One-click SEO analysis run models."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class SeoRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class SeoRunStage(str, enum.Enum):
    crawl = "crawl"
    audit = "audit"
    semantic_index = "semantic_index"
    content_optimization = "content_optimization"
    planner = "planner"
    completed = "completed"


class SeoRunStageStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    skipped_or_failed = "skipped_or_failed"
    failed = "failed"


class SeoRun(Base):
    """A top-level project SEO run across crawl, audit, semantic, content, and planner."""

    __tablename__ = "seo_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    status = Column(SQLEnum(SeoRunStatus), default=SeoRunStatus.queued, nullable=False, index=True)
    current_stage = Column(SQLEnum(SeoRunStage), default=SeoRunStage.crawl, nullable=False, index=True)
    stage_statuses = Column(JSONB, nullable=False, default=dict)
    stage_errors = Column(JSONB, nullable=False, default=dict)

    crawl_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=True, index=True)
    audit_id = Column(UUID(as_uuid=True), ForeignKey("seo_audit_runs.id"), nullable=True, index=True)
    semantic_index_run_id = Column(UUID(as_uuid=True), ForeignKey("semantic_index_runs.id"), nullable=True, index=True)
    content_optimization_run_id = Column(UUID(as_uuid=True), ForeignKey("content_optimization_runs.id"), nullable=True, index=True)
    planner_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_planner_runs.id"), nullable=True, index=True)

    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_seo_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_runs_status_created", "status", "created_at"),
    )

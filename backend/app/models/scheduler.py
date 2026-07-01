"""Production scheduler models for recurring SEO automation."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SeoScheduleType(str, enum.Enum):
    daily_gsc_sync = "daily_gsc_sync"
    weekly_full_seo = "weekly_full_seo"
    weekly_blog_planning = "weekly_blog_planning"
    weekly_repo_scan = "weekly_repo_scan"
    weekly_indexing_monitor = "weekly_indexing_monitor"
    monthly_deep_audit = "monthly_deep_audit"


class SeoScheduleFrequency(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class SeoScheduledRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class SeoSchedule(Base):
    """A recurring automation schedule for one project."""

    __tablename__ = "seo_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    schedule_type = Column(SQLEnum(SeoScheduleType), nullable=False, index=True)
    frequency = Column(SQLEnum(SeoScheduleFrequency), nullable=False, index=True)
    day_of_week = Column(Integer, nullable=True)
    day_of_month = Column(Integer, nullable=True)
    hour = Column(Integer, nullable=False, default=9)
    minute = Column(Integer, nullable=False, default=0)
    timezone = Column(String(64), nullable=False, default="UTC")
    is_enabled = Column(Boolean, nullable=False, default=True, index=True)
    last_run_at = Column(DateTime, nullable=True, index=True)
    next_run_at = Column(DateTime, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    runs = relationship("SeoScheduledRun", back_populates="schedule", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_seo_schedules_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_schedules_due", "is_enabled", "next_run_at"),
    )


class SeoScheduledRun(Base):
    """One execution attempt for a recurring schedule."""

    __tablename__ = "seo_scheduled_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("seo_schedules.id"), nullable=False, index=True)

    status = Column(SQLEnum(SeoScheduledRunStatus), default=SeoScheduledRunStatus.queued, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    planner_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_planner_runs.id"), nullable=True, index=True)
    gsc_sync_job_id = Column(UUID(as_uuid=True), ForeignKey("gsc_sync_jobs.id"), nullable=True, index=True)
    crawl_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=True, index=True)
    audit_id = Column(UUID(as_uuid=True), ForeignKey("seo_audit_runs.id"), nullable=True, index=True)
    semantic_run_id = Column(UUID(as_uuid=True), ForeignKey("semantic_index_runs.id"), nullable=True, index=True)
    repo_scan_run_id = Column(UUID(as_uuid=True), ForeignKey("repo_scan_runs.id"), nullable=True, index=True)
    blog_plan_id = Column(UUID(as_uuid=True), ForeignKey("blog_plans.id"), nullable=True, index=True)

    summary = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    schedule = relationship("SeoSchedule", back_populates="runs")

    __table_args__ = (
        Index("ix_seo_scheduled_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_scheduled_runs_schedule_status", "schedule_id", "status"),
    )

"""Scheduler / worker telemetry models.

One SchedulerJobRun row is written per background job execution (scheduler tick,
SEO run, dispatch, verification, briefing, ...). It is the single source of truth
for Mission Control's job status, retry history and performance analytics.
Reuses project / seo_run FKs; it records execution metadata only, not SEO data.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    retrying = "retrying"
    cancelled = "cancelled"


class JobTriggerType(str, enum.Enum):
    manual = "manual"
    automatic = "automatic"


class SchedulerJobRun(Base):
    __tablename__ = "scheduler_job_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # null for system-wide jobs
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    seo_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_runs.id"), nullable=True, index=True)

    job_name = Column(String(128), nullable=False, index=True)
    job_type = Column(String(64), nullable=False, index=True)
    trigger_type = Column(SQLEnum(JobTriggerType), default=JobTriggerType.automatic, nullable=False, index=True)
    worker_name = Column(String(128), nullable=True, index=True)

    status = Column(SQLEnum(JobStatus), default=JobStatus.running, nullable=False, index=True)
    retry_count = Column(Integer, default=0, nullable=False)

    started_at = Column(DateTime, nullable=True, index=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    cpu_time = Column(Float, nullable=True)
    memory_usage = Column(Float, nullable=True)  # MB, best-effort

    next_run = Column(DateTime, nullable=True)
    previous_run = Column(DateTime, nullable=True)

    error_message = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_scheduler_job_runs_name_status", "job_name", "status"),
        Index("ix_scheduler_job_runs_project_status", "project_id", "status"),
    )

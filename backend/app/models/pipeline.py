"""Per-stage pipeline telemetry.

One PipelineStageRun row per stage of a SEO run (crawl, audit, semantic,
content, planner), so Mission Control can visualise the pipeline stage-by-stage
and compute per-stage analytics. Complements the coarser SchedulerJobRun
(one row per whole job). Reuses project / seo_run FKs.
"""
from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.models.telemetry import JobStatus  # reuse the same status vocabulary


class PipelineStageRun(Base):
    __tablename__ = "pipeline_stage_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    seo_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_runs.id"), nullable=True, index=True)

    stage_name = Column(String(64), nullable=False, index=True)
    worker_name = Column(String(128), nullable=True)
    status = Column(SQLEnum(JobStatus), default=JobStatus.running, nullable=False, index=True)
    retry_count = Column(Integer, default=0, nullable=False)

    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    cpu_time = Column(Float, nullable=True)
    memory_usage = Column(Float, nullable=True)

    error_message = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("seo_run_id", "stage_name", name="uq_pipeline_stage_run"),
        Index("ix_pipeline_stage_runs_run_stage", "seo_run_id", "stage_name"),
        Index("ix_pipeline_stage_runs_stage_status", "stage_name", "status"),
    )

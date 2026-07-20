"""Patch pipeline models.

A PatchPipeline tracks a generated SEO patch set as it flows through the full
engineering lifecycle: generate -> apply -> branch -> commit -> pull request ->
deploy -> verify -> learn. Each stage records status + timestamps so Mission
Control can render a live Patch Pipeline panel. It reuses the existing Repo
Agent / Deployment / Verification / Learning engines — this model only records
the journey.

Only SEO-safe files are ever applied; the pipeline hard-stops before touching any
protected UI / business-logic / auth / payments / CRM / database file.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    Boolean,
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


class PatchPipelineStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    rolled_back = "rolled_back"      # validation failed -> reverted, no PR
    blocked = "blocked"             # cannot proceed (e.g. no repo connected)


# Canonical ordered stages of the lifecycle.
PIPELINE_STAGES = [
    "generate", "apply", "branch", "commit", "pull_request",
    "deploy", "verify", "learn",
]


class PatchPipeline(Base):
    __tablename__ = "patch_pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    framework = Column(String(64), nullable=True)
    status = Column(SQLEnum(PatchPipelineStatus), default=PatchPipelineStatus.pending, nullable=False, index=True)
    current_stage = Column(String(32), nullable=True)

    # [{name, status, started_at, finished_at, detail}, ...]
    stages = Column(JSONB, nullable=False, default=list)

    branch_name = Column(String(255), nullable=True)
    commit_sha = Column(String(64), nullable=True)
    diff_summary = Column(Text, nullable=True)

    pr_url = Column(String(1024), nullable=True)
    pr_status = Column(String(64), nullable=True)
    deployment_id = Column(UUID(as_uuid=True), nullable=True)
    verification_id = Column(UUID(as_uuid=True), nullable=True)

    validation_status = Column(String(32), nullable=True)   # passed/failed/gated/not_run
    validation_output = Column(Text, nullable=True)

    patches_total = Column(Integer, default=0)
    patches_applied = Column(Integer, default=0)
    patches_failed = Column(Integer, default=0)

    seo_before = Column(Integer, nullable=True)
    seo_after = Column(Integer, nullable=True)
    performance_before = Column(Integer, nullable=True)
    performance_after = Column(Integer, nullable=True)

    ready_for_pr = Column(Boolean, default=False)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PatchPipeline {self.project_id} {self.status} @ {self.current_stage}>"

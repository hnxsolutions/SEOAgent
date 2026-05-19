"""Weekly autonomous SEO planner models."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SeoPlannerRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class SeoPlannerRunType(str, enum.Enum):
    manual = "manual"
    scheduled = "scheduled"


class SeoTaskType(str, enum.Enum):
    technical_seo_fix = "technical_seo_fix"
    metadata_rewrite = "metadata_rewrite"
    schema_addition = "schema_addition"
    content_refresh = "content_refresh"
    internal_link = "internal_link"
    blog_topic = "blog_topic"
    blog_draft = "blog_draft"
    geo_aeo_improvement = "geo_aeo_improvement"
    search_console_opportunity = "search_console_opportunity"
    repo_patch_review = "repo_patch_review"
    sitemap_robots_fix = "sitemap_robots_fix"
    local_seo_task = "local_seo_task"
    citation_task = "citation_task"
    backlink_opportunity = "backlink_opportunity"
    manual_review = "manual_review"


class SeoTaskSourceType(str, enum.Enum):
    audit_issue = "audit_issue"
    content_optimization = "content_optimization"
    geo_aeo = "geo_aeo"
    search_console = "search_console"
    internal_linking = "internal_linking"
    blog_engine = "blog_engine"
    repo_agent = "repo_agent"
    planner = "planner"


class SeoTaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class SeoTaskImpact(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SeoTaskEffort(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SeoTaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"
    skipped = "skipped"


class SeoTaskDependencyType(str, enum.Enum):
    blocks = "blocks"
    related = "related"
    follow_up = "follow_up"


class SeoPlannerRun(Base):
    """A weekly planner orchestration run for one project."""

    __tablename__ = "seo_planner_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    status = Column(SQLEnum(SeoPlannerRunStatus), default=SeoPlannerRunStatus.queued, nullable=False, index=True)
    run_type = Column(SQLEnum(SeoPlannerRunType), default=SeoPlannerRunType.manual, nullable=False, index=True)
    target_week_start = Column(DateTime, nullable=False, index=True)
    target_week_end = Column(DateTime, nullable=False, index=True)

    crawl_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=True, index=True)
    audit_id = Column(UUID(as_uuid=True), ForeignKey("seo_audit_runs.id"), nullable=True, index=True)
    semantic_run_id = Column(UUID(as_uuid=True), ForeignKey("semantic_index_runs.id"), nullable=True, index=True)
    internal_link_run_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    content_optimization_run_id = Column(UUID(as_uuid=True), ForeignKey("content_optimization_runs.id"), nullable=True, index=True)
    geo_aeo_run_id = Column(UUID(as_uuid=True), ForeignKey("geo_aeo_runs.id"), nullable=True, index=True)
    gsc_sync_job_id = Column(UUID(as_uuid=True), ForeignKey("gsc_sync_jobs.id"), nullable=True, index=True)
    blog_plan_id = Column(UUID(as_uuid=True), ForeignKey("blog_plans.id"), nullable=True, index=True)
    repo_scan_run_id = Column(UUID(as_uuid=True), ForeignKey("repo_scan_runs.id"), nullable=True, index=True)

    tasks_created = Column(Integer, default=0)
    high_priority_tasks = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = relationship("SeoTask", back_populates="planner_run", cascade="all, delete-orphan")
    report = relationship("SeoWeeklyReport", back_populates="planner_run", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_seo_planner_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_planner_runs_status_created", "status", "created_at"),
    )


class SeoTask(Base):
    """A dashboard-ready SEO task generated from deterministic planner signals."""

    __tablename__ = "seo_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    planner_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_planner_runs.id"), nullable=False, index=True)

    task_type = Column(SQLEnum(SeoTaskType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    source_type = Column(SQLEnum(SeoTaskSourceType), nullable=False, index=True)
    source_reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    target_page_url = Column(String(2048), nullable=True, index=True)
    target_keyword = Column(String(255), nullable=True, index=True)
    priority = Column(SQLEnum(SeoTaskPriority), default=SeoTaskPriority.medium, nullable=False, index=True)
    priority_score = Column(Float, default=50, nullable=False, index=True)
    estimated_impact = Column(SQLEnum(SeoTaskImpact), default=SeoTaskImpact.medium, nullable=False, index=True)
    effort = Column(SQLEnum(SeoTaskEffort), default=SeoTaskEffort.medium, nullable=False, index=True)
    status = Column(SQLEnum(SeoTaskStatus), default=SeoTaskStatus.todo, nullable=False, index=True)
    due_date = Column(DateTime, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    planner_run = relationship("SeoPlannerRun", back_populates="tasks")
    dependencies = relationship(
        "SeoTaskDependency",
        back_populates="task",
        foreign_keys="SeoTaskDependency.task_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_seo_tasks_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_tasks_project_status_priority", "project_id", "status", "priority_score"),
        Index(
            "ix_seo_tasks_dedupe_lookup",
            "tenant_id",
            "project_id",
            "task_type",
            "target_page_url",
            "target_keyword",
            "source_type",
            "source_reference_id",
            "status",
        ),
    )


class SeoTaskDependency(Base):
    """A dependency relationship between planner tasks."""

    __tablename__ = "seo_task_dependencies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("seo_tasks.id"), nullable=False, index=True)
    depends_on_task_id = Column(UUID(as_uuid=True), ForeignKey("seo_tasks.id"), nullable=False, index=True)
    dependency_type = Column(SQLEnum(SeoTaskDependencyType), nullable=False, index=True)

    task = relationship("SeoTask", back_populates="dependencies", foreign_keys=[task_id])
    depends_on_task = relationship("SeoTask", foreign_keys=[depends_on_task_id])

    __table_args__ = (
        Index("ix_seo_task_deps_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_task_deps_unique", "task_id", "depends_on_task_id", "dependency_type", unique=True),
    )


class SeoWeeklyReport(Base):
    """A deterministic weekly SEO operating report for a planner run."""

    __tablename__ = "seo_weekly_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    planner_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_planner_runs.id"), nullable=False, index=True)

    summary = Column(Text, nullable=False)
    wins = Column(JSONB, nullable=True)
    risks = Column(JSONB, nullable=True)
    technical_seo_summary = Column(JSONB, nullable=True)
    search_console_summary = Column(JSONB, nullable=True)
    content_summary = Column(JSONB, nullable=True)
    geo_aeo_summary = Column(JSONB, nullable=True)
    blog_summary = Column(JSONB, nullable=True)
    repo_patch_summary = Column(JSONB, nullable=True)
    next_week_priorities = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    planner_run = relationship("SeoPlannerRun", back_populates="report")

    __table_args__ = (
        Index("ix_seo_weekly_reports_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_weekly_reports_run", "planner_run_id", unique=True),
    )

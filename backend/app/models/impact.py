"""SEO impact experiment tracking models."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class SeoImpactExperimentType(str, enum.Enum):
    metadata_update = "metadata_update"
    content_refresh = "content_refresh"
    internal_link_update = "internal_link_update"
    schema_update = "schema_update"
    blog_published = "blog_published"
    repo_patch_applied = "repo_patch_applied"
    geo_aeo_improvement = "geo_aeo_improvement"
    manual_seo_action = "manual_seo_action"


class SeoImpactSourceType(str, enum.Enum):
    planner_task = "planner_task"
    search_console_opportunity = "search_console_opportunity"
    content_optimization_suggestion = "content_optimization_suggestion"
    internal_link_recommendation = "internal_link_recommendation"
    geo_aeo_recommendation = "geo_aeo_recommendation"
    blog_draft = "blog_draft"
    repo_patch = "repo_patch"
    manual = "manual"


class SeoImpactExperimentStatus(str, enum.Enum):
    baseline_pending = "baseline_pending"
    baseline_captured = "baseline_captured"
    action_pending = "action_pending"
    monitoring = "monitoring"
    ready_for_review = "ready_for_review"
    completed = "completed"
    inconclusive = "inconclusive"
    failed = "failed"


class SeoImpactSnapshotType(str, enum.Enum):
    baseline = "baseline"
    followup = "followup"


class SeoImpactDataSource(str, enum.Enum):
    gsc_api = "gsc_api"
    csv_import = "csv_import"
    manual = "manual"


class SeoImpactOutcome(str, enum.Enum):
    improved = "improved"
    declined = "declined"
    neutral = "neutral"
    inconclusive = "inconclusive"


class SeoImpactExperiment(Base):
    """A measured SEO action with baseline/follow-up windows."""

    __tablename__ = "seo_impact_experiments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    experiment_type = Column(SQLEnum(SeoImpactExperimentType), nullable=False, index=True)
    source_type = Column(SQLEnum(SeoImpactSourceType), nullable=False, index=True)
    source_reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    target_page_url = Column(String(2048), nullable=False, index=True)
    target_query = Column(String(1000), nullable=True, index=True)
    target_keywords = Column(JSONB, nullable=True)
    baseline_start_date = Column(DateTime, nullable=False, index=True)
    baseline_end_date = Column(DateTime, nullable=False, index=True)
    action_date = Column(DateTime, nullable=True, index=True)
    review_start_date = Column(DateTime, nullable=True, index=True)
    review_end_date = Column(DateTime, nullable=True, index=True)
    review_after_days = Column(Integer, default=14, nullable=False)
    status = Column(
        SQLEnum(SeoImpactExperimentStatus),
        default=SeoImpactExperimentStatus.baseline_pending,
        nullable=False,
        index=True,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_seo_impact_experiments_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_impact_experiments_status_review", "status", "review_end_date"),
    )


class SeoImpactSnapshot(Base):
    """Aggregated metrics for an experiment baseline or follow-up window."""

    __tablename__ = "seo_impact_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    experiment_id = Column(UUID(as_uuid=True), ForeignKey("seo_impact_experiments.id"), nullable=False, index=True)
    snapshot_type = Column(SQLEnum(SeoImpactSnapshotType), nullable=False, index=True)
    date_start = Column(DateTime, nullable=False, index=True)
    date_end = Column(DateTime, nullable=False, index=True)
    query = Column(String(1000), nullable=True, index=True)
    page_url = Column(String(2048), nullable=False, index=True)
    clicks = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    ctr = Column(Float, default=0)
    position = Column(Float, default=0)
    data_source = Column(SQLEnum(SeoImpactDataSource), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_seo_impact_snapshots_exp_type", "experiment_id", "snapshot_type"),
        Index("ix_seo_impact_snapshots_tenant_project", "tenant_id", "project_id"),
    )


class SeoImpactResult(Base):
    """Evaluated delta and outcome for an impact experiment."""

    __tablename__ = "seo_impact_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    experiment_id = Column(UUID(as_uuid=True), ForeignKey("seo_impact_experiments.id"), nullable=False, index=True)
    clicks_delta = Column(Integer, default=0)
    impressions_delta = Column(Integer, default=0)
    ctr_delta = Column(Float, default=0)
    position_delta = Column(Float, default=0)
    percentage_clicks_change = Column(Float, nullable=True)
    percentage_impressions_change = Column(Float, nullable=True)
    outcome = Column(SQLEnum(SeoImpactOutcome), nullable=False, index=True)
    confidence_score = Column(Float, default=0)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_seo_impact_results_exp_created", "experiment_id", "created_at"),
        Index("ix_seo_impact_results_tenant_project", "tenant_id", "project_id"),
    )

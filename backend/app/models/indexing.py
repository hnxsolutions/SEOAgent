"""Google Search Console URL Inspection and indexing intelligence models."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class GSCUrlInspectionRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    partial = "partial"


class GSCIndexingIssueType(str, enum.Enum):
    not_indexed = "not_indexed"
    crawled_not_indexed = "crawled_not_indexed"
    discovered_not_indexed = "discovered_not_indexed"
    duplicate_canonical = "duplicate_canonical"
    canonical_mismatch = "canonical_mismatch"
    page_with_redirect = "page_with_redirect"
    blocked_by_robots = "blocked_by_robots"
    noindex_detected = "noindex_detected"
    soft_404 = "soft_404"
    server_error = "server_error"
    redirect_error = "redirect_error"
    sitemap_missing = "sitemap_missing"
    thin_content = "thin_content"
    orphan_page = "orphan_page"
    structured_data_issue = "structured_data_issue"
    unknown = "unknown"


class GSCIndexingIssueSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class GSCIndexingIssueStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    fix_proposed = "fix_proposed"
    fixed = "fixed"
    validated = "validated"
    still_failing = "still_failing"
    inconclusive = "inconclusive"
    ignored = "ignored"


class GSCFixValidationRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class GSCUrlInspectionRun(Base):
    """A quota-aware URL Inspection API run for one project/property."""

    __tablename__ = "gsc_url_inspection_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    gsc_property_id = Column(UUID(as_uuid=True), ForeignKey("gsc_properties.id"), nullable=False, index=True)
    status = Column(
        SQLEnum(GSCUrlInspectionRunStatus),
        default=GSCUrlInspectionRunStatus.queued,
        nullable=False,
        index=True,
    )
    requested_url_count = Column(Integer, default=0)
    inspected_url_count = Column(Integer, default=0)
    failed_url_count = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    results = relationship("GSCUrlInspectionResult", back_populates="inspection_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_gsc_url_inspection_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_url_inspection_runs_status_created", "status", "created_at"),
    )


class GSCUrlInspectionResult(Base):
    """Normalized fields from the official URL Inspection API response."""

    __tablename__ = "gsc_url_inspection_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    inspection_run_id = Column(UUID(as_uuid=True), ForeignKey("gsc_url_inspection_runs.id"), nullable=False, index=True)
    page_url = Column(String(2048), nullable=False, index=True)
    inspection_result_link = Column(String(2048), nullable=True)
    verdict = Column(String(64), nullable=True, index=True)
    coverage_state = Column(String(255), nullable=True, index=True)
    indexing_state = Column(String(128), nullable=True, index=True)
    robots_txt_state = Column(String(128), nullable=True)
    page_fetch_state = Column(String(128), nullable=True)
    google_canonical = Column(String(2048), nullable=True)
    user_canonical = Column(String(2048), nullable=True)
    sitemap_urls = Column(JSONB, nullable=True)
    referring_urls = Column(JSONB, nullable=True)
    last_crawl_time = Column(DateTime, nullable=True)
    crawled_as = Column(String(128), nullable=True)
    mobile_usability_verdict = Column(String(64), nullable=True)
    rich_results_verdict = Column(String(64), nullable=True)
    raw_result = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    inspection_run = relationship("GSCUrlInspectionRun", back_populates="results")
    issues = relationship("GSCIndexingIssue", back_populates="inspection_result")

    __table_args__ = (
        Index("ix_gsc_url_inspection_results_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_url_inspection_results_page_created", "page_url", "created_at"),
    )


class GSCIndexingIssue(Base):
    """A diagnosed indexing issue generated from inspection plus local SEO signals."""

    __tablename__ = "gsc_indexing_issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    inspection_result_id = Column(UUID(as_uuid=True), ForeignKey("gsc_url_inspection_results.id"), nullable=False, index=True)
    page_url = Column(String(2048), nullable=False, index=True)
    issue_type = Column(SQLEnum(GSCIndexingIssueType), nullable=False, index=True)
    severity = Column(SQLEnum(GSCIndexingIssueSeverity), nullable=False, index=True)
    likely_cause = Column(Text, nullable=False)
    recommended_fix = Column(Text, nullable=False)
    linked_repo_issue_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_issues.id"), nullable=True, index=True)
    linked_patch_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_patches.id"), nullable=True, index=True)
    status = Column(
        SQLEnum(GSCIndexingIssueStatus),
        default=GSCIndexingIssueStatus.open,
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    inspection_result = relationship("GSCUrlInspectionResult", back_populates="issues")

    __table_args__ = (
        Index("ix_gsc_indexing_issues_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_indexing_issues_status_type", "status", "issue_type"),
        Index("ix_gsc_indexing_issues_page_status", "page_url", "status"),
    )


class GSCFixValidationRun(Base):
    """A post-deploy validation run for one issue, patch, or PR."""

    __tablename__ = "gsc_fix_validation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    issue_id = Column(UUID(as_uuid=True), ForeignKey("gsc_indexing_issues.id"), nullable=True, index=True)
    patch_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_patches.id"), nullable=True, index=True)
    pull_request_id = Column(UUID(as_uuid=True), ForeignKey("pull_request_records.id"), nullable=True, index=True)
    status = Column(
        SQLEnum(GSCFixValidationRunStatus),
        default=GSCFixValidationRunStatus.queued,
        nullable=False,
        index=True,
    )
    validation_after_days = Column(Integer, default=7, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    results = relationship("GSCFixValidationResult", back_populates="validation_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_gsc_fix_validation_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_fix_validation_runs_status_created", "status", "created_at"),
    )


class GSCFixValidationResult(Base):
    """Outcome of a re-inspection against a previous indexing issue."""

    __tablename__ = "gsc_fix_validation_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    validation_run_id = Column(UUID(as_uuid=True), ForeignKey("gsc_fix_validation_runs.id"), nullable=False, index=True)
    issue_id = Column(UUID(as_uuid=True), ForeignKey("gsc_indexing_issues.id"), nullable=False, index=True)
    page_url = Column(String(2048), nullable=False, index=True)
    previous_issue_type = Column(SQLEnum(GSCIndexingIssueType), nullable=False, index=True)
    current_verdict = Column(String(64), nullable=True, index=True)
    current_coverage_state = Column(String(255), nullable=True)
    fixed = Column(Boolean, default=False, nullable=False, index=True)
    still_failing = Column(Boolean, default=False, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    raw_result = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    validation_run = relationship("GSCFixValidationRun", back_populates="results")

    __table_args__ = (
        Index("ix_gsc_fix_validation_results_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_fix_validation_results_issue", "issue_id", "created_at"),
    )

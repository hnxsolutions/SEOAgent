"""
Deterministic SEO audit models.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SEOAuditStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SEOIssueSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class SEOIssueCategory(str, enum.Enum):
    technical = "technical"
    content = "content"
    metadata = "metadata"
    links = "links"
    schema = "schema"


class SEOIssueStatus(str, enum.Enum):
    open = "open"
    ignored = "ignored"
    fixed = "fixed"


class SEOAuditRun(Base):
    """A deterministic SEO audit run for a completed crawl."""

    __tablename__ = "seo_audit_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    status = Column(SQLEnum(SEOAuditStatus), default=SEOAuditStatus.pending, nullable=False, index=True)
    progress = Column(Integer, default=0)
    site_score = Column(Integer, nullable=True)
    total_pages = Column(Integer, default=0)
    total_issues = Column(Integer, default=0)
    issue_counts_by_severity = Column(JSON, nullable=True)
    issue_counts_by_category = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    issues = relationship("SEOIssue", back_populates="audit_run", cascade="all, delete-orphan")
    page_scores = relationship("SEOPageScore", back_populates="audit_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_seo_audit_runs_tenant_crawl", "tenant_id", "crawl_job_id"),
        Index("ix_seo_audit_runs_created", "created_at", postgresql_using="brin"),
    )


class SEOIssue(Base):
    """A deterministic issue raised by the SEO rules engine."""

    __tablename__ = "seo_issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_audit_runs.id"), nullable=False, index=True)
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    crawl_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=True, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    issue_type = Column(String(100), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=True)
    severity = Column(SQLEnum(SEOIssueSeverity), nullable=False, index=True)
    category = Column(SQLEnum(SEOIssueCategory), nullable=False, index=True)
    status = Column(SQLEnum(SEOIssueStatus), default=SEOIssueStatus.open, nullable=False, index=True)
    url = Column(String(2048), nullable=True)
    evidence = Column(JSONB, nullable=True)
    score_impact = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    audit_run = relationship("SEOAuditRun", back_populates="issues")

    __table_args__ = (
        Index("ix_seo_issues_tenant_status", "tenant_id", "status"),
        Index("ix_seo_issues_crawl_page", "crawl_job_id", "crawl_page_id"),
    )


class SEOPageScore(Base):
    """Persisted page-level SEO score for an audit run."""

    __tablename__ = "seo_page_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_run_id = Column(UUID(as_uuid=True), ForeignKey("seo_audit_runs.id"), nullable=False, index=True)
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    crawl_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    url = Column(String(2048), nullable=False)
    score = Column(Integer, nullable=False)
    issue_count = Column(Integer, default=0)
    critical_issues = Column(Integer, default=0)
    high_issues = Column(Integer, default=0)
    medium_issues = Column(Integer, default=0)
    low_issues = Column(Integer, default=0)
    score_breakdown = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    audit_run = relationship("SEOAuditRun", back_populates="page_scores")

    __table_args__ = (
        Index("ix_seo_page_scores_run_page", "audit_run_id", "crawl_page_id", unique=True),
        Index("ix_seo_page_scores_tenant_crawl", "tenant_id", "crawl_job_id"),
    )

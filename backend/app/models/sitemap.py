"""Sitemap intelligence models.

Tracks sitemaps known to Google Search Console (Sitemaps API), sitemaps
detected from the live site (robots.txt / common paths), and deterministic
sitemap issues raised from safe local parsing plus crawl cross-referencing.

Note: the GSC Sitemaps API can list/get/submit/delete sitemap *submissions*.
It cannot edit the website's sitemap file. Editing the actual sitemap.xml is
handled through the repo-agent / PR workflow, never by direct production edits.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SitemapSource(str, enum.Enum):
    gsc_api = "gsc_api"
    detected = "detected"
    generated = "generated"


class SitemapStatus(str, enum.Enum):
    active = "active"
    warning = "warning"
    error = "error"
    deleted = "deleted"


class SitemapIssueType(str, enum.Enum):
    not_submitted = "not_submitted"
    pending = "pending"
    fetch_error = "fetch_error"
    parse_error = "parse_error"
    empty_sitemap = "empty_sitemap"
    invalid_url = "invalid_url"
    url_outside_property = "url_outside_property"
    non_https_url = "non_https_url"
    duplicate_url = "duplicate_url"
    url_not_found = "url_not_found"          # 404 observed by our crawler
    url_server_error = "url_server_error"    # 5xx observed by our crawler
    url_redirects = "url_redirects"          # 3xx observed by our crawler
    url_noindex = "url_noindex"              # noindex observed by our crawler
    url_non_canonical = "url_non_canonical"  # canonical points elsewhere
    url_blocked_by_robots = "url_blocked_by_robots"
    gsc_errors = "gsc_errors"                # GSC reported errors on the sitemap
    gsc_warnings = "gsc_warnings"            # GSC reported warnings on the sitemap
    missing_in_gsc = "missing_in_gsc"        # detected on site but not submitted to GSC


class SitemapIssueSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class SitemapIssueStatus(str, enum.Enum):
    open = "open"
    approved = "approved"
    fixed = "fixed"
    ignored = "ignored"


class GSCSitemapRecord(Base):
    """A sitemap known to GSC (Sitemaps API) or detected on the live site."""

    __tablename__ = "gsc_sitemap_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("gsc_properties.id"), nullable=True, index=True)

    sitemap_url = Column(String(2048), nullable=False, index=True)
    is_submitted = Column(Boolean, default=False, nullable=False, index=True)
    is_pending = Column(Boolean, default=False, nullable=False)
    is_sitemaps_index = Column(Boolean, default=False, nullable=False)
    last_submitted_at = Column(DateTime, nullable=True)
    last_downloaded_at = Column(DateTime, nullable=True)
    errors_count = Column(Integer, default=0, nullable=False)
    warnings_count = Column(Integer, default=0, nullable=False)
    submitted_urls_count = Column(Integer, default=0, nullable=False)
    source = Column(SQLEnum(SitemapSource), default=SitemapSource.detected, nullable=False, index=True)
    status = Column(SQLEnum(SitemapStatus), default=SitemapStatus.active, nullable=False, index=True)
    raw_payload = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    issues = relationship("SitemapIssue", back_populates="sitemap", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_gsc_sitemaps_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_sitemaps_project_url", "project_id", "sitemap_url", unique=True),
        Index("ix_gsc_sitemaps_status", "status", "created_at"),
    )


class SitemapIssue(Base):
    """A deterministic sitemap issue for admin review and optional PR fix."""

    __tablename__ = "sitemap_issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    sitemap_id = Column(UUID(as_uuid=True), ForeignKey("gsc_sitemap_records.id"), nullable=False, index=True)

    issue_type = Column(SQLEnum(SitemapIssueType), nullable=False, index=True)
    severity = Column(SQLEnum(SitemapIssueSeverity), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    sample_urls = Column(JSONB, nullable=True)
    status = Column(SQLEnum(SitemapIssueStatus), default=SitemapIssueStatus.open, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sitemap = relationship("GSCSitemapRecord", back_populates="issues")

    __table_args__ = (
        Index("ix_sitemap_issues_tenant_project", "tenant_id", "project_id"),
        Index("ix_sitemap_issues_status_type", "status", "issue_type"),
        Index("ix_sitemap_issues_dedupe", "sitemap_id", "issue_type", "status"),
    )

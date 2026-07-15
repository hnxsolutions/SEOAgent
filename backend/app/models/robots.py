"""Robots.txt intelligence models.

Stores historical analyses of a project's live robots.txt and the deterministic
issues raised from safe local parsing. Editing the actual robots.txt file is
handled through the repo-agent / PR workflow (human approval), never by direct
production edits.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class RobotsAnalysisStatus(str, enum.Enum):
    completed = "completed"
    unreachable = "unreachable"  # robots.txt could not be fetched
    missing = "missing"          # site returned 404 / no robots.txt


class RobotsIssueType(str, enum.Enum):
    missing_robots = "missing_robots"                    # no robots.txt at all
    unreachable_robots = "unreachable_robots"            # fetch failed (timeout/DNS/5xx)
    missing_sitemap_directive = "missing_sitemap_directive"
    disallow_all = "disallow_all"                        # Disallow: / for * (blocks whole site)
    blocked_css = "blocked_css"
    blocked_js = "blocked_js"
    blocked_images = "blocked_images"
    broken_wildcard = "broken_wildcard"                  # malformed * / $ usage
    conflicting_directives = "conflicting_directives"    # Allow and Disallow collide
    duplicate_directive = "duplicate_directive"          # same rule repeated in a group
    crawl_trap = "crawl_trap"                            # patterns that invite infinite crawl
    invalid_directive = "invalid_directive"              # unknown/misspelled field
    sitemap_not_https = "sitemap_not_https"              # Sitemap: http:// URL


class RobotsIssueSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RobotsIssueStatus(str, enum.Enum):
    open = "open"
    approved = "approved"
    fixed = "fixed"
    ignored = "ignored"


class RobotsAnalysisRun(Base):
    """One fetch + analysis of a project's robots.txt, kept historically."""

    __tablename__ = "robots_analysis_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    robots_url = Column(String(2048), nullable=False)
    status = Column(SQLEnum(RobotsAnalysisStatus), nullable=False, index=True)
    http_status_code = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)
    byte_size = Column(Integer, default=0, nullable=False)
    raw_content = Column(Text, nullable=True)

    sitemap_directive_count = Column(Integer, default=0, nullable=False)
    user_agent_group_count = Column(Integer, default=0, nullable=False)
    issues_found = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    issues = relationship("RobotsIssue", back_populates="analysis_run", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_robots_runs_project_created", "project_id", "created_at"),
    )


class RobotsIssue(Base):
    """A single deterministic robots.txt issue tied to an analysis run."""

    __tablename__ = "robots_issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    analysis_run_id = Column(UUID(as_uuid=True), ForeignKey("robots_analysis_runs.id"), nullable=False, index=True)

    issue_type = Column(SQLEnum(RobotsIssueType), nullable=False, index=True)
    severity = Column(SQLEnum(RobotsIssueSeverity), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    evidence = Column(JSONB, nullable=True)  # offending line(s), rule, user-agent group
    status = Column(SQLEnum(RobotsIssueStatus), default=RobotsIssueStatus.open, nullable=False, index=True)

    analysis_run = relationship("RobotsAnalysisRun", back_populates="issues")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_robots_issues_project_status", "project_id", "status"),
    )

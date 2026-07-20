"""Technology Fingerprint models.

A TechnologyFingerprint is the FIRST thing produced for a project: the complete
technology stack of the website, detected from the live URL (headers + HTML +
markers, no credentials required) and — when a repo is connected — merged with
the repo architecture profile. It is persisted once and reused everywhere
(Mission Control, Daily Briefing, the framework-aware SEO generator, Learning).
It is never re-detected unless the user clicks "Re-analyze Technology" or the
repository changes.

This is an SEO engineer's understanding of the site; it never drives any UI or
business-logic change — only which SEO-safe patch strategy applies.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class FingerprintSource(str, enum.Enum):
    url = "url"        # detected from the live website only
    repo = "repo"      # detected from the connected repository only
    hybrid = "hybrid"  # url + repo merged


class FingerprintStatus(str, enum.Enum):
    detecting = "detecting"  # analysis in progress (live status for Mission Control)
    complete = "complete"
    failed = "failed"


class TechnologyFingerprint(Base):
    """One saved technology fingerprint per project (the active one)."""

    __tablename__ = "technology_fingerprints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )

    source = Column(SQLEnum(FingerprintSource), default=FingerprintSource.url, nullable=False)
    status = Column(SQLEnum(FingerprintStatus), default=FingerprintStatus.detecting, nullable=False, index=True)
    source_url = Column(String(2048), nullable=True)

    # Flat list of detected technologies:
    # [{category, name, version, confidence, evidence: [str, ...]}, ...]
    technologies = Column(JSONB, nullable=False, default=list)
    # Readiness/health scores 0-100:
    # {framework_health, seo_readiness, performance_readiness, accessibility,
    #  security, indexability}
    scores = Column(JSONB, nullable=False, default=dict)

    # Denormalized headline values for quick display + filtering.
    primary_framework = Column(String(255), nullable=True)
    primary_cms = Column(String(255), nullable=True)
    primary_language = Column(String(255), nullable=True)
    rendering = Column(String(255), nullable=True)
    hosting = Column(String(255), nullable=True)
    cdn = Column(String(255), nullable=True)

    # Stable hash of the detection signals — lets the Learning Engine skip
    # relearning an identical stack.
    content_hash = Column(String(64), nullable=True, index=True)

    error = Column(Text, nullable=True)
    detected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", name="uq_technology_fingerprint_project"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TechnologyFingerprint {self.project_id} {self.primary_framework}>"

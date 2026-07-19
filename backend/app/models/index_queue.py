"""Auto Index Queue models.

A PendingIndexUrl is a URL the system discovered (from crawl / blog / planner /
sitemap) that the admin can approve for indexing. IMPORTANT: Google offers no
official API to request indexing of general web pages (the Indexing API is
restricted to JobPosting / BroadcastEvent). The only official mechanism here is
to ensure the URL is in the sitemap and (re)submit the sitemap via the Search
Console Sitemaps API. This model tracks that queue + its sitemap-submission
lifecycle. Reuses the project FK; no page data is duplicated (URLs only).
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class IndexUrlSource(str, enum.Enum):
    crawl = "crawl"
    blog = "blog"
    planner = "planner"
    sitemap = "sitemap"
    manual = "manual"


class IndexUrlStatus(str, enum.Enum):
    pending = "pending"          # discovered, awaiting admin decision
    approved = "approved"        # admin approved; awaiting sitemap submission
    rejected = "rejected"
    scheduled = "scheduled"      # approved, submit later
    submitted = "submitted"      # included in a (re)submitted sitemap
    indexed = "indexed"          # confirmed indexed via URL Inspection (GSC)


class PendingIndexUrl(Base):
    __tablename__ = "pending_index_urls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    url = Column(String(2048), nullable=False, index=True)
    source = Column(SQLEnum(IndexUrlSource), default=IndexUrlSource.crawl, nullable=False, index=True)
    status = Column(SQLEnum(IndexUrlStatus), default=IndexUrlStatus.pending, nullable=False, index=True)

    eligible = Column(Boolean, default=True, nullable=False, index=True)   # passed validation
    reason = Column(Text, nullable=True)                                  # validation / status notes
    submitted_via = Column(String(32), nullable=True)                     # e.g. "sitemap"

    discovered_at = Column(DateTime, default=datetime.utcnow, index=True)
    approved_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "url", name="uq_pending_index_project_url"),
        Index("ix_pending_index_project_status", "project_id", "status"),
    )

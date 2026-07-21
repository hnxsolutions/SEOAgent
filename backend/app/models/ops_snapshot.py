"""Autonomous SEO operations snapshot.

The SEO Operations Engine records a daily health snapshot per project so it can
detect what changed since yesterday (change detection) and chart a health
timeline. Snapshots are read-only observations composed from existing engines;
they never modify a site.
"""
from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class OpsHealthSnapshot(Base):
    __tablename__ = "ops_health_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    overall_score = Column(Integer, nullable=True)
    # {dimension_key: score} — Technical/Content/Performance/CWV/Security/...
    dimensions = Column(JSONB, nullable=False, default=dict)
    # Discrete signals used for change detection (has_sitemap, lcp_ms, indexability, ...)
    signals = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OpsHealthSnapshot {self.project_id} score={self.overall_score}>"

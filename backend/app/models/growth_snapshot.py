"""AI SEO Growth snapshot.

Stores the latest growth analysis for a project (growth score + opportunities +
content plan) so Mission Control, the Daily Briefing, and the Learning Engine can
read it and track what worked over time. Read-only strategy output — it never
modifies a site.
"""
from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class GrowthSnapshot(Base):
    __tablename__ = "growth_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    growth_score = Column(Integer, nullable=True)
    dimensions = Column(JSONB, nullable=False, default=dict)          # keyword/topic/authority/opportunity coverage

    keyword_opportunities = Column(JSONB, nullable=False, default=list)
    content_gaps = Column(JSONB, nullable=False, default=list)
    topic_clusters = Column(JSONB, nullable=False, default=list)
    blog_roadmap = Column(JSONB, nullable=False, default=list)
    traffic_forecast = Column(JSONB, nullable=True)
    eeat = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GrowthSnapshot {self.project_id} score={self.growth_score}>"

"""Daily executive briefing + notification models.

A DailyBriefing is a stored snapshot of a project's composed state (health,
sections, timeline, AI summary) for one day, so history and 7/30/90-day trends
can be shown without recomputation. Notifications are lightweight dashboard
messages (email/Slack/webhook delivery is future / credential-gated). Both reuse
project FKs; no existing data is duplicated — sections embed already-computed
service output.
"""
from datetime import date, datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class NotificationLevel(str, enum.Enum):
    info = "info"
    success = "success"
    warning = "warning"
    critical = "critical"


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    briefing_date = Column(Date, nullable=False, default=date.today, index=True)

    health_score = Column(Float, nullable=True)
    ai_confidence = Column(Float, nullable=True)
    seo_score = Column(Float, nullable=True)
    seo_score_prev = Column(Float, nullable=True)

    executive_summary = Column(Text, nullable=False)
    summary_source = Column(String(16), nullable=False, default="template")  # llm | template
    sections = Column(JSONB, nullable=False)  # composed section snapshot
    timeline = Column(JSONB, nullable=True)   # list of {time, event, category}

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "briefing_date", name="uq_daily_briefing_project_date"),
        Index("ix_daily_briefings_project_date", "project_id", "briefing_date"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)

    level = Column(SQLEnum(NotificationLevel), default=NotificationLevel.info, nullable=False, index=True)
    category = Column(String(64), nullable=False, default="general", index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    read = Column(Boolean, default=False, nullable=False, index=True)
    dedupe_key = Column(String(255), nullable=True, index=True)  # avoid duplicate daily alerts

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_notifications_project_read", "project_id", "read"),
    )

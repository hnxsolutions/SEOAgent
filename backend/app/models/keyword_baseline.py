"""Manual keyword baseline records.

These records are user-entered rank context only. They do not scrape search
engines or call external SERP providers.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class KeywordBaselineDevice(str, enum.Enum):
    desktop = "desktop"
    mobile = "mobile"


class KeywordBaselineSource(str, enum.Enum):
    manual = "manual"
    csv = "csv"
    imported = "imported"


class KeywordBaseline(Base):
    """Manually captured keyword baseline for a project."""

    __tablename__ = "keyword_baselines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    keyword = Column(String(1000), nullable=False, index=True)
    target_location = Column(String(255), nullable=True, index=True)
    search_engine = Column(String(50), default="google", nullable=False, index=True)
    device = Column(
        SQLEnum(KeywordBaselineDevice, name="keywordbaselinedevice"),
        default=KeywordBaselineDevice.desktop,
        nullable=False,
        index=True,
    )
    current_position = Column(Integer, nullable=True, index=True)
    current_url = Column(String(2048), nullable=True)
    search_volume = Column(Integer, nullable=True)
    difficulty = Column(Integer, nullable=True)
    intent = Column(String(255), nullable=True, index=True)
    notes = Column(Text, nullable=True)
    source = Column(
        SQLEnum(KeywordBaselineSource, name="keywordbaselinesource"),
        default=KeywordBaselineSource.manual,
        nullable=False,
        index=True,
    )
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index(
            "ix_keyword_baselines_project_keyword_device_location",
            "project_id",
            "keyword",
            "device",
            "target_location",
        ),
        Index("ix_keyword_baselines_tenant_project", "tenant_id", "project_id"),
    )

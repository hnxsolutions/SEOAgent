"""Core Web Vitals / PageSpeed Insights models.

Stores one PagespeedRun per (project, url, device) analysis from the official
Google PageSpeed Insights API. Reuses the project FK; performance data only.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class PagespeedStrategy(str, enum.Enum):
    mobile = "mobile"
    desktop = "desktop"


class PagespeedStatus(str, enum.Enum):
    completed = "completed"
    quota_exceeded = "quota_exceeded"   # HTTP 429 — needs an API key / quota
    error = "error"                     # network / parse / API error


class PagespeedRun(Base):
    __tablename__ = "pagespeed_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    url = Column(String(2048), nullable=False)
    strategy = Column(SQLEnum(PagespeedStrategy), nullable=False, index=True)
    status = Column(SQLEnum(PagespeedStatus), nullable=False, index=True)

    # Category scores (0-100). Null when unavailable.
    performance_score = Column(Float, nullable=True)
    accessibility_score = Column(Float, nullable=True)
    best_practices_score = Column(Float, nullable=True)
    seo_score = Column(Float, nullable=True)

    # Core Web Vitals (lab). Times in milliseconds; CLS unitless.
    lcp_ms = Column(Float, nullable=True)
    cls = Column(Float, nullable=True)
    inp_ms = Column(Float, nullable=True)
    tbt_ms = Column(Float, nullable=True)
    fcp_ms = Column(Float, nullable=True)
    speed_index_ms = Column(Float, nullable=True)
    ttfb_ms = Column(Float, nullable=True)

    # Field data (CrUX) when available.
    field_lcp_ms = Column(Float, nullable=True)
    field_cls = Column(Float, nullable=True)
    field_inp_ms = Column(Float, nullable=True)

    opportunities = Column(JSONB, nullable=True)   # [{id,title,description,savings_ms,score}]
    diagnostics = Column(JSONB, nullable=True)     # [{id,title,displayValue}]
    error_message = Column(String(1024), nullable=True)
    raw_json = Column(JSONB, nullable=True)        # trimmed raw Lighthouse result

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_pagespeed_runs_project_strategy", "project_id", "strategy"),
        Index("ix_pagespeed_runs_project_created", "project_id", "created_at"),
    )

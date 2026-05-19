"""Google Search Console import, sync, and opportunity models."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SearchConsoleSourceType(str, enum.Enum):
    csv_upload = "csv_upload"
    gsc_api = "gsc_api"


class SearchConsoleImportStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class GSCComparisonWindow(str, enum.Enum):
    last_7_days = "last_7_days"
    last_28_days = "last_28_days"
    current_month = "current_month"


class SearchConsolePeriod(str, enum.Enum):
    current = "current"
    previous = "previous"


class SearchConsoleOpportunityStatus(str, enum.Enum):
    suggested = "suggested"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"


class SearchConsoleOpportunityType(str, enum.Enum):
    high_impressions_low_ctr = "high_impressions_low_ctr"
    striking_distance_keyword = "striking_distance_keyword"
    ranking_drop = "ranking_drop"
    ctr_drop = "ctr_drop"
    click_decline = "click_decline"
    rising_impressions_clicks_flat = "rising_impressions_clicks_flat"
    metadata_rewrite = "metadata_rewrite"
    content_refresh = "content_refresh"
    blog_support = "blog_support"
    internal_link_support = "internal_link_support"
    landing_page_expansion = "landing_page_expansion"


class GSCConnectionStatus(str, enum.Enum):
    connected = "connected"
    expired = "expired"
    revoked = "revoked"
    failed = "failed"


class GSCSyncType(str, enum.Enum):
    manual = "manual"
    scheduled = "scheduled"


class GSCSyncJobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class SearchConsoleImport(Base):
    """A normalized Search Console import from CSV or GSC API."""

    __tablename__ = "search_console_imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("gsc_properties.id"), nullable=True, index=True)

    source_type = Column(SQLEnum(SearchConsoleSourceType), nullable=False, index=True)
    status = Column(
        SQLEnum(SearchConsoleImportStatus),
        default=SearchConsoleImportStatus.pending,
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=True)
    date_start = Column(DateTime, nullable=True)
    date_end = Column(DateTime, nullable=True)
    comparison_window = Column(SQLEnum(GSCComparisonWindow), nullable=True, index=True)
    rows_imported = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    rows = relationship("SearchConsoleRow", back_populates="import_record", cascade="all, delete-orphan")
    opportunities = relationship("SearchConsoleOpportunity", back_populates="import_record")

    __table_args__ = (
        Index("ix_sc_imports_tenant_project", "tenant_id", "project_id"),
        Index("ix_sc_imports_created", "created_at", postgresql_using="brin"),
    )


class SearchConsoleRow(Base):
    """Normalized Search Console row by query and page URL."""

    __tablename__ = "search_console_rows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("search_console_imports.id"), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("gsc_properties.id"), nullable=True, index=True)
    crawl_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=True, index=True)

    query = Column(String(1000), nullable=False, index=True)
    page_url = Column(String(2048), nullable=False, index=True)
    clicks = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    ctr = Column(Float, default=0)
    position = Column(Float, default=0)
    date_start = Column(DateTime, nullable=False, index=True)
    date_end = Column(DateTime, nullable=False, index=True)
    comparison_window = Column(SQLEnum(GSCComparisonWindow), nullable=True, index=True)
    period = Column(SQLEnum(SearchConsolePeriod), default=SearchConsolePeriod.current, nullable=False, index=True)
    source_type = Column(SQLEnum(SearchConsoleSourceType), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    import_record = relationship("SearchConsoleImport", back_populates="rows")

    __table_args__ = (
        Index("ix_sc_rows_import_period", "import_id", "period"),
        Index("ix_sc_rows_tenant_project", "tenant_id", "project_id"),
        Index("ix_sc_rows_dedupe", "import_id", "query", "page_url", "period", "content_hash", unique=True),
    )


class SearchConsoleOpportunity(Base):
    """A deterministic Search Console opportunity for human review."""

    __tablename__ = "search_console_opportunities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("search_console_imports.id"), nullable=True, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("gsc_properties.id"), nullable=True, index=True)
    crawl_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=True, index=True)

    query = Column(String(1000), nullable=False, index=True)
    page_url = Column(String(2048), nullable=False, index=True)
    opportunity_type = Column(SQLEnum(SearchConsoleOpportunityType), nullable=False, index=True)
    status = Column(
        SQLEnum(SearchConsoleOpportunityStatus),
        default=SearchConsoleOpportunityStatus.suggested,
        nullable=False,
        index=True,
    )

    current_clicks = Column(Integer, default=0)
    current_impressions = Column(Integer, default=0)
    current_ctr = Column(Float, default=0)
    current_position = Column(Float, default=0)
    previous_clicks = Column(Integer, nullable=True)
    previous_impressions = Column(Integer, nullable=True)
    previous_ctr = Column(Float, nullable=True)
    previous_position = Column(Float, nullable=True)

    reason = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    priority_score = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    evidence = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    import_record = relationship("SearchConsoleImport", back_populates="opportunities")

    __table_args__ = (
        Index("ix_sc_opps_tenant_project", "tenant_id", "project_id"),
        Index("ix_sc_opps_status_priority", "status", "priority_score"),
        Index(
            "ix_sc_opps_dedupe_open",
            "tenant_id",
            "project_id",
            "query",
            "page_url",
            "opportunity_type",
            "status",
        ),
    )


class GSCConnection(Base):
    """Google Search Console OAuth connection with encrypted refresh token."""

    __tablename__ = "gsc_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(50), default="google", nullable=False, index=True)
    encrypted_refresh_token = Column(Text, nullable=False)
    access_token_expires_at = Column(DateTime, nullable=True)
    scopes = Column(JSONB, nullable=True)
    status = Column(SQLEnum(GSCConnectionStatus), default=GSCConnectionStatus.connected, nullable=False, index=True)
    metadata_json = Column("metadata", JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    properties = relationship("GSCProperty", back_populates="connection")

    __table_args__ = (
        Index("ix_gsc_connections_tenant_user", "tenant_id", "user_id"),
        Index("ix_gsc_connections_created", "created_at", postgresql_using="brin"),
    )


class GSCProperty(Base):
    """A verified Search Console property available to a connection."""

    __tablename__ = "gsc_properties"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("gsc_connections.id"), nullable=False, index=True)
    site_url = Column(String(2048), nullable=False, index=True)
    permission_level = Column(String(100), nullable=True)
    is_selected = Column(Boolean, default=False, nullable=False, index=True)
    last_synced_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    connection = relationship("GSCConnection", back_populates="properties")

    __table_args__ = (
        Index("ix_gsc_properties_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_properties_site", "tenant_id", "connection_id", "site_url", unique=True),
    )


class GSCSyncJob(Base):
    """A manual or scheduled GSC API sync job."""

    __tablename__ = "gsc_sync_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("gsc_connections.id"), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("gsc_properties.id"), nullable=False, index=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("search_console_imports.id"), nullable=True, index=True)

    sync_type = Column(SQLEnum(GSCSyncType), nullable=False, index=True)
    date_start = Column(DateTime, nullable=False)
    date_end = Column(DateTime, nullable=False)
    comparison_window = Column(SQLEnum(GSCComparisonWindow), nullable=False, index=True)
    status = Column(SQLEnum(GSCSyncJobStatus), default=GSCSyncJobStatus.queued, nullable=False, index=True)
    rows_fetched = Column(Integer, default=0)
    opportunities_created = Column(Integer, default=0)
    opportunities_updated = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_gsc_sync_jobs_tenant_project", "tenant_id", "project_id"),
        Index("ix_gsc_sync_jobs_status", "status", "created_at"),
    )

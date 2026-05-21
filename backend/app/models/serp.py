"""
SEO Agent SaaS - SERP Analysis Models
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum as SQLEnum, JSON
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class SERPStatus(str, enum.Enum):
    """SERP analysis status enum"""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SERPAnalysis(Base):
    """SERP analysis model"""
    
    __tablename__ = "serp_analyses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keywords = Column(ARRAY(String), nullable=False)
    status = Column(SQLEnum(SERPStatus), default=SERPStatus.pending)
    progress = Column(Integer, default=0)
    total_keywords = Column(Integer, nullable=False)
    analyzed_keywords = Column(Integer, default=0)
    location = Column(String, default="us")
    language = Column(String, default="en")
    search_engine = Column(String, default="google")
    error_message = Column(Text, nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="serp_analyses")
    results = relationship("SERPResult", back_populates="analysis", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<SERPAnalysis {self.keywords} - {self.status}>"


class SERPResult(Base):
    """SERP result model"""
    
    __tablename__ = "serp_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("serp_analyses.id"), nullable=False)
    keyword = Column(String, nullable=False)
    position = Column(Integer, nullable=True)
    url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    domain_authority = Column(Integer, nullable=True)
    page_authority = Column(Integer, nullable=True)
    backlinks = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    analysis = relationship("SERPAnalysis", back_populates="results")
    
    def __repr__(self):
        return f"<SERPResult {self.keyword} - Position {self.position}>"


class SerpSnapshotSearchEngine(str, enum.Enum):
    google = "google"


class SerpSnapshotDevice(str, enum.Enum):
    desktop = "desktop"
    mobile = "mobile"


class SerpSnapshotCaptureMode(str, enum.Enum):
    manual = "manual"
    screenshot_upload = "screenshot_upload"
    browser_assisted_manual = "browser_assisted_manual"


class SerpSnapshotStatus(str, enum.Enum):
    captured = "captured"
    missing_target = "missing_target"
    failed = "failed"


class SerpSnapshotAssetType(str, enum.Enum):
    screenshot = "screenshot"
    html_note = "html_note"


class SerpSnapshot(Base):
    """Manual-assisted SERP snapshot evidence. No automated Google scraping."""

    __tablename__ = "serp_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    keyword = Column(String(1000), nullable=False, index=True)
    target_url = Column(String(2048), nullable=True, index=True)
    target_domain = Column(String(255), nullable=False, index=True)
    search_engine = Column(SQLEnum(SerpSnapshotSearchEngine), default=SerpSnapshotSearchEngine.google, nullable=False, index=True)
    country = Column(String(100), nullable=False, index=True)
    city = Column(String(255), nullable=True, index=True)
    device = Column(SQLEnum(SerpSnapshotDevice), default=SerpSnapshotDevice.desktop, nullable=False, index=True)
    language = Column(String(50), nullable=True)
    capture_mode = Column(SQLEnum(SerpSnapshotCaptureMode), default=SerpSnapshotCaptureMode.manual, nullable=False, index=True)
    observed_target_rank = Column(Integer, nullable=True, index=True)
    status = Column(SQLEnum(SerpSnapshotStatus), default=SerpSnapshotStatus.captured, nullable=False, index=True)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    notes = Column(Text, nullable=True)


class SerpSnapshotResult(Base):
    """Manually entered visible SERP result."""

    __tablename__ = "serp_snapshot_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey("serp_snapshots.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False, index=True)
    title = Column(String(1000), nullable=False)
    url = Column(String(2048), nullable=False, index=True)
    domain = Column(String(255), nullable=False, index=True)
    snippet = Column(Text, nullable=True)
    is_target_domain = Column(Boolean, default=False, nullable=False, index=True)
    is_target_url = Column(Boolean, default=False, nullable=False, index=True)


class SerpSnapshotAsset(Base):
    """Uploaded screenshot or note metadata for a manual SERP snapshot."""

    __tablename__ = "serp_snapshot_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey("serp_snapshots.id"), nullable=False, index=True)
    asset_type = Column(SQLEnum(SerpSnapshotAssetType), nullable=False, index=True)
    file_path = Column(String(2048), nullable=False)
    original_filename = Column(String(255), nullable=True)
    mime_type = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

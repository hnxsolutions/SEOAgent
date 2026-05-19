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

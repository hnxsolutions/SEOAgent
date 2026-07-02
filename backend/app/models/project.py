"""
SEO Agent SaaS - Project Model
"""
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.database import Base


class Project(Base):
    """Project model for SEO projects"""
    
    __tablename__ = "projects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    keywords = Column(ARRAY(String), nullable=True)
    business_name = Column(String(255), nullable=True)
    industry = Column(String(255), nullable=True)
    target_location = Column(String(255), nullable=True)
    target_audience = Column(Text, nullable=True)
    primary_services = Column(ARRAY(String), nullable=True)
    target_keywords = Column(ARRAY(String), nullable=True)
    competitor_urls = Column(ARRAY(String), nullable=True)
    seo_goal = Column(Text, nullable=True)
    brand_tone = Column(String(255), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="projects")
    owner = relationship("User", foreign_keys=[owner_id])
    crawl_jobs = relationship("CrawlJob", back_populates="project", cascade="all, delete-orphan")
    serp_analyses = relationship("SERPAnalysis", back_populates="project", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Project {self.name}>"

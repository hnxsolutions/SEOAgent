"""
SEO Agent SaaS - AI Agent Models
"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class AgentStatus(str, enum.Enum):
    """Agent run status enum"""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class AgentRun(Base):
    """AI Agent run model"""
    
    __tablename__ = "agent_runs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_type = Column(String, nullable=False)  # e.g., "seo_analyzer", "content_optimizer"
    status = Column(SQLEnum(AgentStatus), default=AgentStatus.pending)
    config = Column(JSON, nullable=True)
    input_data = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    project = relationship("Project")
    
    def __repr__(self):
        return f"<AgentRun {self.agent_type} - {self.status}>"

"""
SEO Agent SaaS - Tenant Model
"""
from sqlalchemy import Column, String, Boolean, DateTime, Table, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class SubscriptionTier(str, enum.Enum):
    """Subscription tier enum"""
    free = "free"
    pro = "pro"
    enterprise = "enterprise"


# Association table for tenant members
tenant_members = Table(
    "tenant_members",
    Base.metadata,
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("role", String, default="member"),  # owner, admin, member
    Column("created_at", DateTime, default=datetime.utcnow),
)


class Tenant(Base):
    """Tenant model for multi-tenant SaaS"""
    
    __tablename__ = "tenants"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    subscription_tier = Column(SQLEnum(SubscriptionTier), default=SubscriptionTier.free)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    members = relationship("User", secondary=tenant_members, back_populates="tenants")
    projects = relationship("Project", back_populates="tenant", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Tenant {self.name}>"

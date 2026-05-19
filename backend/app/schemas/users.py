"""
SEO Agent SaaS - User Schemas
"""
from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class UserBase(BaseModel):
    """Base user schema"""
    email: EmailStr
    full_name: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema for updating user profile"""
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserResponse(UserBase):
    """Schema for user response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class TenantBase(BaseModel):
    """Base tenant schema"""
    name: str
    slug: str


class TenantResponse(TenantBase):
    """Schema for tenant response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    subscription_tier: str = "free"
    created_at: datetime
    updated_at: Optional[datetime] = None

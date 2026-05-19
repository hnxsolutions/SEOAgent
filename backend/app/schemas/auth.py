"""
SEO Agent SaaS - Authentication Schemas
"""
from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID


class UserBase(BaseModel):
    """Base user schema"""
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """Schema for user registration"""
    password: str


class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class UserResponse(UserBase):
    """Schema for user response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class Token(BaseModel):
    """Schema for authentication token"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """Schema for refreshing an access token."""
    refresh_token: str


class TokenPayload(BaseModel):
    """Schema for token payload"""
    sub: str  # email
    user_id: str
    exp: datetime

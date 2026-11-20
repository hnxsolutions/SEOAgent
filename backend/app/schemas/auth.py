"""
SEO Agent SaaS - Authentication Schemas
"""
from pydantic import BaseModel, ConfigDict, EmailStr, Field
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


class ForgotPasswordRequest(BaseModel):
    """Start a reset. Only an address is needed."""

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Deliberately constant.

    The same body is returned for a registered address, an unregistered one and
    a disabled account, so the endpoint cannot be used to discover who has an
    account here.
    """

    message: str = (
        "If an account exists for that email, a password reset link has been sent."
    )


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=512)
    new_password: str = Field(..., min_length=8, max_length=200)


class ResetPasswordResponse(BaseModel):
    message: str = "Your password has been updated. You can now log in."


class ResetTokenCheckResponse(BaseModel):
    """Lets the reset page show an expired link before asking for a password."""

    valid: bool

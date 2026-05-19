"""
SEO Agent SaaS - Authentication Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.core.database import get_db
from app.schemas.auth import Token, UserCreate, UserResponse, RefreshTokenRequest
from app.services.auth import AuthService

router = APIRouter()


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Register a new user"""
    auth_service = AuthService(db)
    
    # Check if user already exists
    existing_user = await auth_service.get_user_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user
    user = await auth_service.create_user(user_data)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Login and get access token"""
    auth_service = AuthService(db)
    
    # Authenticate user
    user = await auth_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    tenant_id = await auth_service.get_default_tenant_id(user.id)
    token_data = {
        "sub": user.email,
        "user_id": str(user.id),
        "tenant_id": tenant_id,
    }

    # Generate tokens
    access_token = auth_service.create_access_token(data=token_data)
    refresh_token = auth_service.create_refresh_token(data=token_data)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_request: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Refresh access token"""
    auth_service = AuthService(db)
    
    # Validate refresh token
    payload = auth_service.verify_refresh_token(refresh_request.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Generate new access token
    access_token = auth_service.create_access_token(
        data={
            "sub": payload["sub"],
            "user_id": payload["user_id"],
            "tenant_id": payload.get("tenant_id"),
        }
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_request.refresh_token,  # Return same refresh token
        "token_type": "bearer"
    }

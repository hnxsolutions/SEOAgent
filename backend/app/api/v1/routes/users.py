"""
SEO Agent SaaS - User Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, List

from app.core.database import get_db
from app.schemas.users import UserResponse, UserUpdate, TenantResponse
from app.services.users import UserService
from app.core.security import get_current_user

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get current user profile"""
    user_service = UserService(db)
    user = await user_service.get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.put("/me", response_model=UserResponse)
async def update_current_user_profile(
    user_update: UserUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Update current user profile"""
    user_service = UserService(db)
    user = await user_service.update_user(current_user["user_id"], user_update)
    return user


@router.get("/me/tenants", response_model=List[TenantResponse])
async def get_user_tenants(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get all tenants (organizations) the user belongs to"""
    user_service = UserService(db)
    tenants = await user_service.get_user_tenants(current_user["user_id"])
    return tenants
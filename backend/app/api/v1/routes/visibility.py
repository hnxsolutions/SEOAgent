"""
SEO Agent SaaS - AI Visibility Tracking Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, List

from app.core.database import get_db
from app.schemas.visibility import VisibilityQuery, VisibilityResponse, VisibilityTrendResponse
from app.services.visibility import VisibilityService
from app.core.security import get_current_user

router = APIRouter()


@router.post("/query", response_model=VisibilityResponse)
async def query_visibility(
    query_data: VisibilityQuery,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Query AI visibility for specific keywords/topics"""
    visibility_service = VisibilityService(db)
    
    results = await visibility_service.query_visibility(
        keywords=query_data.keywords,
        topics=query_data.topics,
        date_range=query_data.date_range,
        tenant_id=current_user["tenant_id"]
    )
    
    return results


@router.get("/trends", response_model=VisibilityTrendResponse)
async def get_visibility_trends(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 30
):
    """Get AI visibility trends over time"""
    visibility_service = VisibilityService(db)
    
    trends = await visibility_service.get_trends(
        days=days,
        tenant_id=current_user["tenant_id"]
    )
    
    return trends


@router.get("/competitors", response_model=List[dict])
async def get_competitor_visibility(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get competitor AI visibility comparison"""
    visibility_service = VisibilityService(db)
    
    competitors = await visibility_service.get_competitor_analysis(
        tenant_id=current_user["tenant_id"]
    )
    
    return competitors

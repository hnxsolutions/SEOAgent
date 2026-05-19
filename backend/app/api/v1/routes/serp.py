"""
SEO Agent SaaS - SERP Analysis Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, List
from uuid import UUID

from app.core.database import get_db
from app.schemas.serp import SERPAnalysisRequest, SERPAnalysisResponse, SERPAnalysisStatusResponse
from app.services.serp import SERPService
from app.core.security import get_current_user

router = APIRouter()


@router.post("/analyze", response_model=SERPAnalysisResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_serp(
    analysis_request: SERPAnalysisRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Start SERP analysis for keywords"""
    serp_service = SERPService(db)
    
    # Create SERP analysis job
    analysis = await serp_service.create_analysis(
        keywords=analysis_request.keywords,
        location=analysis_request.location,
        language=analysis_request.language,
        search_engine=analysis_request.search_engine,
        tenant_id=current_user["tenant_id"],
        project_id=analysis_request.project_id
    )
    
    # Queue the analysis task
    background_tasks.add_task(
        serp_service.execute_analysis,
        analysis_id=analysis.id,
        keywords=analysis_request.keywords
    )
    
    return analysis


@router.get("/{analysis_id}", response_model=SERPAnalysisStatusResponse)
async def get_analysis_status(
    analysis_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get SERP analysis status and results"""
    serp_service = SERPService(db)
    analysis = await serp_service.get_analysis_status(analysis_id, current_user["tenant_id"])
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SERP analysis not found"
        )
    return analysis


@router.get("/", response_model=List[SERPAnalysisResponse])
async def list_analyses(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID = None
):
    """List all SERP analyses for current tenant"""
    serp_service = SERPService(db)
    analyses = await serp_service.get_tenant_analyses(
        tenant_id=current_user["tenant_id"],
        project_id=project_id
    )
    return analyses

"""Robots.txt intelligence routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.robots import RobotsIssueStatus
from app.schemas.robots import (
    RobotsAnalysisListResponse,
    RobotsAnalysisRunResponse,
    RobotsIssueListResponse,
    RobotsIssueResponse,
    RobotsIssueStatusUpdate,
    RobotsSummaryResponse,
)
from app.services.robots import RobotsIntelligenceService

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.post("/projects/{project_id}/analyze", response_model=RobotsAnalysisRunResponse)
async def analyze_robots(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Fetch and analyze the project's live robots.txt, storing the result."""
    service = RobotsIntelligenceService(db)
    try:
        return await service.analyze_project(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/analyses", response_model=RobotsAnalysisListResponse)
async def list_robots_analyses(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Historical robots.txt analyses for a project (newest first)."""
    service = RobotsIntelligenceService(db)
    analyses = await service.list_analyses(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    return RobotsAnalysisListResponse(
        analyses=analyses, limit=limit, offset=offset, has_more=len(analyses) == limit
    )


@router.get("/projects/{project_id}/latest", response_model=RobotsAnalysisRunResponse)
async def latest_robots_analysis(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Most recent robots.txt analysis for a project."""
    service = RobotsIntelligenceService(db)
    run = await service.get_latest_analysis(project_id, _tenant_id(current_user))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No robots analysis yet")
    return run


@router.get("/projects/{project_id}/issues", response_model=RobotsIssueListResponse)
async def list_robots_issues(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    analysis_run_id: Optional[UUID] = Query(None),
    issue_status: Optional[RobotsIssueStatus] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List robots.txt issues, optionally scoped to a run or status."""
    service = RobotsIntelligenceService(db)
    issues = await service.list_issues(
        project_id, _tenant_id(current_user),
        analysis_run_id=analysis_run_id, status=issue_status, limit=limit, offset=offset,
    )
    return RobotsIssueListResponse(issues=issues, limit=limit, offset=offset, has_more=len(issues) == limit)


@router.get("/projects/{project_id}/summary", response_model=RobotsSummaryResponse)
async def robots_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Latest robots.txt status with a latest-vs-previous regression delta."""
    service = RobotsIntelligenceService(db)
    return await service.summary(project_id, _tenant_id(current_user))


@router.post("/issues/{issue_id}/status", response_model=RobotsIssueResponse)
async def update_robots_issue_status(
    issue_id: UUID,
    payload: RobotsIssueStatusUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a robots issue status (open/approved/fixed/ignored)."""
    service = RobotsIntelligenceService(db)
    issue = await service.update_issue_status(issue_id, _tenant_id(current_user), payload.status)
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Robots issue not found")
    return issue

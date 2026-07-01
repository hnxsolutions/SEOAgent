"""GSC URL Inspection indexing intelligence routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.indexing import GSCIndexingIssueStatus, GSCIndexingIssueType
from app.schemas.indexing import (
    GSCIndexingIssueListResponse,
    GSCIndexingIssueResponse,
    GSCUrlInspectionRunDetailResponse,
    GSCUrlInspectionRunListResponse,
    GSCUrlInspectionRunResponse,
    IndexingFixPlanResponse,
    IndexingInspectRequest,
    IndexingSummaryResponse,
    IndexingValidationRequest,
    IndexingValidationResponse,
)
from app.services.indexing import IndexingService, IndexingServiceError
from app.services.search_console import SearchConsoleConfigurationError, SearchConsoleError

router = APIRouter()


@router.post("/projects/{project_id}/inspect", response_model=GSCUrlInspectionRunResponse)
async def inspect_project_urls(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: IndexingInspectRequest = Body(default_factory=IndexingInspectRequest),
):
    """Run URL Inspection API checks for explicit or priority-selected URLs."""
    service = IndexingService(db)
    try:
        return await service.inspect_project(
            tenant_id=_tenant_id(current_user),
            project_id=project_id,
            urls=payload.urls,
            limit=payload.limit,
            language_code=payload.language_code,
        )
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except (SearchConsoleError, IndexingServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/projects/{project_id}/runs", response_model=GSCUrlInspectionRunListResponse)
async def list_project_indexing_runs(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = IndexingService(db)
    runs = await service.list_runs(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    return GSCUrlInspectionRunListResponse(runs=runs, limit=limit, offset=offset, has_more=len(runs) == limit)


@router.get("/runs/{run_id}", response_model=GSCUrlInspectionRunDetailResponse)
async def get_indexing_run(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = IndexingService(db)
    try:
        return await service.get_run_details(run_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/issues", response_model=GSCIndexingIssueListResponse)
async def list_project_indexing_issues(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    issue_status: Optional[GSCIndexingIssueStatus] = Query(None, alias="status"),
    issue_type: Optional[GSCIndexingIssueType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = IndexingService(db)
    issues = await service.list_issues(
        project_id,
        _tenant_id(current_user),
        status=issue_status,
        issue_type=issue_type,
        limit=limit,
        offset=offset,
    )
    return GSCIndexingIssueListResponse(issues=issues, limit=limit, offset=offset, has_more=len(issues) == limit)


@router.get("/issues/{issue_id}", response_model=GSCIndexingIssueResponse)
async def get_indexing_issue(
    issue_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = IndexingService(db)
    issue = await service.get_issue(issue_id, _tenant_id(current_user))
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indexing issue not found")
    return issue


@router.post("/issues/{issue_id}/create-fix-plan", response_model=IndexingFixPlanResponse)
async def create_indexing_fix_plan(
    issue_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = IndexingService(db)
    try:
        return await service.create_fix_plan(issue_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/issues/{issue_id}/ignore", response_model=GSCIndexingIssueResponse)
async def ignore_indexing_issue(
    issue_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = IndexingService(db)
    try:
        return await service.ignore_issue(issue_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/issues/{issue_id}/validate", response_model=IndexingValidationResponse)
async def validate_indexing_issue(
    issue_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: IndexingValidationRequest = Body(default_factory=IndexingValidationRequest),
):
    service = IndexingService(db)
    try:
        return await service.validate_issue(
            issue_id,
            _tenant_id(current_user),
            validation_after_days=payload.validation_after_days,
            run_now=payload.run_now,
        )
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/projects/{project_id}/summary", response_model=IndexingSummaryResponse)
async def project_indexing_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = IndexingService(db)
    try:
        return await service.summary(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id

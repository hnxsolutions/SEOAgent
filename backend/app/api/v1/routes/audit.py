"""Deterministic SEO audit API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, get_db_session
from app.core.security import get_current_user
from app.models.audit import SEOIssueCategory, SEOIssueSeverity, SEOIssueStatus
from app.schemas.audit import (
    SEOAuditRunResponse,
    SEOIssueListResponse,
    SEOIssueResponse,
    SEOPageScoreResponse,
    SEOSiteSummaryResponse,
)
from app.services.audit import AuditService

router = APIRouter()


@router.post(
    "/crawls/{crawl_id}/start",
    response_model=SEOAuditRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_audit_for_crawl(
    crawl_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start a deterministic SEO audit for an existing crawl."""
    service = AuditService(db)
    try:
        audit_run = await service.start_audit(crawl_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    background_tasks.add_task(run_audit_background, audit_run.id)
    return audit_run


@router.get("/{audit_id}/status", response_model=SEOAuditRunResponse)
async def get_audit_status(
    audit_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get deterministic audit run status."""
    service = AuditService(db)
    audit_run = await service.get_audit_status(audit_id, current_user["tenant_id"])
    if not audit_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit run not found")
    return audit_run


@router.get("/issues", response_model=SEOIssueListResponse)
async def list_audit_issues(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    audit_id: Optional[UUID] = Query(None),
    crawl_id: Optional[UUID] = Query(None),
    project_id: Optional[UUID] = Query(None),
    page_id: Optional[UUID] = Query(None),
    severity: Optional[SEOIssueSeverity] = Query(None),
    category: Optional[SEOIssueCategory] = Query(None),
    issue_status: Optional[SEOIssueStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List SEO issues by audit, crawl, project, page, severity, category, or status."""
    service = AuditService(db)
    issues = await service.list_issues(
        tenant_id=current_user["tenant_id"],
        audit_run_id=audit_id,
        crawl_job_id=crawl_id,
        project_id=project_id,
        page_id=page_id,
        severity=severity,
        category=category,
        issue_status=issue_status,
        limit=limit,
        offset=offset,
    )
    return SEOIssueListResponse(
        issues=[SEOIssueResponse.model_validate(issue) for issue in issues],
        limit=limit,
        offset=offset,
        has_more=len(issues) == limit,
    )


@router.get("/pages/{page_id}/score", response_model=SEOPageScoreResponse)
async def get_page_seo_score(
    page_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    audit_id: Optional[UUID] = Query(None),
):
    """Get page-level SEO score for the latest or specified audit run."""
    service = AuditService(db)
    score = await service.get_page_score(page_id, current_user["tenant_id"], audit_id)
    if not score:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page SEO score not found")
    return score


@router.get("/crawls/{crawl_id}/summary", response_model=SEOSiteSummaryResponse)
async def get_site_seo_summary(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    audit_id: Optional[UUID] = Query(None),
):
    """Get site-level SEO score and issue summary for a crawl."""
    service = AuditService(db)
    summary = await service.get_site_summary(crawl_id, current_user["tenant_id"], audit_id)
    if not summary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit summary not found")
    return summary


async def run_audit_background(audit_run_id: UUID) -> None:
    """Execute an audit run with a fresh DB session for FastAPI background tasks."""
    db = get_db_session()
    try:
        service = AuditService(db)
        await service.execute_audit(audit_run_id)
    finally:
        await db.close()

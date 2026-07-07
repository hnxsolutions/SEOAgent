"""Sitemap intelligence routes (mounted under /search-console)."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.sitemap import (
    SitemapAnalyzeRequest,
    SitemapAnalyzeResponse,
    SitemapIssueListResponse,
    SitemapListResponse,
    SitemapRecordResponse,
    SitemapSubmitRequest,
)
from app.services.search_console import SearchConsoleConfigurationError, SearchConsoleError
from app.services.sitemap import SitemapIntelligenceService, SitemapServiceError

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.get("/projects/{project_id}/sitemaps", response_model=SitemapListResponse)
async def list_sitemaps(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List stored sitemap records (detected + submitted) for a project."""
    service = SitemapIntelligenceService(db)
    try:
        sitemaps = await service.list_sitemaps(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SitemapListResponse(
        sitemaps=[SitemapRecordResponse.model_validate(item) for item in sitemaps],
        oauth_enabled=service.google_client.credentials_configured,
    )


@router.get("/projects/{project_id}/sitemap-issues", response_model=SitemapIssueListResponse)
async def list_sitemap_issues(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    issue_status: Optional[str] = Query(default=None),
):
    """List sitemap issues for a project."""
    service = SitemapIntelligenceService(db)
    try:
        issues = await service.list_issues(project_id, _tenant_id(current_user), status=issue_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SitemapIssueListResponse(issues=issues)


@router.post("/projects/{project_id}/sitemaps/refresh", response_model=SitemapListResponse)
async def refresh_sitemaps(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Fetch submitted sitemaps from the GSC Sitemaps API and persist them."""
    service = SitemapIntelligenceService(db)
    try:
        sitemaps = await service.refresh(project_id, _tenant_id(current_user))
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except SitemapServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SearchConsoleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return SitemapListResponse(
        sitemaps=[SitemapRecordResponse.model_validate(item) for item in sitemaps],
        oauth_enabled=service.google_client.credentials_configured,
    )


@router.post("/projects/{project_id}/sitemaps/submit", response_model=SitemapRecordResponse)
async def submit_sitemap(
    project_id: UUID,
    payload: SitemapSubmitRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Submit a sitemap URL to Google Search Console (write scope required)."""
    service = SitemapIntelligenceService(db)
    try:
        record = await service.submit(project_id, _tenant_id(current_user), payload.sitemap_url)
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except SitemapServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SearchConsoleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return SitemapRecordResponse.model_validate(record)


@router.delete("/sitemaps/{sitemap_id}", response_model=SitemapRecordResponse)
async def delete_sitemap(
    sitemap_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a sitemap submission from Google Search Console."""
    service = SitemapIntelligenceService(db)
    try:
        record = await service.delete(sitemap_id, _tenant_id(current_user))
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except SitemapServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SearchConsoleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SitemapRecordResponse.model_validate(record)


@router.post("/projects/{project_id}/sitemaps/detect", response_model=SitemapListResponse)
async def detect_sitemaps(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Detect sitemaps from robots.txt and common paths (no Google needed)."""
    service = SitemapIntelligenceService(db)
    try:
        sitemaps = await service.detect(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return SitemapListResponse(
        sitemaps=[SitemapRecordResponse.model_validate(item) for item in sitemaps],
        oauth_enabled=service.google_client.credentials_configured,
    )


@router.post("/projects/{project_id}/sitemaps/analyze", response_model=SitemapAnalyzeResponse)
async def analyze_sitemaps(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: SitemapAnalyzeRequest = Body(default_factory=SitemapAnalyzeRequest),
):
    """Download and validate sitemaps, cross-reference the latest crawl, raise issues."""
    service = SitemapIntelligenceService(db)
    try:
        result = await service.analyze(
            project_id,
            _tenant_id(current_user),
            sitemap_id=payload.sitemap_id,
            sitemap_url=payload.sitemap_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return SitemapAnalyzeResponse(
        analyzed_sitemaps=result["analyzed_sitemaps"],
        issues_created=result["issues_created"],
        sitemaps=[SitemapRecordResponse.model_validate(item) for item in result["sitemaps"]],
    )

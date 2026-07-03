"""Search Console API mode and CSV fallback routes."""
from datetime import date, datetime
from typing import Annotated, Optional
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.search_console import (
    GSCComparisonWindow,
    GSCSyncType,
    SearchConsoleOpportunityStatus,
    SearchConsolePeriod,
)
from app.schemas.search_console import (
    GSCConnectionListResponse,
    GSCConnectionResponse,
    GSCMonitorRunResponse,
    GSCMonitorSettingsResponse,
    GSCMonitorSettingsUpdate,
    GSCProjectPropertyResponse,
    GoogleOAuthCallbackResponse,
    GoogleOAuthStartResponse,
    GSCPropertyListResponse,
    GSCPropertyManualCreateRequest,
    GSCPropertyResponse,
    GSCPropertySelectRequest,
    GSCSyncJobListResponse,
    GSCSyncJobResponse,
    GSCSyncRequest,
    SearchConsoleAnalyzeResponse,
    SearchConsoleImportListResponse,
    SearchConsoleImportResponse,
    SearchConsoleOpportunityListResponse,
    SearchConsoleOpportunityResponse,
    SearchConsoleRowListResponse,
    SearchConsoleSummaryResponse,
)
from app.services.search_console import (
    SearchConsoleConfigurationError,
    SearchConsoleError,
    SearchConsoleOAuthError,
    SearchConsoleService,
)

router = APIRouter()


@router.post("/connections/google/start", response_model=GoogleOAuthStartResponse)
async def start_google_connection(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a Google OAuth URL for Search Console access."""
    service = SearchConsoleService(db)
    try:
        return service.build_oauth_start(_tenant_id(current_user), current_user["user_id"])
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.get("/connections/google/callback")
async def google_connection_callback(
    code: str,
    state: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    as_json: bool = Query(False),
):
    """Handle the Google OAuth callback and store the encrypted refresh token."""
    service = SearchConsoleService(db)
    try:
        result = await service.handle_oauth_callback(code, state)
        if as_json:
            return GoogleOAuthCallbackResponse(
                connection_id=result["connection_id"],
                tenant_id=result["tenant_id"],
                status=_enum_value(result["status"]),
                scopes=result["scopes"],
            )
        params = urlencode({"gsc": "connected", "connectionId": str(result["connection_id"])})
        return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/search-console?{params}")
    except SearchConsoleOAuthError as exc:
        if not as_json:
            params = urlencode({"gsc": "error", "message": str(exc)})
            return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/search-console?{params}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SearchConsoleConfigurationError as exc:
        if not as_json:
            params = urlencode({"gsc": "error", "message": str(exc)})
            return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/search-console?{params}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.get("/connections", response_model=GSCConnectionListResponse)
async def list_google_connections(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List Google Search Console OAuth connections without exposing tokens."""
    service = SearchConsoleService(db)
    connections = await service.list_connections(_tenant_id(current_user))
    return GSCConnectionListResponse(connections=connections)


@router.delete("/connections/{connection_id}", response_model=GSCConnectionResponse)
async def revoke_google_connection(
    connection_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Revoke the local Search Console OAuth connection record."""
    service = SearchConsoleService(db)
    try:
        return await service.disconnect_connection(_tenant_id(current_user), connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/properties", response_model=GSCPropertyListResponse)
async def list_gsc_properties(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    refresh: bool = Query(True),
):
    """List stored GSC properties, optionally refreshing from Google."""
    service = SearchConsoleService(db)
    try:
        properties = await service.list_properties(
            tenant_id=_tenant_id(current_user),
            user_id=current_user["user_id"],
            project_id=project_id,
            refresh=refresh,
        )
        return GSCPropertyListResponse(properties=properties, oauth_enabled=service.google_oauth_enabled())
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except SearchConsoleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/projects/{project_id}/property", response_model=GSCPropertyResponse)
async def select_gsc_property(
    project_id: UUID,
    payload: GSCPropertySelectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Select the Search Console property used by a project."""
    service = SearchConsoleService(db)
    try:
        return await service.select_property(project_id, _tenant_id(current_user), payload.property_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/projects/{project_id}/property/select", response_model=GSCPropertyResponse)
async def select_gsc_property_alias(
    project_id: UUID,
    payload: GSCPropertySelectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Select the Search Console property used by a project."""
    return await select_gsc_property(project_id, payload, current_user, db)


@router.get("/projects/{project_id}/property", response_model=GSCProjectPropertyResponse)
async def get_project_gsc_property(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return selected GSC property and monitor setting for a project."""
    service = SearchConsoleService(db)
    try:
        return await service.selected_project_property(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/monitor", response_model=Optional[GSCMonitorSettingsResponse])
async def get_project_gsc_monitor(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return automatic Search Console monitor settings for a project."""
    service = SearchConsoleService(db)
    try:
        return await service.get_monitor_setting(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.put("/projects/{project_id}/monitor", response_model=GSCMonitorSettingsResponse)
async def update_project_gsc_monitor(
    project_id: UUID,
    payload: GSCMonitorSettingsUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create or update automatic Search Console monitor settings."""
    service = SearchConsoleService(db)
    try:
        return await service.update_monitor_setting(
            project_id,
            _tenant_id(current_user),
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/projects/{project_id}/property/manual",
    response_model=GSCPropertyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_gsc_property(
    project_id: UUID,
    payload: GSCPropertyManualCreateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register a manual GSC property for CSV fallback and onboarding context."""
    service = SearchConsoleService(db)
    try:
        return await service.register_manual_property(
            project_id=project_id,
            tenant_id=_tenant_id(current_user),
            site_url=payload.site_url,
            property_type=payload.property_type,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/projects/{project_id}/sync", response_model=GSCSyncJobResponse)
async def sync_project_search_console(
    project_id: UUID,
    payload: GSCSyncRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run a manual or scheduled Search Console sync for a project."""
    service = SearchConsoleService(db)
    try:
        return await service.sync_project(
            tenant_id=_tenant_id(current_user),
            project_id=project_id,
            sync_type=payload.sync_type,
            comparison_window=payload.comparison_window,
            date_start=_date_to_datetime(payload.date_start),
            date_end=_date_to_datetime(payload.date_end),
        )
    except SearchConsoleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SearchConsoleError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/projects/{project_id}/sync-jobs", response_model=GSCSyncJobListResponse)
async def list_project_sync_jobs(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List Search Console sync jobs for a project."""
    service = SearchConsoleService(db)
    jobs = await service.list_sync_jobs(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    return GSCSyncJobListResponse(sync_jobs=jobs, limit=limit, offset=offset, has_more=len(jobs) == limit)


@router.post("/monitor/run-due", response_model=GSCMonitorRunResponse)
async def run_due_gsc_monitors(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
):
    """Run due Search Console monitor syncs for the current tenant."""
    service = SearchConsoleService(db)
    result = await service.run_due_monitor_syncs(tenant_id=_tenant_id(current_user), limit=limit)
    return GSCMonitorRunResponse(due_count=result["due_count"], jobs=result["jobs"])


@router.get("/projects/{project_id}/summary", response_model=SearchConsoleSummaryResponse)
async def project_search_console_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return dashboard-ready Search Console monitoring summary."""
    service = SearchConsoleService(db)
    try:
        return await service.summary(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/imports", response_model=SearchConsoleImportResponse, status_code=status.HTTP_201_CREATED)
async def upload_search_console_csv(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    project_id: Optional[UUID] = Form(None),
    date_start: date = Form(...),
    date_end: date = Form(...),
    comparison_window: Optional[GSCComparisonWindow] = Form(None),
):
    """Upload CSV fallback data into the same normalized Search Console tables."""
    service = SearchConsoleService(db)
    try:
        return await service.import_csv(
            tenant_id=_tenant_id(current_user),
            project_id=project_id,
            filename=file.filename or "search-console.csv",
            content=await file.read(),
            date_start=_date_to_datetime(date_start) or datetime.utcnow(),
            date_end=_date_to_datetime(date_end) or datetime.utcnow(),
            comparison_window=comparison_window,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/imports", response_model=SearchConsoleImportListResponse)
async def list_search_console_imports(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List Search Console imports from CSV and GSC API syncs."""
    service = SearchConsoleService(db)
    imports = await service.list_imports(_tenant_id(current_user), project_id=project_id, limit=limit, offset=offset)
    return SearchConsoleImportListResponse(imports=imports, limit=limit, offset=offset, has_more=len(imports) == limit)


@router.get("/imports/{import_id}/status", response_model=SearchConsoleImportResponse)
async def get_search_console_import_status(
    import_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get Search Console import status."""
    service = SearchConsoleService(db)
    import_record = await service.get_import(import_id, _tenant_id(current_user))
    if not import_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search Console import not found")
    return import_record


@router.get("/imports/{import_id}/rows", response_model=SearchConsoleRowListResponse)
async def list_search_console_rows(
    import_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    period: Optional[SearchConsolePeriod] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List normalized rows for an import."""
    service = SearchConsoleService(db)
    try:
        rows = await service.list_rows(import_id, _tenant_id(current_user), period=period, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SearchConsoleRowListResponse(rows=rows, limit=limit, offset=offset, has_more=len(rows) == limit)


@router.post("/imports/{import_id}/analyze", response_model=SearchConsoleAnalyzeResponse)
async def analyze_search_console_import(
    import_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run deterministic opportunity analysis for an import."""
    service = SearchConsoleService(db)
    try:
        result = await service.analyze_import(import_id, _tenant_id(current_user))
        return SearchConsoleAnalyzeResponse(
            import_id=import_id,
            opportunities_created=result.created,
            opportunities_updated=result.updated,
            opportunities_total=len(result.opportunities),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/imports/{import_id}/opportunities", response_model=SearchConsoleOpportunityListResponse)
async def list_import_opportunities(
    import_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    opportunity_status: Optional[SearchConsoleOpportunityStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List opportunities generated for one import."""
    service = SearchConsoleService(db)
    opportunities = await service.list_opportunities(
        tenant_id=_tenant_id(current_user),
        import_id=import_id,
        status=opportunity_status,
        limit=limit,
        offset=offset,
    )
    return SearchConsoleOpportunityListResponse(
        opportunities=opportunities,
        limit=limit,
        offset=offset,
        has_more=len(opportunities) == limit,
    )


@router.post("/opportunities/{opportunity_id}/approve", response_model=SearchConsoleOpportunityResponse)
async def approve_search_console_opportunity(
    opportunity_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_opportunity_status(
        opportunity_id,
        current_user,
        db,
        SearchConsoleOpportunityStatus.approved,
    )


@router.post("/opportunities/{opportunity_id}/reject", response_model=SearchConsoleOpportunityResponse)
async def reject_search_console_opportunity(
    opportunity_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_opportunity_status(
        opportunity_id,
        current_user,
        db,
        SearchConsoleOpportunityStatus.rejected,
    )


@router.post("/opportunities/{opportunity_id}/mark-completed", response_model=SearchConsoleOpportunityResponse)
async def complete_search_console_opportunity(
    opportunity_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_opportunity_status(
        opportunity_id,
        current_user,
        db,
        SearchConsoleOpportunityStatus.completed,
    )


async def _set_opportunity_status(
    opportunity_id: UUID,
    current_user: dict,
    db: AsyncSession,
    opportunity_status: SearchConsoleOpportunityStatus,
):
    service = SearchConsoleService(db)
    try:
        return await service.update_opportunity_status(opportunity_id, _tenant_id(current_user), opportunity_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id


def _date_to_datetime(value: Optional[date]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time())


def _enum_value(value) -> str:
    return str(getattr(value, "value", value))

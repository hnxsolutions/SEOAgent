"""Schemas for Search Console API mode and CSV fallback."""
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.search_console import (
    GSCComparisonWindow,
    GSCSyncJobStatus,
    GSCSyncType,
    GSCPropertySourceType,
    GSCPropertyType,
    SearchConsoleImportStatus,
    SearchConsoleOpportunityStatus,
    SearchConsoleOpportunityType,
    SearchConsolePeriod,
    SearchConsoleSourceType,
)


class GoogleOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str
    expires_at: datetime
    scopes: List[str]


class GoogleOAuthCallbackResponse(BaseModel):
    connection_id: UUID
    tenant_id: UUID
    status: str
    scopes: List[str]


class GSCPropertyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    connection_id: Optional[UUID] = None
    site_url: str
    source_type: GSCPropertySourceType = GSCPropertySourceType.oauth
    property_type: GSCPropertyType = GSCPropertyType.url_prefix
    permission_level: Optional[str] = None
    notes: Optional[str] = None
    is_selected: bool
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class GSCPropertyListResponse(BaseModel):
    properties: List[GSCPropertyResponse]
    oauth_enabled: bool


class GSCPropertySelectRequest(BaseModel):
    property_id: UUID


class GSCPropertyManualCreateRequest(BaseModel):
    site_url: str = Field(..., min_length=1, max_length=2048)
    property_type: GSCPropertyType
    notes: Optional[str] = None


class GSCSyncRequest(BaseModel):
    comparison_window: GSCComparisonWindow = GSCComparisonWindow.last_28_days
    sync_type: GSCSyncType = GSCSyncType.manual
    date_start: Optional[date] = None
    date_end: Optional[date] = None


class GSCSyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    connection_id: Optional[UUID] = None
    property_id: UUID
    import_id: Optional[UUID] = None
    sync_type: GSCSyncType
    date_start: datetime
    date_end: datetime
    comparison_window: GSCComparisonWindow
    status: GSCSyncJobStatus
    rows_fetched: int = 0
    opportunities_created: int = 0
    opportunities_updated: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class GSCSyncJobListResponse(BaseModel):
    sync_jobs: List[GSCSyncJobResponse]
    limit: int
    offset: int
    has_more: bool = False


class SearchConsoleImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    source_type: SearchConsoleSourceType
    status: SearchConsoleImportStatus
    filename: Optional[str] = None
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    comparison_window: Optional[GSCComparisonWindow] = None
    rows_imported: int = 0
    error_message: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SearchConsoleImportListResponse(BaseModel):
    imports: List[SearchConsoleImportResponse]
    limit: int
    offset: int
    has_more: bool = False


class SearchConsoleRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    import_id: UUID
    property_id: Optional[UUID] = None
    crawl_page_id: Optional[UUID] = None
    query: str
    page_url: str
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0
    position: float = 0
    date_start: datetime
    date_end: datetime
    country: Optional[str] = None
    device: Optional[str] = None
    search_appearance: Optional[str] = None
    comparison_window: Optional[GSCComparisonWindow] = None
    period: SearchConsolePeriod
    source_type: SearchConsoleSourceType
    content_hash: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class SearchConsoleRowListResponse(BaseModel):
    rows: List[SearchConsoleRowResponse]
    limit: int
    offset: int
    has_more: bool = False


class SearchConsoleOpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    import_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    crawl_page_id: Optional[UUID] = None
    query: str
    page_url: str
    opportunity_type: SearchConsoleOpportunityType
    status: SearchConsoleOpportunityStatus
    current_clicks: int = 0
    current_impressions: int = 0
    current_ctr: float = 0
    current_position: float = 0
    previous_clicks: Optional[int] = None
    previous_impressions: Optional[int] = None
    previous_ctr: Optional[float] = None
    previous_position: Optional[float] = None
    reason: str
    recommended_action: str
    priority_score: float
    confidence_score: float
    evidence: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SearchConsoleOpportunityListResponse(BaseModel):
    opportunities: List[SearchConsoleOpportunityResponse]
    limit: int
    offset: int
    has_more: bool = False


class SearchConsoleAnalyzeResponse(BaseModel):
    import_id: UUID
    opportunities_created: int
    opportunities_updated: int
    opportunities_total: int


class SearchConsoleSummaryResponse(BaseModel):
    project_id: UUID
    imports_count: int
    rows_count: int
    opportunities_count: int
    opportunities_by_status: Dict[str, int]
    opportunities_by_type: Dict[str, int]
    latest_sync_job_id: Optional[UUID] = None
    latest_sync_status: Optional[str] = None
    selected_property: Optional[GSCPropertyResponse] = None
    top_opportunities: List[SearchConsoleOpportunityResponse] = Field(default_factory=list)

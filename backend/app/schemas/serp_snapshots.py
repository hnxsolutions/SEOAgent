"""Schemas for manual SERP snapshot tracking."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.serp import (
    SerpSnapshotAssetType,
    SerpSnapshotCaptureMode,
    SerpSnapshotDevice,
    SerpSnapshotSearchEngine,
    SerpSnapshotStatus,
)


class SerpSnapshotResultInput(BaseModel):
    position: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=1000)
    url: str = Field(..., min_length=1, max_length=2048)
    snippet: Optional[str] = None


class SerpSnapshotCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=1000)
    target_url: Optional[str] = Field(None, max_length=2048)
    target_domain: str = Field(..., min_length=1, max_length=255)
    search_engine: SerpSnapshotSearchEngine = SerpSnapshotSearchEngine.google
    country: str = Field(..., min_length=1, max_length=100)
    city: Optional[str] = Field(None, max_length=255)
    device: SerpSnapshotDevice = SerpSnapshotDevice.desktop
    language: Optional[str] = Field(None, max_length=50)
    capture_mode: SerpSnapshotCaptureMode = SerpSnapshotCaptureMode.manual
    notes: Optional[str] = None
    results: List[SerpSnapshotResultInput] = Field(default_factory=list)


class SerpSnapshotResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    snapshot_id: UUID
    position: int
    title: str
    url: str
    domain: str
    snippet: Optional[str] = None
    is_target_domain: bool
    is_target_url: bool


class SerpSnapshotAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    snapshot_id: UUID
    asset_type: SerpSnapshotAssetType
    file_path: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    created_at: datetime


class SerpSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    keyword: str
    target_url: Optional[str] = None
    target_domain: str
    search_engine: SerpSnapshotSearchEngine
    country: str
    city: Optional[str] = None
    device: SerpSnapshotDevice
    language: Optional[str] = None
    capture_mode: SerpSnapshotCaptureMode
    observed_target_rank: Optional[int] = None
    status: SerpSnapshotStatus
    captured_at: datetime
    notes: Optional[str] = None
    results: List[SerpSnapshotResultResponse] = Field(default_factory=list)
    assets: List[SerpSnapshotAssetResponse] = Field(default_factory=list)
    competitors_above_target: List[SerpSnapshotResultResponse] = Field(default_factory=list)
    previous_rank: Optional[int] = None
    rank_delta: Optional[int] = None


class SerpSnapshotListResponse(BaseModel):
    snapshots: List[SerpSnapshotResponse]
    limit: int
    offset: int
    has_more: bool = False


class SerpSnapshotHistoryResponse(BaseModel):
    history: List[SerpSnapshotResponse]


class SerpSnapshotSummaryResponse(BaseModel):
    project_id: UUID
    total_snapshots: int
    keywords_tracked: int
    latest_snapshots: List[SerpSnapshotResponse]
    message: str = "SERP snapshots are manual evidence. Official rank tracking uses GSC average position."

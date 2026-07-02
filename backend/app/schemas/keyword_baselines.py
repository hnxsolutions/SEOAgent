"""Schemas for manual keyword baseline records."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.keyword_baseline import KeywordBaselineDevice, KeywordBaselineSource


class KeywordBaselineCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=1000)
    target_location: Optional[str] = Field(None, max_length=255)
    search_engine: str = Field("google", min_length=1, max_length=50)
    device: KeywordBaselineDevice = KeywordBaselineDevice.desktop
    current_position: Optional[int] = Field(None, ge=1, le=100)
    current_url: Optional[str] = Field(None, max_length=2048)
    search_volume: Optional[int] = Field(None, ge=0)
    difficulty: Optional[int] = Field(None, ge=0, le=100)
    intent: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    source: KeywordBaselineSource = KeywordBaselineSource.manual
    captured_at: Optional[datetime] = None

    @field_validator("keyword", "search_engine")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Value cannot be blank")
        return text

    @field_validator("target_location", "current_url", "intent", "notes")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None


class KeywordBaselineUpdate(BaseModel):
    keyword: Optional[str] = Field(None, min_length=1, max_length=1000)
    target_location: Optional[str] = Field(None, max_length=255)
    search_engine: Optional[str] = Field(None, min_length=1, max_length=50)
    device: Optional[KeywordBaselineDevice] = None
    current_position: Optional[int] = Field(None, ge=1, le=100)
    current_url: Optional[str] = Field(None, max_length=2048)
    search_volume: Optional[int] = Field(None, ge=0)
    difficulty: Optional[int] = Field(None, ge=0, le=100)
    intent: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    source: Optional[KeywordBaselineSource] = None
    captured_at: Optional[datetime] = None

    @field_validator("keyword", "search_engine")
    @classmethod
    def strip_required_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("Value cannot be blank")
        return text

    @field_validator("target_location", "current_url", "intent", "notes")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None


class KeywordBaselineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    keyword: str
    target_location: Optional[str] = None
    search_engine: str
    device: KeywordBaselineDevice
    current_position: Optional[int] = None
    current_url: Optional[str] = None
    search_volume: Optional[int] = None
    difficulty: Optional[int] = None
    intent: Optional[str] = None
    notes: Optional[str] = None
    source: KeywordBaselineSource
    captured_at: datetime
    created_at: datetime
    updated_at: Optional[datetime] = None


class KeywordBaselineListResponse(BaseModel):
    baselines: List[KeywordBaselineResponse]
    limit: int
    offset: int
    has_more: bool = False


class KeywordBaselineBulkRequest(BaseModel):
    items: List[KeywordBaselineCreate] = Field(..., min_length=1, max_length=500)


class KeywordBaselineBulkResponse(BaseModel):
    created_count: int
    baselines: List[KeywordBaselineResponse]

"""Schemas for GSC-based rank tracking."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RankTrackingRow(BaseModel):
    query: str
    page_url: str
    country: Optional[str] = None
    device: Optional[str] = None
    search_appearance: Optional[str] = None
    current_clicks: int = 0
    current_impressions: int = 0
    current_ctr: float = 0
    current_position: float = 0
    previous_clicks: int = 0
    previous_impressions: int = 0
    previous_ctr: float = 0
    previous_position: float = 0
    position_delta: float = 0
    clicks_delta: int = 0
    impressions_delta: int = 0
    ctr_delta: float = 0
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None


class RankTrackingListResponse(BaseModel):
    rankings: List[RankTrackingRow]
    limit: int
    offset: int
    has_more: bool = False


class RankTrackingPageRow(BaseModel):
    page_url: str
    query_count: int
    current_clicks: int
    current_impressions: int
    current_ctr: float
    current_position: float
    previous_clicks: int
    previous_impressions: int
    previous_ctr: float
    previous_position: float
    position_delta: float
    clicks_delta: int
    impressions_delta: int


class RankTrackingPagesResponse(BaseModel):
    pages: List[RankTrackingPageRow]
    limit: int
    offset: int
    has_more: bool = False


class RankTrackingKeywordRow(BaseModel):
    query: str
    page_count: int
    current_clicks: int
    current_impressions: int
    current_ctr: float
    current_position: float
    previous_clicks: int
    previous_impressions: int
    previous_ctr: float
    previous_position: float
    position_delta: float
    clicks_delta: int
    impressions_delta: int


class RankTrackingKeywordsResponse(BaseModel):
    keywords: List[RankTrackingKeywordRow]
    limit: int
    offset: int
    has_more: bool = False


class RankTrackingSummaryResponse(BaseModel):
    project_id: UUID
    total_keywords: int
    total_pages: int
    total_rows: int
    improved_keywords: int
    dropped_keywords: int
    striking_distance_keywords: int
    low_ctr_keywords: int
    total_clicks: int
    total_impressions: int
    average_ctr: float
    average_position: float
    message: Optional[str] = None
    top_movements: List[RankTrackingRow] = Field(default_factory=list)


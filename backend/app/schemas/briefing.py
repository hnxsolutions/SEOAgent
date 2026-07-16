"""Schemas for daily briefing + notification APIs."""
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.briefing import NotificationLevel


class DailyBriefingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    briefing_date: date
    health_score: Optional[float] = None
    ai_confidence: Optional[float] = None
    seo_score: Optional[float] = None
    seo_score_prev: Optional[float] = None
    executive_summary: str
    summary_source: str
    sections: Dict[str, Any]
    timeline: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None


class BriefingHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    briefing_date: date
    health_score: Optional[float] = None
    seo_score: Optional[float] = None
    ai_confidence: Optional[float] = None
    executive_summary: str


class BriefingHistoryResponse(BaseModel):
    briefings: List[BriefingHistoryItem]
    total: int


class BriefingTrendsResponse(BaseModel):
    window_days: int
    count: int
    points: List[Dict[str, Any]]


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    project_id: Optional[UUID] = None
    level: NotificationLevel
    category: str
    title: str
    message: str
    read: bool
    created_at: Optional[datetime] = None


class NotificationListResponse(BaseModel):
    notifications: List[NotificationResponse]
    unread_count: int

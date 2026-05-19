"""
SEO Agent SaaS - AI Visibility Schemas
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class VisibilityQuery(BaseModel):
    """Schema for visibility query"""
    keywords: Optional[List[str]] = None
    topics: Optional[List[str]] = None
    date_range: Optional[Dict[str, datetime]] = None


class VisibilityResponse(BaseModel):
    """Schema for visibility response"""
    total_mentions: int
    visibility_score: float
    avg_position: float
    top_keywords: List[Dict[str, Any]]
    trends: Optional[List[Dict[str, Any]]] = None


class VisibilityTrendResponse(BaseModel):
    """Schema for visibility trends"""
    data_points: List[Dict[str, Any]]
    trend_direction: str  # "up", "down", "stable"
    change_percentage: float


class VisibilityMetric(BaseModel):
    """Schema for individual visibility metric"""
    keyword: str
    mentions: int
    avg_position: float
    visibility_score: float
    trend: str
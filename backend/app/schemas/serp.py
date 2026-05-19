"""
SEO Agent SaaS - SERP Analysis Schemas
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class SERPAnalysisRequest(BaseModel):
    """Schema for SERP analysis request"""
    keywords: List[str]
    project_id: Optional[UUID] = None
    location: str = "us"
    language: str = "en"
    search_engine: str = "google"


class SERPAnalysisBase(BaseModel):
    """Base SERP analysis schema"""
    keywords: List[str]
    status: str = "pending"
    progress: int = 0
    total_keywords: int
    analyzed_keywords: int = 0


class SERPAnalysisResponse(SERPAnalysisBase):
    """Schema for SERP analysis response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    location: str
    language: str
    search_engine: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SERPResultResponse(BaseModel):
    """Schema for individual SERP result"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    keyword: str
    position: Optional[int] = None
    url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    domain_authority: Optional[int] = None
    page_authority: Optional[int] = None
    backlinks: Optional[int] = None
    created_at: datetime


class SERPAnalysisStatusResponse(SERPAnalysisResponse):
    """Schema for SERP analysis status with results"""
    results: Optional[List[SERPResultResponse]] = None
    error_message: Optional[str] = None

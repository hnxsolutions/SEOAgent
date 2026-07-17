"""Schemas for Core Web Vitals / PageSpeed APIs."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.pagespeed import PagespeedStatus, PagespeedStrategy


class PagespeedRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    project_id: UUID
    url: str
    strategy: PagespeedStrategy
    status: PagespeedStatus
    performance_score: Optional[float] = None
    accessibility_score: Optional[float] = None
    best_practices_score: Optional[float] = None
    seo_score: Optional[float] = None
    lcp_ms: Optional[float] = None
    cls: Optional[float] = None
    inp_ms: Optional[float] = None
    tbt_ms: Optional[float] = None
    fcp_ms: Optional[float] = None
    speed_index_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    field_lcp_ms: Optional[float] = None
    field_cls: Optional[float] = None
    field_inp_ms: Optional[float] = None
    opportunities: Optional[List[Dict[str, Any]]] = None
    diagnostics: Optional[List[Dict[str, Any]]] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


class PagespeedAnalyzeResponse(BaseModel):
    runs: List[PagespeedRunResponse]


class PagespeedLatestResponse(BaseModel):
    mobile: Optional[PagespeedRunResponse] = None
    desktop: Optional[PagespeedRunResponse] = None


class PagespeedHistoryResponse(BaseModel):
    runs: List[PagespeedRunResponse]
    total: int

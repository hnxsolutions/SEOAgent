"""Schemas for sitemap intelligence APIs."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.sitemap import (
    SitemapIssueSeverity,
    SitemapIssueStatus,
    SitemapIssueType,
    SitemapSource,
    SitemapStatus,
)


class SitemapSubmitRequest(BaseModel):
    sitemap_url: str = Field(min_length=3, max_length=2048)


class SitemapAnalyzeRequest(BaseModel):
    sitemap_id: Optional[UUID] = None
    sitemap_url: Optional[str] = Field(default=None, max_length=2048)


class SitemapIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    sitemap_id: UUID
    issue_type: SitemapIssueType
    severity: SitemapIssueSeverity
    title: str
    description: str
    recommended_action: str
    sample_urls: Optional[List[str]] = None
    status: SitemapIssueStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class SitemapRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    property_id: Optional[UUID] = None
    sitemap_url: str
    is_submitted: bool
    is_pending: bool
    is_sitemaps_index: bool
    last_submitted_at: Optional[datetime] = None
    last_downloaded_at: Optional[datetime] = None
    errors_count: int
    warnings_count: int
    submitted_urls_count: int
    source: SitemapSource
    status: SitemapStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class SitemapListResponse(BaseModel):
    sitemaps: List[SitemapRecordResponse]
    oauth_enabled: bool = False


class SitemapIssueListResponse(BaseModel):
    issues: List[SitemapIssueResponse]


class SitemapAnalyzeResponse(BaseModel):
    analyzed_sitemaps: int
    issues_created: int
    sitemaps: List[SitemapRecordResponse]

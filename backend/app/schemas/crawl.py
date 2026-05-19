"""
SEO Agent SaaS - Enhanced Crawl Schemas
Comprehensive schemas for crawl operations
"""
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


# ========== Request Schemas ==========

class CrawlRequest(BaseModel):
    """Schema for initiating a new crawl job"""
    url: HttpUrl = Field(..., description="Starting URL for the crawl")
    project_id: Optional[UUID] = Field(None, description="Project ID to associate with crawl")
    name: Optional[str] = Field(None, description="Friendly name for the crawl job")
    
    # Crawl parameters
    max_pages: int = Field(100, ge=1, le=10000, description="Maximum pages to crawl")
    depth: int = Field(2, ge=0, le=10, description="Maximum crawl depth")
    priority: str = Field("normal", description="Crawl priority: low, normal, high, critical")
    
    # Crawl settings
    crawl_delay: float = Field(1.0, ge=0, le=60, description="Delay between requests in seconds")
    request_timeout: int = Field(30, ge=5, le=300, description="Request timeout in seconds")
    max_retries: int = Field(3, ge=0, le=10, description="Maximum retry attempts")
    
    # Domain restrictions
    allowed_domains: Optional[List[str]] = Field(None, description="List of allowed domains")
    excluded_paths: Optional[List[str]] = Field(None, description="Path patterns to exclude")
    follow_subdomains: bool = Field(False, description="Whether to follow subdomains")
    
    # Rate limiting
    rate_limit_requests: int = Field(10, ge=1, le=100, description="Requests per rate limit window")
    rate_limit_window: int = Field(60, ge=10, le=3600, description="Rate limit window in seconds")
    
    # Robots & Sitemap
    respect_robots_txt: bool = Field(True, description="Whether to respect robots.txt")
    sitemap_urls: Optional[List[str]] = Field(None, description="Additional sitemap URLs")
    
    # Browser settings
    render_javascript: bool = Field(True, description="Whether to render JavaScript")
    wait_for_selector: Optional[str] = Field(None, description="CSS selector to wait for")
    user_agent: Optional[str] = Field(None, description="Custom user agent")
    
    @field_validator("excluded_paths", mode="before")
    @classmethod
    def validate_excluded_paths(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            return [p.strip() for p in v.split(',')]
        return v


class PauseCrawlRequest(BaseModel):
    """Schema for pausing a crawl"""
    reason: Optional[str] = Field(None, description="Reason for pausing")


class ResumeCrawlRequest(BaseModel):
    """Schema for resuming a paused crawl"""
    pass


class CancelCrawlRequest(BaseModel):
    """Schema for cancelling a crawl"""
    reason: Optional[str] = Field(None, description="Reason for cancellation")


# ========== Response Schemas ==========

class CrawlPageSummary(BaseModel):
    """Summary of a crawled page"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    title: Optional[str] = None
    meta_description: Optional[str] = None
    word_count: int = 0
    internal_links: int = 0
    external_links: int = 0
    issue_count: int = 0
    critical_issues: int = 0
    warning_issues: int = 0
    crawled_at: datetime


class CrawlLinkSummary(BaseModel):
    """Summary of a crawled link"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    link_text: Optional[str] = None
    link_type: str
    is_nofollow: bool = False
    is_broken: bool = False
    status_code: Optional[int] = None


class CrawlErrorSummary(BaseModel):
    """Summary of a crawl error"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    error_type: str
    error_message: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime


class CrawlJobResponse(BaseModel):
    """Response schema for crawl job"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    name: Optional[str] = None
    status: str
    priority: str
    progress: int = 0
    
    # Configuration
    max_pages: int
    max_depth: int
    crawl_delay: float
    request_timeout: int
    max_retries: int
    
    # Domain restrictions
    allowed_domains: Optional[List[str]] = None
    excluded_paths: Optional[List[str]] = None
    follow_subdomains: bool = False
    
    # Rate limiting
    rate_limit_requests: int
    rate_limit_window: int
    
    # Robots & Sitemap
    respect_robots_txt: bool = True
    sitemap_urls: Optional[List[str]] = None
    
    # Browser settings
    render_javascript: bool = True
    wait_for_selector: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Progress
    total_pages_discovered: int = 0
    total_pages_crawled: int = 0
    total_pages_failed: int = 0
    total_pages_skipped: int = 0
    
    # Results
    total_internal_links: int = 0
    total_external_links: int = 0
    total_issues_found: int = 0
    
    # Error
    error_message: Optional[str] = None
    last_error_at: Optional[datetime] = None
    
    # Tenant & Project
    project_id: Optional[UUID] = None
    tenant_id: UUID
    
    # Timestamps
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CrawlStatusResponse(BaseModel):
    """Detailed crawl status response"""
    job: CrawlJobResponse
    progress: Dict[str, Any]
    stats: Dict[str, Any]
    
    # Recent pages
    recent_pages: List[CrawlPageSummary] = Field(default_factory=list)
    
    # Recent errors
    recent_errors: List[CrawlErrorSummary] = Field(default_factory=list)


class CrawlProgressResponse(BaseModel):
    """Crawl progress response"""
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str
    progress: int
    url: str
    total_pages_crawled: int
    total_pages_failed: int
    total_pages_skipped: int
    total_pages_discovered: int
    max_pages: int
    total_internal_links: int
    total_external_links: int
    total_issues_found: int
    critical_issues: int
    warning_issues: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CrawlResultsResponse(BaseModel):
    """Crawl results with pagination"""
    job_id: UUID
    total_pages: int
    pages: List[CrawlPageSummary]
    total_issues: int
    critical_issues: int
    warning_issues: int
    
    # Pagination
    limit: int
    offset: int
    has_more: bool = False


class CrawlSummaryResponse(BaseModel):
    """Summary of crawl results"""
    job_id: UUID
    url: str
    status: str
    total_pages: int
    status_code_distribution: Dict[int, int]
    issue_summary: Dict[str, int]
    total_internal_links: int
    total_external_links: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class CrawlListResponse(BaseModel):
    """List of crawl jobs with pagination"""
    crawls: List[CrawlJobResponse]
    total: int
    limit: int
    offset: int
    has_more: bool = False


# ========== SEO Analysis Schemas ==========

class PageSEOIssues(BaseModel):
    """SEO issues found on a page"""
    page_id: UUID
    url: str
    issues: List[Dict[str, Any]]
    critical_count: int
    warning_count: int
    info_count: int


class SiteSEOSummary(BaseModel):
    """SEO summary for an entire site"""
    total_pages: int
    pages_with_issues: int
    total_issues: int
    critical_issues: int
    warning_issues: int
    info_issues: int
    
    # Issue breakdown
    issue_breakdown: Dict[str, int]
    
    # Top issues
    top_issues: List[Dict[str, Any]]


# ========== Queue Stats Schema ==========

class QueueStatsResponse(BaseModel):
    """Queue statistics"""
    queue_name: str
    queued: int
    processing: int
    delayed: int
    failed: int
    total: int


class WorkerStatsResponse(BaseModel):
    """Worker statistics"""
    worker_id: str
    running: bool
    tasks_completed: int
    tasks_failed: int
    current_task: Optional[str] = None
    crawler_stats: Dict[str, Any] = Field(default_factory=dict)


# ========== Export Schemas ==========

class ExportCrawlDataRequest(BaseModel):
    """Request for exporting crawl data"""
    format: str = Field("csv", description="Export format: csv, json, excel")
    include_pages: bool = True
    include_links: bool = False
    include_issues: bool = True
    filter_status_codes: Optional[List[int]] = None
    filter_has_issues: bool = False

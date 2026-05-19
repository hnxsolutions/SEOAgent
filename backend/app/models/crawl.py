"""
SEO Agent SaaS - Crawl Models
Comprehensive models for distributed SEO crawling system
"""
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, Text, 
    Enum as SQLEnum, Float, JSON, BigInteger, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class CrawlStatus(str, enum.Enum):
    """Crawl job status enum"""
    pending = "pending"
    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class CrawlPriority(str, enum.Enum):
    """Crawl priority levels"""
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"


class PageIssueType(str, enum.Enum):
    """Types of SEO issues that can be detected"""
    MISSING_TITLE = "missing_title"
    MISSING_META_DESCRIPTION = "missing_meta_description"
    TITLE_TOO_LONG = "title_too_long"
    TITLE_TOO_SHORT = "title_too_short"
    META_DESCRIPTION_TOO_LONG = "meta_description_too_long"
    META_DESCRIPTION_TOO_SHORT = "meta_description_too_short"
    MISSING_H1 = "missing_h1"
    MULTIPLE_H1 = "multiple_h1"
    MISSING_CANONICAL = "missing_canonical"
    DUPLICATE_CANONICAL = "duplicate_canonical"
    BROKEN_LINK = "broken_link"
    REDIRECT_CHAIN = "redirect_chain"
    SLOW_PAGE_LOAD = "slow_page_load"
    MISSING_ALT_TAGS = "missing_alt_tags"
    DUPLICATE_CONTENT = "duplicate_content"
    NOINDEX_PAGE = "noindex_page"
    NOFOLLOW_PAGE = "nofollow_page"
    MISSING_ROBOTS_META = "missing_robots_meta"
    INVALID_ROBOTS_META = "invalid_robots_meta"
    MISSING_SCHEMA_MARKUP = "missing_schema_markup"
    MISSING_OG_TAGS = "missing_og_tags"
    MISSING_TWITTER_CARD = "missing_twitter_card"
    INTERNAL_LINK_ISSUES = "internal_link_issues"
    EXTERNAL_LINK_ISSUES = "external_link_issues"


class CrawlJob(Base):
    """Crawl job model - represents a complete crawl session"""
    
    __tablename__ = "crawl_jobs"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Basic Configuration
    url = Column(String(2048), nullable=False)
    name = Column(String(255), nullable=True)  # Optional friendly name
    status = Column(SQLEnum(CrawlStatus), default=CrawlStatus.pending, index=True)
    priority = Column(SQLEnum(CrawlPriority), default=CrawlPriority.normal)
    
    # Crawl Parameters
    max_pages = Column(Integer, default=100)
    max_depth = Column(Integer, default=2)
    crawl_delay = Column(Float, default=1.0)  # Delay between requests in seconds
    request_timeout = Column(Integer, default=30)  # Timeout per request in seconds
    max_retries = Column(Integer, default=3)
    
    # Domain Restrictions
    allowed_domains = Column(JSON, nullable=True)  # List of allowed domains
    excluded_paths = Column(JSON, nullable=True)  # List of path patterns to exclude
    follow_subdomains = Column(Boolean, default=False)
    
    # Rate Limiting
    rate_limit_requests = Column(Integer, default=10)  # Requests per window
    rate_limit_window = Column(Integer, default=60)  # Window in seconds
    
    # Robot.txt & Sitemap
    respect_robots_txt = Column(Boolean, default=True)
    sitemap_urls = Column(JSON, nullable=True)  # Additional sitemap URLs
    
    # Browser Settings
    render_javascript = Column(Boolean, default=True)
    wait_for_selector = Column(String, nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Progress Tracking
    progress = Column(Integer, default=0)  # 0-100 percentage
    total_pages_discovered = Column(Integer, default=0)
    total_pages_crawled = Column(Integer, default=0)
    total_pages_failed = Column(Integer, default=0)
    total_pages_skipped = Column(Integer, default=0)
    
    # Results Summary
    total_internal_links = Column(Integer, default=0)
    total_external_links = Column(Integer, default=0)
    total_issues_found = Column(Integer, default=0)
    
    # Error Tracking
    error_message = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    
    # Queue Management
    queue_name = Column(String(100), nullable=True)
    worker_id = Column(String(100), nullable=True)
    
    # Tenant & Project
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = relationship("Project", back_populates="crawl_jobs")
    pages = relationship("CrawlPage", back_populates="crawl_job", cascade="all, delete-orphan", lazy="dynamic")
    errors = relationship("CrawlError", back_populates="crawl_job", cascade="all, delete-orphan")
    logs = relationship("CrawlLog", back_populates="crawl_job", cascade="all, delete-orphan", order_by="CrawlLog.created_at")
    
    # Indexes
    __table_args__ = (
        Index('ix_crawl_jobs_tenant_status', 'tenant_id', 'status'),
        Index('ix_crawl_jobs_created', 'created_at', postgresql_using='brin'),
    )
    
    def __repr__(self):
        return f"<CrawlJob {self.id} - {self.url} - {self.status}>"
    
    @property
    def is_active(self) -> bool:
        """Check if crawl is actively running or queued"""
        return self.status in [CrawlStatus.pending, CrawlStatus.queued, CrawlStatus.running]


class CrawlPage(Base):
    """Crawled page data model - detailed SEO data for each page"""
    
    __tablename__ = "crawl_pages"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign Key
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    
    # URL Information
    url = Column(String(2048), nullable=False, index=True)
    normalized_url = Column(String(2048), nullable=True, index=True)
    final_url = Column(String(2048), nullable=True)  # After redirects
    
    # HTTP Response
    status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    content_type = Column(String(255), nullable=True)
    content_length = Column(BigInteger, nullable=True)
    
    # Redirect Information
    redirect_count = Column(Integer, default=0)
    redirect_chain = Column(JSON, nullable=True)  # Array of redirect URLs
    
    # Page Content Analysis
    title = Column(String(1000), nullable=True)
    title_length = Column(Integer, nullable=True)
    meta_description = Column(Text, nullable=True)
    meta_description_length = Column(Integer, nullable=True)
    
    # Headings
    h1 = Column(JSON, nullable=True)  # Array of H1 texts
    h2 = Column(JSON, nullable=True)  # Array of H2 texts
    h3 = Column(JSON, nullable=True)  # Array of H3 texts
    h4 = Column(JSON, nullable=True)  # Array of H4 texts
    h5 = Column(JSON, nullable=True)  # Array of H5 texts
    h6 = Column(JSON, nullable=True)  # Array of H6 texts
    heading_count = Column(Integer, default=0)
    
    # Content Metrics
    word_count = Column(Integer, default=0)
    text_content = Column(Text, nullable=True)  # Extracted text content
    content_hash = Column(String(64), nullable=True, index=True)  # For duplicate detection
    
    # Link Analysis
    internal_links = Column(Integer, default=0)
    external_links = Column(Integer, default=0)
    total_links = Column(Integer, default=0)
    internal_link_urls = Column(JSON, nullable=True)  # Array of internal URLs
    external_link_urls = Column(JSON, nullable=True)  # Array of external URLs
    
    # Canonical & Meta
    canonical_url = Column(String(2048), nullable=True)
    canonical_url_normalized = Column(String(2048), nullable=True)
    robots_meta = Column(String(255), nullable=True)
    noindex = Column(Boolean, default=False)
    nofollow = Column(Boolean, default=False)
    
    # Open Graph Tags
    og_title = Column(String(1000), nullable=True)
    og_description = Column(Text, nullable=True)
    og_image = Column(String(2048), nullable=True)
    og_type = Column(String(100), nullable=True)
    og_url = Column(String(2048), nullable=True)
    has_og_tags = Column(Boolean, default=False)
    
    # Twitter Card
    twitter_card = Column(String(100), nullable=True)
    twitter_title = Column(String(1000), nullable=True)
    twitter_description = Column(Text, nullable=True)
    twitter_image = Column(String(2048), nullable=True)
    has_twitter_card = Column(Boolean, default=False)
    
    # Schema.org Markup
    schema_markup = Column(JSONB, nullable=True)
    schema_types = Column(JSON, nullable=True)  # Array of schema types found
    has_schema_markup = Column(Boolean, default=False)
    
    # Image Analysis
    total_images = Column(Integer, default=0)
    images_with_alt = Column(Integer, default=0)
    images_without_alt = Column(Integer, default=0)
    image_alt_texts = Column(JSON, nullable=True)  # Array of alt texts
    
    # Page Speed Metrics (placeholders for real metrics)
    load_time_ms = Column(Float, nullable=True)
    first_contentful_paint_ms = Column(Float, nullable=True)
    largest_contentful_paint_ms = Column(Float, nullable=True)
    time_to_interactive_ms = Column(Float, nullable=True)
    cumulative_layout_shift = Column(Float, nullable=True)
    first_input_delay_ms = Column(Float, nullable=True)
    
    # Mobile Friendliness
    is_mobile_friendly = Column(Boolean, nullable=True)
    viewport_meta = Column(String(255), nullable=True)
    
    # Language & Localization
    language = Column(String(10), nullable=True)
    hreflang_tags = Column(JSON, nullable=True)  # Array of hreflang values
    
    # Issues Found
    issues = Column(JSON, nullable=True)  # Array of issue objects
    issue_count = Column(Integer, default=0)
    critical_issues = Column(Integer, default=0)
    warning_issues = Column(Integer, default=0)
    
    # Crawl Metadata
    depth = Column(Integer, default=0)  # Depth from start URL
    crawl_order = Column(Integer, default=0)  # Order in which page was crawled
    retry_count = Column(Integer, default=0)
    
    # Timestamps
    crawled_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    crawl_job = relationship("CrawlJob", back_populates="pages")
    links = relationship("CrawlLink", back_populates="source_page", cascade="all, delete-orphan", foreign_keys="CrawlLink.source_page_id")
    
    # Indexes
    __table_args__ = (
        Index('ix_crawl_pages_url_crawl', 'url', 'crawl_job_id'),
        Index('ix_crawl_pages_status', 'status_code'),
        Index('ix_crawl_pages_crawled', 'crawled_at', postgresql_using='brin'),
    )
    
    def __repr__(self):
        return f"<CrawlPage {self.url} - {self.status_code}>"


class CrawlLink(Base):
    """Individual link data model for detailed link analysis"""
    
    __tablename__ = "crawl_links"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign Keys
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    source_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=False, index=True)
    
    # Link Information
    url = Column(String(2048), nullable=False, index=True)
    normalized_url = Column(String(2048), nullable=True)
    link_text = Column(String(500), nullable=True)
    link_type = Column(String(20), nullable=True)  # 'internal' or 'external'
    
    # Link Attributes
    rel_attribute = Column(String(255), nullable=True)
    is_nofollow = Column(Boolean, default=False)
    is_sponsored = Column(Boolean, default=False)
    is_ugc = Column(Boolean, default=False)
    target_attribute = Column(String(50), nullable=True)
    
    # Link Context
    surrounding_text = Column(Text, nullable=True)
    link_position = Column(String(50), nullable=True)  # header, nav, content, footer, sidebar
    
    # HTTP Status (for internal links)
    status_code = Column(Integer, nullable=True)
    is_broken = Column(Boolean, default=False)
    response_time_ms = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    crawl_job = relationship("CrawlJob")
    source_page = relationship("CrawlPage", back_populates="links", foreign_keys=[source_page_id])
    
    # Indexes
    __table_args__ = (
        Index('ix_crawl_links_type_status', 'link_type', 'is_broken'),
    )
    
    def __repr__(self):
        return f"<CrawlLink {self.url}>"


class CrawlError(Base):
    """Crawl error tracking model"""
    
    __tablename__ = "crawl_errors"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign Key
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    
    # Error Details
    error_type = Column(String(100), nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)
    
    # Context
    url = Column(String(2048), nullable=True)
    page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Stack Trace (for debugging)
    stack_trace = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    crawl_job = relationship("CrawlJob", back_populates="errors")
    
    # Indexes
    __table_args__ = (
        Index('ix_crawl_errors_type_created', 'error_type', 'created_at'),
    )
    
    def __repr__(self):
        return f"<CrawlError {self.error_type} - {self.url}>"


class CrawlLog(Base):
    """Crawl activity log model"""
    
    __tablename__ = "crawl_logs"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign Key
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    
    # Log Details
    level = Column(String(20), nullable=False, index=True)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    message = Column(Text, nullable=False)
    module = Column(String(100), nullable=True)
    function = Column(String(100), nullable=True)
    
    # Context
    url = Column(String(2048), nullable=True)
    page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=True)
    
    # Additional Data
    extra_data = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    crawl_job = relationship("CrawlJob", back_populates="logs")
    
    # Indexes
    __table_args__ = (
        Index('ix_crawl_logs_level_created', 'level', 'created_at'),
        Index('ix_crawl_logs_created', 'created_at', postgresql_using='brin'),
    )
    
    def __repr__(self):
        return f"<CrawlLog {self.level} - {self.message[:50]}>"


class RobotsTxtCache(Base):
    """Cache for robots.txt files to avoid repeated fetching"""
    
    __tablename__ = "robots_txt_cache"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Domain
    domain = Column(String(255), nullable=False, unique=True, index=True)
    
    # Robots.txt Content
    content = Column(Text, nullable=True)
    parsed_rules = Column(JSONB, nullable=True)
    
    # Sitemap URLs found
    sitemap_urls = Column(JSON, nullable=True)
    
    # Cache Validity
    fetched_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_valid = Column(Boolean, default=True)
    
    # Error Tracking
    fetch_error = Column(Text, nullable=True)
    fetch_attempts = Column(Integer, default=0)
    
    def __repr__(self):
        return f"<RobotsTxtCache {self.domain}>"


class SitemapCache(Base):
    """Cache for sitemap.xml files"""
    
    __tablename__ = "sitemap_cache"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Sitemap URL
    url = Column(String(2048), nullable=False, unique=True, index=True)
    
    # Parent sitemap (for sitemap index files)
    parent_sitemap_id = Column(UUID(as_uuid=True), ForeignKey("sitemap_cache.id"), nullable=True)
    
    # Sitemap Type
    sitemap_type = Column(String(20), default="urlset")  # 'urlset' or 'sitemapindex'
    
    # URLs in sitemap
    urls = Column(JSON, nullable=True)  # Array of URL objects with loc, lastmod, changefreq, priority
    
    # Child sitemaps (for sitemap index)
    child_sitemaps = Column(JSON, nullable=True)  # Array of child sitemap URLs
    
    # Cache Validity
    fetched_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_valid = Column(Boolean, default=True)
    
    # Error Tracking
    fetch_error = Column(Text, nullable=True)
    
    def __repr__(self):
        return f"<SitemapCache {self.url}>"

"""
SEO Agent SaaS - Enhanced Crawl Service
Production-grade crawl service with distributed queue support
"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
import structlog

from app.models.crawl import (
    CrawlJob, CrawlStatus, CrawlPage, CrawlLink, CrawlError, CrawlLog,
    RobotsTxtCache, SitemapCache, CrawlPriority
)
from app.crawler.queue_manager import CrawlQueueManager, CrawlTask, TaskPriority
from app.core.config import settings
from app.core.url_utils import URLNormalizer
from app.repositories.crawl import CrawlRepository

logger = structlog.get_logger(__name__)


class CrawlService:
    """
    Enhanced crawl service for managing distributed crawl operations.
    Handles job creation, progress tracking, and result retrieval.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = CrawlRepository(db)
    
    # ========== Job Management ==========
    
    async def create_crawl_job(
        self,
        url: str,
        tenant_id: UUID,
        max_pages: int = 100,
        depth: int = 2,
        project_id: Optional[UUID] = None,
        name: Optional[str] = None,
        priority: CrawlPriority = CrawlPriority.normal,
        # Crawl settings
        crawl_delay: float = 1.0,
        request_timeout: int = 30,
        max_retries: int = 3,
        # Domain restrictions
        allowed_domains: Optional[List[str]] = None,
        excluded_paths: Optional[List[str]] = None,
        follow_subdomains: bool = False,
        # Rate limiting
        rate_limit_requests: int = 10,
        rate_limit_window: int = 60,
        # Robots & Sitemap
        respect_robots_txt: bool = True,
        sitemap_urls: Optional[List[str]] = None,
        # Browser settings
        render_javascript: bool = True,
        wait_for_selector: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> CrawlJob:
        """Create a new crawl job with comprehensive settings"""
        
        # Normalize the start URL
        normalized_url = URLNormalizer.normalize_url(url)
        if not normalized_url:
            raise ValueError(f"Invalid URL: {url}")
        
        # Set default allowed domains if not specified
        if not allowed_domains and not follow_subdomains:
            allowed_domains = [URLNormalizer.get_domain(normalized_url)]
        
        crawl_job = await self.repository.create_job(
            url=normalized_url,
            name=name,
            status=CrawlStatus.pending,
            priority=priority,
            max_pages=max_pages,
            max_depth=depth,
            crawl_delay=crawl_delay,
            request_timeout=request_timeout,
            max_retries=max_retries,
            allowed_domains=allowed_domains,
            excluded_paths=excluded_paths,
            follow_subdomains=follow_subdomains,
            rate_limit_requests=rate_limit_requests,
            rate_limit_window=rate_limit_window,
            respect_robots_txt=respect_robots_txt,
            sitemap_urls=sitemap_urls,
            render_javascript=render_javascript,
            wait_for_selector=wait_for_selector,
            user_agent=user_agent,
            project_id=project_id,
            tenant_id=tenant_id,
        )

        await self.db.commit()
        await self.db.refresh(crawl_job)
        
        logger.info(
            f"Created crawl job: {crawl_job.id}",
            extra={
                "job_id": str(crawl_job.id),
                "url": normalized_url,
                "tenant_id": str(tenant_id),
                "max_pages": max_pages,
                "depth": depth,
            }
        )
        
        return crawl_job

    async def enqueue_crawl_job(
        self,
        job_id: UUID,
        tenant_id: Optional[UUID] = None,
        queue_name: str = "default",
    ) -> CrawlJob:
        """Queue the first crawl task in Redis for distributed workers."""
        job = await self.get_crawl_job(job_id, tenant_id)
        if not job:
            raise ValueError("Crawl job not found")

        priority_map = {
            CrawlPriority.low: TaskPriority.LOW,
            CrawlPriority.normal: TaskPriority.NORMAL,
            CrawlPriority.high: TaskPriority.HIGH,
            CrawlPriority.critical: TaskPriority.CRITICAL,
        }
        metadata = {
            "tenant_id": str(job.tenant_id),
            "project_id": str(job.project_id) if job.project_id else None,
            "start_url": job.url,
            "max_pages": job.max_pages,
            "max_depth": job.max_depth,
            "allowed_domains": job.allowed_domains or [],
            "excluded_paths": job.excluded_paths or [],
            "follow_subdomains": job.follow_subdomains,
            "respect_robots_txt": job.respect_robots_txt,
            "sitemap_urls": job.sitemap_urls or [],
            "render_javascript": job.render_javascript,
            "request_timeout": job.request_timeout,
            "crawl_delay": job.crawl_delay,
            "user_agent": job.user_agent,
            "max_retries": job.max_retries,
        }
        job_priority = job.priority
        if isinstance(job_priority, str):
            job_priority = CrawlPriority(job_priority)

        task = CrawlTask(
            crawl_job_id=str(job.id),
            url=job.url,
            depth=0,
            priority=priority_map.get(job_priority, TaskPriority.NORMAL),
            max_retries=job.max_retries,
            metadata=metadata,
        )

        queue = CrawlQueueManager(redis_url=settings.get_redis_url, queue_name=queue_name)
        try:
            await queue.connect()
            await queue.enqueue_task(task)
        except Exception as exc:
            await self.repository.set_job_status(job, CrawlStatus.failed, error_message=str(exc))
            await self.db.commit()
            logger.error("Failed to enqueue crawl job", job_id=str(job.id), error=str(exc))
            raise
        finally:
            await queue.disconnect()

        job.status = CrawlStatus.queued
        job.queue_name = queue_name
        job.total_pages_discovered = max(job.total_pages_discovered or 0, 1)
        await self.db.commit()
        await self.db.refresh(job)
        logger.info("Queued crawl job", job_id=str(job.id), queue_name=queue_name)
        return job

    async def cancel_queued_tasks(
        self,
        job_id: UUID,
        queue_name: str = "default",
    ) -> int:
        """Cancel all queued/processing Redis tasks for a crawl job."""
        queue = CrawlQueueManager(redis_url=settings.get_redis_url, queue_name=queue_name)
        try:
            await queue.connect()
            return await queue.cancel_job_tasks(str(job_id))
        finally:
            await queue.disconnect()
    
    async def get_crawl_job(
        self,
        job_id: UUID,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[CrawlJob]:
        """Get a crawl job by ID"""
        query = select(CrawlJob).where(CrawlJob.id == job_id)
        if tenant_id:
            query = query.where(CrawlJob.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def update_crawl_status(
        self,
        job_id: UUID,
        status: CrawlStatus,
        error_message: Optional[str] = None,
    ):
        """Update crawl job status"""
        await self.db.execute(
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(
                status=status,
                error_message=error_message,
                completed_at=datetime.utcnow() if status in [
                    CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled
                ] else None,
            )
        )
        await self.db.commit()
    
    async def start_crawl(self, job_id: UUID) -> Optional[CrawlJob]:
        """Mark a crawl job as started"""
        job = await self.get_crawl_job(job_id)
        if not job:
            return None
        
        if job.status != CrawlStatus.pending:
            logger.warning(f"Cannot start job {job_id}: status is {job.status}")
            return None
        
        job.status = CrawlStatus.running
        job.started_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(f"Started crawl job: {job_id}")
        return job
    
    async def pause_crawl(self, job_id: UUID) -> Optional[CrawlJob]:
        """Pause a running crawl job"""
        job = await self.get_crawl_job(job_id)
        if not job or job.status != CrawlStatus.running:
            return None
        
        job.status = CrawlStatus.paused
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(f"Paused crawl job: {job_id}")
        return job
    
    async def resume_crawl(self, job_id: UUID) -> Optional[CrawlJob]:
        """Resume a paused crawl job"""
        job = await self.get_crawl_job(job_id)
        if not job or job.status != CrawlStatus.paused:
            return None
        
        job.status = CrawlStatus.running
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(f"Resumed crawl job: {job_id}")
        return job
    
    async def cancel_crawl(self, job_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[CrawlJob]:
        """Cancel a crawl job"""
        job = await self.get_crawl_job(job_id, tenant_id)
        if not job:
            return None
        
        if job.status in [CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled]:
            return job
        
        job.status = CrawlStatus.cancelled
        job.completed_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(f"Cancelled crawl job: {job_id}")
        return job
    
    # ========== Progress Tracking ==========
    
    async def update_crawl_progress(
        self,
        job_id: UUID,
        pages_crawled: Optional[int] = None,
        pages_failed: Optional[int] = None,
        pages_skipped: Optional[int] = None,
        pages_discovered: Optional[int] = None,
        progress: Optional[int] = None,
        internal_links: Optional[int] = None,
        external_links: Optional[int] = None,
        issues_found: Optional[int] = None,
    ):
        """Update crawl job progress"""
        update_data = {}
        if pages_crawled is not None:
            update_data["total_pages_crawled"] = pages_crawled
        if pages_failed is not None:
            update_data["total_pages_failed"] = pages_failed
        if pages_skipped is not None:
            update_data["total_pages_skipped"] = pages_skipped
        if pages_discovered is not None:
            update_data["total_pages_discovered"] = pages_discovered
        if progress is not None:
            update_data["progress"] = progress
        if internal_links is not None:
            update_data["total_internal_links"] = internal_links
        if external_links is not None:
            update_data["total_external_links"] = external_links
        if issues_found is not None:
            update_data["total_issues_found"] = issues_found
        
        if update_data:
            await self.db.execute(
                update(CrawlJob)
                .where(CrawlJob.id == job_id)
                .values(**update_data)
            )
            await self.db.commit()
    
    async def get_crawl_progress(self, job_id: UUID) -> Dict[str, Any]:
        """Get detailed progress for a crawl job"""
        job = await self.get_crawl_job(job_id)
        if not job:
            return {}
        
        # Get page counts
        total_pages = await self.db.execute(
            select(CrawlPage).where(CrawlPage.crawl_job_id == job_id)
        )
        pages = total_pages.scalars().all()
        
        # Get issue summary
        issues_query = await self.db.execute(
            select(CrawlPage.issue_count).where(CrawlPage.crawl_job_id == job_id)
        )
        issue_counts = issues_query.scalars().all()
        
        return {
            "job_id": str(job.id),
            "status": job.status.value,
            "progress": job.progress,
            "url": job.url,
            "total_pages_crawled": job.total_pages_crawled,
            "total_pages_failed": job.total_pages_failed,
            "total_pages_skipped": job.total_pages_skipped,
            "total_pages_discovered": job.total_pages_discovered,
            "max_pages": job.max_pages,
            "total_internal_links": job.total_internal_links,
            "total_external_links": job.total_external_links,
            "total_issues_found": job.total_issues_found,
            "critical_issues": sum(p.critical_issues for p in pages),
            "warning_issues": sum(p.warning_issues for p in pages),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
    
    # ========== Page Management ==========
    
    async def save_crawled_page(
        self,
        job_id: UUID,
        page_data: Dict[str, Any],
        crawl_order: int = 0,
        depth: int = 0,
    ) -> CrawlPage:
        """Save a crawled page's data to the database"""
        
        # Check for existing page
        existing = await self.db.execute(
            select(CrawlPage).where(
                CrawlPage.crawl_job_id == job_id,
                CrawlPage.url == page_data.get("url")
            )
        )
        page = existing.scalar_one_or_none()
        
        if not page:
            page = CrawlPage(
                crawl_job_id=job_id,
                url=page_data.get("url"),
            )
            self.db.add(page)
        
        # Update all fields from page_data
        for key, value in page_data.items():
            if hasattr(page, key):
                setattr(page, key, value)
        
        page.crawl_order = crawl_order
        page.depth = depth
        page.crawled_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(page)
        
        return page
    
    async def save_crawl_link(
        self,
        job_id: UUID,
        source_page_id: UUID,
        link_data: Dict[str, Any],
    ) -> CrawlLink:
        """Save a link found during crawling"""
        link = CrawlLink(
            crawl_job_id=job_id,
            source_page_id=source_page_id,
            url=link_data.get("url"),
            normalized_url=link_data.get("normalized_url"),
            link_text=link_data.get("text"),
            link_type=link_data.get("link_type", "internal"),
            rel_attribute=link_data.get("rel"),
            is_nofollow=link_data.get("is_nofollow", False),
            is_sponsored=link_data.get("is_sponsored", False),
            is_ugc=link_data.get("is_ugc", False),
            target_attribute=link_data.get("target"),
            status_code=link_data.get("status_code"),
            is_broken=link_data.get("is_broken", False),
            response_time_ms=link_data.get("response_time_ms"),
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        return link
    
    async def save_crawl_error(
        self,
        job_id: UUID,
        error_type: str,
        error_message: str,
        url: Optional[str] = None,
        page_id: Optional[UUID] = None,
        error_code: Optional[str] = None,
        stack_trace: Optional[str] = None,
    ):
        """Save a crawl error to the database"""
        error = CrawlError(
            crawl_job_id=job_id,
            error_type=error_type,
            error_message=error_message,
            url=url,
            page_id=page_id,
            error_code=error_code,
            stack_trace=stack_trace,
        )
        self.db.add(error)
        await self.db.commit()
    
    async def save_crawl_log(
        self,
        job_id: UUID,
        level: str,
        message: str,
        url: Optional[str] = None,
        page_id: Optional[UUID] = None,
        module: Optional[str] = None,
        function: Optional[str] = None,
        extra_data: Optional[Dict] = None,
    ):
        """Save a crawl log entry"""
        log = CrawlLog(
            crawl_job_id=job_id,
            level=level,
            message=message,
            url=url,
            page_id=page_id,
            module=module,
            function=function,
            extra_data=extra_data,
        )
        self.db.add(log)
        await self.db.commit()
    
    # ========== Results Retrieval ==========
    
    async def get_crawl_pages(
        self,
        job_id: UUID,
        limit: int = 100,
        offset: int = 0,
        status_code: Optional[int] = None,
        has_issues: bool = False,
    ) -> List[CrawlPage]:
        """Get pages from a crawl job with optional filtering"""
        query = select(CrawlPage).where(CrawlPage.crawl_job_id == job_id)
        
        if status_code is not None:
            query = query.where(CrawlPage.status_code == status_code)
        if has_issues:
            query = query.where(CrawlPage.issue_count > 0)
        
        query = query.order_by(CrawlPage.crawled_at.desc()).offset(offset).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_crawl_links(
        self,
        job_id: UUID,
        link_type: Optional[str] = None,
        is_broken: bool = False,
        limit: int = 100,
    ) -> List[CrawlLink]:
        """Get links from a crawl job"""
        query = select(CrawlLink).where(CrawlLink.crawl_job_id == job_id)
        
        if link_type:
            query = query.where(CrawlLink.link_type == link_type)
        if is_broken:
            query = query.where(CrawlLink.is_broken == True)
        
        query = query.limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_crawl_errors(
        self,
        job_id: UUID,
        error_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[CrawlError]:
        """Get errors from a crawl job"""
        query = select(CrawlError).where(CrawlError.crawl_job_id == job_id)
        
        if error_type:
            query = query.where(CrawlError.error_type == error_type)
        
        query = query.order_by(CrawlError.created_at.desc()).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_crawl_summary(self, job_id: UUID) -> Dict[str, Any]:
        """Get a summary of crawl results"""
        job = await self.get_crawl_job(job_id)
        if not job:
            return {}
        
        # Count pages by status
        status_counts = {}
        issue_counts = {"critical": 0, "warning": 0, "info": 0}
        
        pages_query = await self.db.execute(
            select(CrawlPage.status_code, CrawlPage.issue_count, CrawlPage.critical_issues, CrawlPage.warning_issues)
            .where(CrawlPage.crawl_job_id == job_id)
        )
        
        for row in pages_query.all():
            status = row[0]
            if status is not None:
                status_counts[status] = status_counts.get(status, 0) + 1
            issue_counts["critical"] += row[2] or 0
            issue_counts["warning"] += row[3] or 0
            if row[1] and row[1] > (row[2] or 0) + (row[3] or 0):
                issue_counts["info"] += row[1] - (row[2] or 0) - (row[3] or 0)
        issue_counts["total"] = (
            issue_counts["critical"] + issue_counts["warning"] + issue_counts["info"]
        )
        
        return {
            "job_id": job.id,
            "url": job.url,
            "status": job.status.value,
            "total_pages": job.total_pages_crawled,
            "status_code_distribution": status_counts,
            "issue_summary": issue_counts,
            "total_internal_links": job.total_internal_links,
            "total_external_links": job.total_external_links,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "duration_seconds": (
                (job.completed_at - job.started_at).total_seconds()
                if job.started_at and job.completed_at
                else None
            ),
        }
    
    # ========== Tenant Operations ==========
    
    async def get_tenant_crawls(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        status: Optional[CrawlStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CrawlJob]:
        """Get all crawl jobs for a tenant"""
        query = select(CrawlJob).where(CrawlJob.tenant_id == tenant_id)
        
        if project_id:
            query = query.where(CrawlJob.project_id == project_id)
        if status:
            query = query.where(CrawlJob.status == status)
        
        query = query.order_by(CrawlJob.created_at.desc()).offset(offset).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_active_crawls(self, tenant_id: UUID) -> List[CrawlJob]:
        """Get all active crawl jobs for a tenant"""
        result = await self.db.execute(
            select(CrawlJob).where(
                CrawlJob.tenant_id == tenant_id,
                CrawlJob.status.in_([CrawlStatus.pending, CrawlStatus.queued, CrawlStatus.running])
            )
        )
        return result.scalars().all()
    
    # ========== Robots.txt & Sitemap Cache ==========
    
    async def cache_robots_txt(
        self,
        domain: str,
        content: str,
        parsed_rules: Dict,
        sitemap_urls: List[str],
        is_valid: bool = True,
    ) -> RobotsTxtCache:
        """Cache robots.txt content"""
        # Check for existing cache
        existing = await self.db.execute(
            select(RobotsTxtCache).where(RobotsTxtCache.domain == domain)
        )
        cache = existing.scalar_one_or_none()
        
        if not cache:
            cache = RobotsTxtCache(domain=domain)
            self.db.add(cache)
        
        cache.content = content
        cache.parsed_rules = parsed_rules
        cache.sitemap_urls = sitemap_urls
        cache.is_valid = is_valid
        cache.fetched_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(cache)
        return cache
    
    async def get_robots_txt_cache(self, domain: str) -> Optional[RobotsTxtCache]:
        """Get cached robots.txt"""
        result = await self.db.execute(
            select(RobotsTxtCache).where(RobotsTxtCache.domain == domain)
        )
        return result.scalar_one_or_none()
    
    async def cache_sitemap(
        self,
        url: str,
        sitemap_type: str,
        urls: Optional[List] = None,
        child_sitemaps: Optional[List] = None,
        parent_sitemap_id: Optional[UUID] = None,
    ) -> SitemapCache:
        """Cache sitemap content"""
        existing = await self.db.execute(
            select(SitemapCache).where(SitemapCache.url == url)
        )
        cache = existing.scalar_one_or_none()
        
        if not cache:
            cache = SitemapCache(url=url, sitemap_type=sitemap_type)
            self.db.add(cache)
        
        cache.urls = urls
        cache.child_sitemaps = child_sitemaps
        cache.parent_sitemap_id = parent_sitemap_id
        cache.fetched_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(cache)
        return cache
    
    # ========== Legacy Methods (for backward compatibility) ==========
    
    async def execute_crawl(
        self,
        crawl_id: UUID,
        url: str,
        max_pages: int = 100,
        depth: int = 2,
    ):
        """
        Execute a crawl job (legacy method for backward compatibility).
        Delegates to the Redis queue used by the crawler workers.
        """
        logger.warning("execute_crawl is deprecated. Use enqueue_crawl_job instead.")

        try:
            return await self.enqueue_crawl_job(crawl_id)
        except Exception as e:
            logger.error(f"Crawl failed for {url}: {e}")
            crawl = await self.db.get(CrawlJob, crawl_id)
            if not crawl:
                return None
            crawl.status = CrawlStatus.failed
            crawl.error_message = str(e)
            crawl.completed_at = datetime.utcnow()
            await self.db.commit()
            return crawl

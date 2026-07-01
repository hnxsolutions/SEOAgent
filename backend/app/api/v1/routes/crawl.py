"""
SEO Agent SaaS - Enhanced Web Crawling Routes
Production-grade API endpoints for crawl management
"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.config import settings
from app.core.redis import REDIS_UNAVAILABLE_MESSAGE, RedisUnavailableError, get_redis
from app.crawler.queue_manager import CrawlQueueManager
from app.schemas.crawl import (
    CrawlRequest,
    CrawlJobResponse,
    CrawlStatusResponse,
    CrawlProgressResponse,
    CrawlResultsResponse,
    CrawlSummaryResponse,
    CrawlListResponse,
    CrawlPageSummary,
    CrawlErrorSummary,
    PauseCrawlRequest,
    ResumeCrawlRequest,
    CancelCrawlRequest,
    ExportCrawlDataRequest,
    QueueStatsResponse,
)
from app.services.crawl import CrawlService
from app.models.crawl import CrawlStatus, CrawlPriority
from app.core.security import get_current_user

logger = structlog.get_logger(__name__)

router = APIRouter()


# ========== Job Management ==========

@router.post("/start", response_model=CrawlJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_crawl(
    crawl_request: CrawlRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    """
    Start a new website crawl for SEO analysis.
    
    This creates a crawl job and queues it for processing.
    The crawl will be executed by distributed workers.
    """
    try:
        crawl_service = CrawlService(db)
        
        # Map priority string to enum
        priority_map = {
            "low": CrawlPriority.low,
            "normal": CrawlPriority.normal,
            "high": CrawlPriority.high,
            "critical": CrawlPriority.critical,
        }
        priority = priority_map.get(crawl_request.priority.lower(), CrawlPriority.normal)
        
        # Create crawl job
        crawl_job = await crawl_service.create_crawl_job(
            url=str(crawl_request.url),
            tenant_id=current_user["tenant_id"],
            project_id=crawl_request.project_id,
            name=crawl_request.name,
            max_pages=crawl_request.max_pages,
            depth=crawl_request.depth,
            priority=priority,
            crawl_delay=crawl_request.crawl_delay,
            request_timeout=crawl_request.request_timeout,
            max_retries=crawl_request.max_retries,
            allowed_domains=crawl_request.allowed_domains,
            excluded_paths=crawl_request.excluded_paths,
            follow_subdomains=crawl_request.follow_subdomains,
            rate_limit_requests=crawl_request.rate_limit_requests,
            rate_limit_window=crawl_request.rate_limit_window,
            respect_robots_txt=crawl_request.respect_robots_txt,
            sitemap_urls=crawl_request.sitemap_urls,
            render_javascript=crawl_request.render_javascript,
            wait_for_selector=crawl_request.wait_for_selector,
            user_agent=crawl_request.user_agent,
        )
        
        crawl_job = await crawl_service.enqueue_crawl_job(
            crawl_job.id,
            tenant_id=current_user["tenant_id"],
        )
        
        logger.info(
            f"Crawl job created: {crawl_job.id}",
            extra={
                "job_id": str(crawl_job.id),
                "url": str(crawl_request.url),
                "tenant_id": str(current_user["tenant_id"]),
            }
        )
        
        return crawl_job
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        if isinstance(e, RedisUnavailableError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=REDIS_UNAVAILABLE_MESSAGE,
            )
        logger.error("Failed to start crawl", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Crawler queue is unavailable",
        )


@router.post("/{crawl_id}/pause", response_model=CrawlJobResponse)
async def pause_crawl(
    crawl_id: UUID,
    pause_request: PauseCrawlRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Pause a running crawl job"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    if crawl.status != CrawlStatus.running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot pause crawl with status: {crawl.status.value}",
        )
    
    paused_crawl = await crawl_service.pause_crawl(crawl_id)
    
    logger.info(f"Crawl paused: {crawl_id}")
    return paused_crawl


@router.post("/{crawl_id}/resume", response_model=CrawlJobResponse)
async def resume_crawl(
    crawl_id: UUID,
    resume_request: ResumeCrawlRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    """Resume a paused crawl job"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    if crawl.status != CrawlStatus.paused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume crawl with status: {crawl.status.value}",
        )
    
    resumed_crawl = await crawl_service.resume_crawl(crawl_id)
    
    # Re-queue the crawl
    background_tasks.add_task(
        queue_crawl_job,
        str(crawl_id),
        crawl.url,
        crawl.max_pages,
        crawl.max_depth,
    )
    
    logger.info(f"Crawl resumed: {crawl_id}")
    return resumed_crawl


@router.post("/{crawl_id}/cancel", response_model=CrawlJobResponse)
async def cancel_crawl(
    crawl_id: UUID,
    cancel_request: CancelCrawlRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Cancel a crawl job"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    cancelled_crawl = await crawl_service.cancel_crawl(crawl_id, current_user["tenant_id"])
    try:
        await crawl_service.cancel_queued_tasks(crawl_id, queue_name=cancelled_crawl.queue_name or "default")
    except Exception as e:
        logger.warning("Failed to cancel queued crawl tasks", crawl_id=str(crawl_id), error=str(e))
    
    logger.info(f"Crawl cancelled: {crawl_id}")
    return cancelled_crawl


@router.get("/active")
async def get_active_crawls(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get all active crawl jobs"""
    crawl_service = CrawlService(db)
    
    active_crawls = await crawl_service.get_active_crawls(
        tenant_id=current_user["tenant_id"]
    )
    
    return {
        "active_crawls": active_crawls,
        "count": len(active_crawls),
    }


# ========== Status & Progress ==========

@router.get("/{crawl_id}/status", response_model=CrawlStatusResponse)
async def get_crawl_status(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get detailed crawl job status and progress"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    # Get progress
    progress = await crawl_service.get_crawl_progress(crawl_id)
    
    # Get recent pages
    recent_pages = await crawl_service.get_crawl_pages(crawl_id, limit=10)
    
    # Get recent errors
    recent_errors = await crawl_service.get_crawl_errors(crawl_id, limit=10)
    
    queue_stats = {}
    try:
        queue = CrawlQueueManager(redis_url=settings.get_redis_url, queue_name=crawl.queue_name or "default")
        await queue.connect()
        queue_stats = await queue.get_job_stats(str(crawl_id))
        await queue.disconnect()
    except Exception as e:
        logger.debug("Queue stats unavailable", crawl_id=str(crawl_id), error=str(e))
    
    return CrawlStatusResponse(
        job=crawl,
        progress=progress,
        stats=queue_stats,
        recent_pages=[CrawlPageSummary.model_validate(p) for p in recent_pages],
        recent_errors=[CrawlErrorSummary.model_validate(e) for e in recent_errors],
    )


@router.get("/{crawl_id}", response_model=CrawlStatusResponse)
async def get_crawl_status_legacy(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Backward-compatible crawl status endpoint."""
    return await get_crawl_status(crawl_id, current_user, db)


@router.get("/{crawl_id}/progress", response_model=CrawlProgressResponse)
async def get_crawl_progress(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get crawl progress details"""
    crawl_service = CrawlService(db)
    
    progress = await crawl_service.get_crawl_progress(crawl_id)
    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    return progress


# ========== Results ==========

@router.get("/{crawl_id}/results", response_model=CrawlResultsResponse)
async def get_crawl_results(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_code: Optional[int] = Query(None),
    has_issues: bool = Query(False),
):
    """Get crawl results with pagination"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    # Get pages
    pages = await crawl_service.get_crawl_pages(
        crawl_id,
        limit=limit,
        offset=offset,
        status_code=status_code,
        has_issues=has_issues,
    )
    
    # Get summary for totals
    summary = await crawl_service.get_crawl_summary(crawl_id)
    
    return CrawlResultsResponse(
        job_id=crawl_id,
        total_pages=crawl.total_pages_crawled,
        pages=[CrawlPageSummary.model_validate(p) for p in pages],
        total_issues=summary.get("issue_summary", {}).get("total", 0),
        critical_issues=summary.get("issue_summary", {}).get("critical", 0),
        warning_issues=summary.get("issue_summary", {}).get("warning", 0),
        limit=limit,
        offset=offset,
        has_more=crawl.total_pages_crawled > (offset + limit),
    )


@router.get("/{crawl_id}/summary", response_model=CrawlSummaryResponse)
async def get_crawl_summary(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get summary of crawl results"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    summary = await crawl_service.get_crawl_summary(crawl_id)
    return summary


@router.get("/{crawl_id}/pages", response_model=List[CrawlPageSummary])
async def get_crawl_pages(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_code: Optional[int] = Query(None),
    has_issues: bool = Query(False),
):
    """Get crawled pages for a crawl job."""
    crawl_service = CrawlService(db)

    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )

    pages = await crawl_service.get_crawl_pages(
        crawl_id,
        limit=limit,
        offset=offset,
        status_code=status_code,
        has_issues=has_issues,
    )
    return [CrawlPageSummary.model_validate(page) for page in pages]


@router.get("/{crawl_id}/pages/{page_id}")
async def get_page_details(
    crawl_id: UUID,
    page_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get detailed information about a specific crawled page"""
    from sqlalchemy import select
    from app.models.crawl import CrawlPage
    
    # Verify crawl belongs to tenant
    crawl_service = CrawlService(db)
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    # Get page
    result = await db.execute(
        select(CrawlPage).where(
            CrawlPage.id == page_id,
            CrawlPage.crawl_job_id == crawl_id,
        )
    )
    page = result.scalar_one_or_none()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page not found",
        )
    
    return page


@router.get("/{crawl_id}/links")
async def get_crawl_links(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    link_type: Optional[str] = Query(None),
    is_broken: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get links found during crawl"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    links = await crawl_service.get_crawl_links(
        crawl_id,
        link_type=link_type,
        is_broken=is_broken,
        limit=limit,
    )
    
    return links


@router.get("/{crawl_id}/errors")
async def get_crawl_errors(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    error_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get errors encountered during crawl"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    errors = await crawl_service.get_crawl_errors(
        crawl_id,
        error_type=error_type,
        limit=limit,
    )
    
    return errors


# ========== List Operations ==========

@router.get("/", response_model=CrawlListResponse)
async def list_crawls(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all crawl jobs for current tenant"""
    crawl_service = CrawlService(db)
    
    # Map status string to enum
    crawl_status = None
    if status_filter:
        try:
            crawl_status = CrawlStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )
    
    crawls = await crawl_service.get_tenant_crawls(
        tenant_id=current_user["tenant_id"],
        project_id=project_id,
        status=crawl_status,
        limit=limit,
        offset=offset,
    )
    
    # Get total count
    all_crawls = await crawl_service.get_tenant_crawls(
        tenant_id=current_user["tenant_id"],
        project_id=project_id,
        status=crawl_status,
    )
    
    return CrawlListResponse(
        crawls=crawls,
        total=len(all_crawls),
        limit=limit,
        offset=offset,
        has_more=len(all_crawls) > (offset + limit),
    )


# ========== Export ==========

@router.post("/{crawl_id}/export")
async def export_crawl_data(
    crawl_id: UUID,
    export_request: ExportCrawlDataRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Export crawl data in various formats"""
    crawl_service = CrawlService(db)
    
    crawl = await crawl_service.get_crawl_job(crawl_id, current_user["tenant_id"])
    if not crawl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crawl job not found",
        )
    
    # Generate export based on format
    if export_request.format == "json":
        return await export_as_json(crawl_id, export_request, crawl_service)
    elif export_request.format == "csv":
        return await export_as_csv(crawl_id, export_request, crawl_service)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format: {export_request.format}",
        )


async def export_as_json(crawl_id: UUID, request: ExportCrawlDataRequest, service: CrawlService):
    """Export crawl data as JSON"""
    pages = await service.get_crawl_pages(crawl_id)
    
    data = {
        "crawl_id": str(crawl_id),
        "exported_at": datetime.utcnow().isoformat(),
        "pages": [page.to_dict() if hasattr(page, 'to_dict') else str(page) for page in pages],
    }
    
    return data


async def export_as_csv(crawl_id: UUID, request: ExportCrawlDataRequest, service: CrawlService):
    """Export crawl data as CSV"""
    pages = await service.get_crawl_pages(crawl_id)
    
    def generate_csv():
        # Header
        yield "URL,Status Code,Title,Word Count,Internal Links,External Links,Issues\n"
        
        for page in pages:
            yield f'"{page.url}",{page.status_code or ""},"{page.title or ""}",{page.word_count},{page.internal_links},{page.external_links},{page.issue_count}\n'
    
    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=crawl_{crawl_id}.csv"},
    )


# ========== Queue Management ==========

@router.get("/queue/stats", response_model=QueueStatsResponse)
async def get_queue_stats(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get queue statistics"""
    try:
        queue = CrawlQueueManager(redis_url=settings.get_redis_url, queue_name="default")
        await queue.connect()
        stats = await queue.get_queue_stats()
        await queue.disconnect()
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        if not settings.REDIS_REQUIRED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=REDIS_UNAVAILABLE_MESSAGE,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ========== Background Task Helpers ==========

async def queue_crawl_job(
    job_id: str,
    url: str,
    max_pages: int,
    depth: int,
):
    """Queue a crawl job for processing"""
    try:
        from app.core.database import get_db_session
        from app.services.crawl import CrawlService
        
        db = get_db_session()
        try:
            crawl_service = CrawlService(db)
            await crawl_service.enqueue_crawl_job(UUID(job_id))
        finally:
            await db.close()
            
    except Exception as e:
        logger.error(f"Failed to queue crawl job {job_id}: {e}")

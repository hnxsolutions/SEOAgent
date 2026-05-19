"""
SEO Agent SaaS - Crawl Worker
Distributed worker for processing crawl tasks from the queue
"""
import asyncio
import argparse
import os
import traceback
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from contextlib import asynccontextmanager
from uuid import UUID

import structlog

from app.crawler.engine import CrawlerEngine, PageData
from app.crawler.queue_manager import CrawlQueueManager, CrawlTask, TaskStatus
from app.crawler.rate_limiter import CrawlRateLimiter
from app.core.config import settings
from app.core.database import async_session_maker
from app.models.crawl import CrawlStatus
from app.repositories.crawl import CrawlRepository

logger = structlog.get_logger(__name__)


def _safe_log_text(value: Any) -> str:
    """Keep Windows console logging from crashing on non-encodable error text."""
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


class CrawlWorker:
    """
    Worker that processes crawl tasks from the Redis queue.
    Supports graceful shutdown, heartbeats, and error recovery.
    """
    
    def __init__(
        self,
        worker_id: Optional[str] = None,
        queue_name: str = "default",
        redis_url: Optional[str] = None,
        max_concurrent_pages: int = 5,
        request_timeout: int = 30,
        render_javascript: bool = True,
        respect_robots_txt: bool = True,
        rate_limit_requests_per_second: float = 2.0,
        shutdown_timeout: float = 30.0,
        persist_results: bool = True,
    ):
        self.worker_id = worker_id or str(uuid.uuid4())
        self.queue_name = queue_name
        self.redis_url = redis_url or settings.get_redis_url
        self.max_concurrent_pages = max_concurrent_pages
        self.request_timeout = request_timeout
        self.render_javascript = render_javascript
        self.respect_robots_txt = respect_robots_txt
        self.rate_limit_requests_per_second = rate_limit_requests_per_second
        self.shutdown_timeout = shutdown_timeout
        self.persist_results = persist_results
        
        # Components
        self._queue_manager: Optional[CrawlQueueManager] = None
        self._crawler: Optional[CrawlerEngine] = None
        self._rate_limiter: Optional[CrawlRateLimiter] = None
        
        # State
        self._running = False
        self._current_task: Optional[CrawlTask] = None
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # Callbacks
        self._on_page_crawled: Optional[Callable] = None
        self._on_job_progress: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
    
    async def start(self):
        """Start the worker and its components"""
        logger.info(f"Starting crawl worker: {self.worker_id}")
        
        # Initialize queue manager
        self._queue_manager = CrawlQueueManager(
            redis_url=self.redis_url,
            queue_name=self.queue_name,
        )
        await self._queue_manager.connect()
        
        # Initialize crawler engine
        self._crawler = CrawlerEngine(
            max_concurrent_pages=self.max_concurrent_pages,
            request_timeout=self.request_timeout,
            render_javascript=self.render_javascript,
            respect_robots_txt=self.respect_robots_txt,
        )
        await self._crawler.start()
        
        # Initialize rate limiter
        self._rate_limiter = CrawlRateLimiter(
            requests_per_second=self.rate_limit_requests_per_second,
            adaptive=True,
        )
        
        # Register worker
        await self._queue_manager.register_worker(
            self.worker_id,
            metadata={
                "max_concurrent_pages": self.max_concurrent_pages,
                "started_at": datetime.utcnow().isoformat(),
            }
        )
        
        # Start heartbeat
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        logger.info(f"Crawl worker started: {self.worker_id}")
    
    async def stop(self):
        """Stop the worker gracefully"""
        logger.info(f"Stopping crawl worker: {self.worker_id}")
        self._running = False
        
        # Cancel heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Close crawler
        if self._crawler:
            await self._crawler.close()
        
        # Disconnect queue manager
        if self._queue_manager:
            await self._queue_manager.disconnect()
        
        logger.info(
            f"Crawl worker stopped: {self.worker_id}. "
            f"Completed: {self._tasks_completed}, Failed: {self._tasks_failed}"
        )
    
    def on_page_crawled(self, callback: Callable):
        """Register callback for when a page is crawled"""
        self._on_page_crawled = callback
    
    def on_job_progress(self, callback: Callable):
        """Register callback for job progress updates"""
        self._on_job_progress = callback
    
    def on_error(self, callback: Callable):
        """Register callback for errors"""
        self._on_error = callback
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to the queue manager"""
        while self._running:
            try:
                await self._queue_manager.worker_heartbeat(self.worker_id)
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
            
            await asyncio.sleep(30)  # Heartbeat every 30 seconds
    
    async def process_task(self, task: CrawlTask) -> bool:
        """
        Process a single crawl task.
        
        Args:
            task: The crawl task to process
            
        Returns:
            True if task completed successfully
        """
        self._current_task = task
        url = task.url
        
        try:
            logger.info("Processing crawl task", task_id=task.id, job_id=task.crawl_job_id, url=url)

            if await self._should_skip_task(task):
                await self._queue_manager.complete_task(task.id, success=True)
                await self._mark_job_finished_if_idle(task.crawl_job_id)
                return True

            self._apply_task_settings(task)
            
            # Apply rate limiting
            await self._rate_limiter.wait(url)

            if task.depth == 0 and not task.metadata.get("sitemaps_queued"):
                await self._queue_sitemap_urls(task)
            
            # Crawl the page
            page_data, new_urls = await self._crawler.crawl_page(
                url=url,
                depth=task.depth,
                max_depth=task.metadata.get("max_depth", 2),
                crawl_job_id=task.crawl_job_id,
                allowed_domains=task.metadata.get("allowed_domains"),
                excluded_paths=task.metadata.get("excluded_paths"),
                follow_subdomains=task.metadata.get("follow_subdomains", False),
                max_retries=task.metadata.get("max_retries", task.max_retries),
            )
            
            if page_data:
                # Report response to rate limiter for adaptive adjustment
                await self._rate_limiter.report_response(
                    url,
                    page_data.status_code or 0,
                    page_data.response_time_ms or 0,
                )

                if self.persist_results:
                    await self._persist_page_result(task, page_data)
                
                # Execute callback for page crawled
                if self._on_page_crawled:
                    await self._on_page_crawled(task.crawl_job_id, page_data)
                
                # Queue new URLs if found
                if new_urls and task.depth < task.metadata.get("max_depth", 2):
                    new_tasks = []
                    remaining = await self._remaining_capacity(
                        task.crawl_job_id,
                        task.metadata.get("max_pages", 100),
                    )
                    for new_url in new_urls[: min(50, remaining)]:
                        metadata = dict(task.metadata)
                        metadata["sitemaps_queued"] = True
                        new_task = CrawlTask(
                            crawl_job_id=task.crawl_job_id,
                            url=new_url,
                            depth=task.depth + 1,
                            priority=task.priority,
                            max_retries=task.max_retries,
                            metadata=metadata,
                        )
                        new_tasks.append(new_task)
                    
                    if new_tasks:
                        result = await self._queue_manager.enqueue_tasks_batch(new_tasks)
                        await self._update_discovered_count(task.crawl_job_id, result["added"])
                        logger.debug(
                            f"Enqueued {result['added']} new URLs, "
                            f"{result['duplicates']} duplicates"
                        )
                
                # Mark task as completed
                await self._queue_manager.complete_task(task.id, success=True)
                self._tasks_completed += 1
                await self._mark_job_finished_if_idle(task.crawl_job_id)
                
                # Update progress
                if self._on_job_progress:
                    await self._on_job_progress(
                        task.crawl_job_id,
                        self._crawler.get_stats(),
                    )
                
                return True
            else:
                # Page data is None - treat as failure
                if self.persist_results:
                    await self._persist_task_error(task, "extract_failed", "Failed to extract page data")
                await self._queue_manager.complete_task(
                    task.id,
                    success=False,
                    error_message="Failed to extract page data",
                )
                self._tasks_failed += 1
                await self._mark_job_finished_if_idle(task.crawl_job_id)
                return False
                
        except Exception as e:
            logger.error(
                "Error processing task",
                task_id=task.id,
                job_id=task.crawl_job_id,
                error=_safe_log_text(e),
            )
            
            # Execute error callback
            if self._on_error:
                await self._on_error(task, e)

            if self.persist_results:
                try:
                    await self._persist_task_error(
                        task,
                        type(e).__name__,
                        str(e),
                        stack_trace=traceback.format_exc(),
                    )
                except Exception as persist_error:
                    logger.error(
                        "Failed to persist crawl task error",
                        task_id=task.id,
                        job_id=task.crawl_job_id,
                        error=_safe_log_text(persist_error),
                    )
            
            # Mark task as failed
            await self._queue_manager.complete_task(
                task.id,
                success=False,
                error_message=str(e),
            )
            self._tasks_failed += 1
            await self._mark_job_finished_if_idle(task.crawl_job_id)
            return False
        
        finally:
            self._current_task = None

    def _apply_task_settings(self, task: CrawlTask) -> None:
        """Apply per-job crawl settings carried on the queued task."""
        if not self._crawler:
            return

        metadata = task.metadata or {}
        self._crawler.request_timeout = int(metadata.get("request_timeout", self.request_timeout))
        self._crawler.crawl_delay = float(metadata.get("crawl_delay", 0) or 0)
        self._crawler.render_javascript = bool(metadata.get("render_javascript", self.render_javascript))
        self._crawler.respect_robots_txt = bool(metadata.get("respect_robots_txt", self.respect_robots_txt))
        if metadata.get("user_agent"):
            self._crawler.user_agent = metadata["user_agent"]

    async def _should_skip_task(self, task: CrawlTask) -> bool:
        """Skip work for cancelled/completed jobs or jobs that reached their page cap."""
        async with async_session_maker() as db:
            repo = CrawlRepository(db)
            job = await repo.get_job(UUID(task.crawl_job_id))
            if not job:
                logger.warning("Skipping task for missing crawl job", task_id=task.id, job_id=task.crawl_job_id)
                return True
            if job.status in {CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled}:
                return True
            if (job.total_pages_crawled or 0) >= job.max_pages:
                await repo.set_job_status(job, CrawlStatus.completed)
                await db.commit()
                return True
        return False

    async def _queue_sitemap_urls(self, task: CrawlTask) -> None:
        """Queue sitemap-discovered URLs for the initial crawl task."""
        remaining = await self._remaining_capacity(task.crawl_job_id, task.metadata.get("max_pages", 100))
        if remaining <= 0:
            return

        sitemap_urls = await self._crawler.discover_sitemap_pages(
            task.url,
            additional_sitemaps=task.metadata.get("sitemap_urls") or [],
            max_urls=remaining,
        )
        if not sitemap_urls:
            return

        metadata = dict(task.metadata)
        metadata["sitemaps_queued"] = True
        new_tasks = [
            CrawlTask(
                crawl_job_id=task.crawl_job_id,
                url=url,
                depth=0,
                priority=task.priority,
                max_retries=task.max_retries,
                metadata=metadata,
            )
            for url in sitemap_urls
            if url != task.url
        ]
        if new_tasks:
            result = await self._queue_manager.enqueue_tasks_batch(new_tasks)
            await self._update_discovered_count(task.crawl_job_id, result["added"])
            logger.info(
                "Queued sitemap URLs",
                job_id=task.crawl_job_id,
                added=result["added"],
                duplicates=result["duplicates"],
            )

    async def _persist_page_result(self, task: CrawlTask, page_data: PageData) -> None:
        """Persist extracted page, links, errors, and aggregate progress."""
        job_id = UUID(task.crawl_job_id)
        async with async_session_maker() as db:
            repo = CrawlRepository(db)
            job = await repo.get_job(job_id)
            if not job:
                return

            if job.status in {CrawlStatus.pending, CrawlStatus.queued}:
                await repo.set_job_status(job, CrawlStatus.running, worker_id=self.worker_id)

            page = await repo.save_page(
                job_id,
                page_data.to_dict(),
                crawl_order=(job.total_pages_crawled or 0) + 1,
                depth=task.depth,
                retry_count=task.retry_count,
            )
            await repo.replace_page_links(
                job_id,
                page.id,
                page_data.internal_links,
                page_data.external_links,
            )

            for issue in page_data.issues:
                issue_type = str(issue.get("type") or "")
                if issue_type in {"crawl_error", "unexpected_error", "timeout", "blocked_by_robots"}:
                    await repo.save_error(
                        job_id,
                        error_type=issue_type,
                        error_message=str(issue.get("message") or ""),
                        url=page_data.url,
                        page_id=page.id,
                        retry_count=task.retry_count,
                    )

            await repo.refresh_job_aggregates(job_id)
            await db.commit()

    async def _persist_task_error(
        self,
        task: CrawlTask,
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None,
    ) -> None:
        async with async_session_maker() as db:
            repo = CrawlRepository(db)
            await repo.save_error(
                UUID(task.crawl_job_id),
                error_type=error_type,
                error_message=error_message,
                url=task.url,
                retry_count=task.retry_count,
                stack_trace=stack_trace,
            )
            await db.commit()

    async def _remaining_capacity(self, job_id: str, max_pages: int) -> int:
        stats = await self._queue_manager.get_job_stats(job_id)
        scheduled = (
            stats.get("pending", 0)
            + stats.get("running", 0)
            + stats.get("retry", 0)
            + stats.get("completed", 0)
            + stats.get("failed", 0)
        )
        return max(0, int(max_pages) - int(scheduled))

    async def _update_discovered_count(self, job_id: str, added_count: int) -> None:
        if added_count <= 0:
            return
        async with async_session_maker() as db:
            repo = CrawlRepository(db)
            job = await repo.get_job(UUID(job_id))
            if job:
                job.total_pages_discovered = (job.total_pages_discovered or 0) + added_count
                await db.commit()

    async def _mark_job_finished_if_idle(self, job_id: str) -> None:
        stats = await self._queue_manager.get_job_stats(job_id)
        if stats.get("pending", 0) > 0 or stats.get("running", 0) > 0 or stats.get("retry", 0) > 0:
            return

        async with async_session_maker() as db:
            repo = CrawlRepository(db)
            job = await repo.get_job(UUID(job_id))
            if not job or job.status in {CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled}:
                return

            await repo.refresh_job_aggregates(UUID(job_id))
            final_status = CrawlStatus.completed
            if (job.total_pages_crawled or 0) == 0 and stats.get("failed", 0) > 0:
                final_status = CrawlStatus.failed
            await repo.set_job_status(job, final_status)
            await db.commit()
    
    async def run(self):
        """Main worker loop - process tasks from the queue"""
        logger.info(f"Worker {self.worker_id} starting main loop")
        
        while self._running:
            try:
                # Get next task from queue
                task = await self._queue_manager.dequeue_task(self.worker_id)
                
                if task:
                    await self.process_task(task)
                else:
                    # No task available, wait a bit
                    await asyncio.sleep(0.5)
                    
            except asyncio.CancelledError:
                logger.info(f"Worker {self.worker_id} cancelled")
                break
                
            except Exception as e:
                logger.error("Error in worker loop", error=_safe_log_text(e))
                await asyncio.sleep(1)  # Back off on error
        
        logger.info(f"Worker {self.worker_id} main loop ended")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        return {
            "worker_id": self.worker_id,
            "running": self._running,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "current_task": self._current_task.id if self._current_task else None,
            "crawler_stats": self._crawler.get_stats() if self._crawler else {},
        }


class CrawlWorkerPool:
    """
    Pool of crawl workers for parallel processing.
    Manages multiple worker instances and their lifecycle.
    """
    
    def __init__(
        self,
        num_workers: int = 3,
        queue_name: str = "default",
        redis_url: Optional[str] = None,
        **worker_kwargs,
    ):
        self.num_workers = num_workers
        self.queue_name = queue_name
        self.redis_url = redis_url or settings.get_redis_url
        self.worker_kwargs = worker_kwargs
        
        self._workers: List[CrawlWorker] = []
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._on_page_crawled: Optional[Callable] = None
        self._on_job_progress: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
    
    async def start(self):
        """Start all workers in the pool"""
        logger.info(f"Starting worker pool with {self.num_workers} workers")
        
        self._running = True
        
        for i in range(self.num_workers):
            worker = CrawlWorker(
                worker_id=f"worker-{i}-{uuid.uuid4().hex[:8]}",
                queue_name=self.queue_name,
                redis_url=self.redis_url,
                **self.worker_kwargs,
            )
            
            # Set up callbacks
            worker.on_page_crawled(self._on_page_crawled)
            worker.on_job_progress(self._on_job_progress)
            worker.on_error(self._on_error)
            
            await worker.start()
            self._workers.append(worker)
            
            # Start worker task
            task = asyncio.create_task(worker.run())
            self._tasks.append(task)
        
        logger.info(f"Worker pool started with {self.num_workers} workers")
    
    async def stop(self):
        """Stop all workers gracefully"""
        logger.info("Stopping worker pool")
        self._running = False
        
        # Stop all workers
        for worker in self._workers:
            await worker.stop()
        
        # Wait for all tasks to complete
        if self._tasks:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Worker task error: {result}")
        
        self._workers.clear()
        self._tasks.clear()
        
        logger.info("Worker pool stopped")
    
    def on_page_crawled(self, callback: Callable):
        """Register callback for when a page is crawled"""
        self._on_page_crawled = callback
    
    def on_job_progress(self, callback: Callable):
        """Register callback for job progress updates"""
        self._on_job_progress = callback
    
    def on_error(self, callback: Callable):
        """Register callback for errors"""
        self._on_error = callback
    
    def get_stats(self) -> List[Dict[str, Any]]:
        """Get statistics from all workers"""
        return [worker.get_stats() for worker in self._workers]


async def run_worker(
    worker_id: Optional[str] = None,
    queue_name: str = "default",
    redis_url: Optional[str] = None,
    num_workers: int = 1,
    **kwargs,
):
    """
    Run crawl worker(s).
    
    Args:
        worker_id: Optional worker ID
        queue_name: Name of the queue to process
        redis_url: Redis connection URL
        num_workers: Number of workers to run
        **kwargs: Additional arguments passed to CrawlWorker
    """
    if num_workers == 1:
        worker = CrawlWorker(
            worker_id=worker_id,
            queue_name=queue_name,
            redis_url=redis_url,
            **kwargs,
        )
        async with worker:
            await worker.run()
    else:
        pool = CrawlWorkerPool(
            num_workers=num_workers,
            queue_name=queue_name,
            redis_url=redis_url,
            **kwargs,
        )
        async with pool:
            # Keep running until interrupted
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def main() -> None:
    """Command-line entrypoint used by Docker Compose crawl workers."""
    parser = argparse.ArgumentParser(description="Run distributed SEO crawl workers")
    parser.add_argument("--workers", type=int, default=int(os.getenv("CRAWL_WORKER_REPLICAS", "1")))
    parser.add_argument("--queue", default="default")
    parser.add_argument("--redis-url", default=settings.get_redis_url)
    parser.add_argument("--max-concurrent-pages", type=int, default=int(os.getenv("CRAWLER_MAX_CONCURRENT_PAGES", "5")))
    parser.add_argument("--request-timeout", type=int, default=int(os.getenv("CRAWLER_REQUEST_TIMEOUT", "30")))
    parser.add_argument("--rate-limit-rps", type=float, default=float(os.getenv("CRAWLER_RATE_LIMIT_RPS", "2")))
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    asyncio.run(
        run_worker(
            queue_name=args.queue,
            redis_url=args.redis_url,
            num_workers=args.workers,
            max_concurrent_pages=args.max_concurrent_pages,
            request_timeout=args.request_timeout,
            render_javascript=_env_bool("CRAWLER_RENDER_JAVASCRIPT", True),
            respect_robots_txt=_env_bool("CRAWLER_RESPECT_ROBOTS_TXT", True),
            rate_limit_requests_per_second=args.rate_limit_rps,
            persist_results=not args.no_persist,
        )
    )


if __name__ == "__main__":
    main()

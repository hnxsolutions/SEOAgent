"""
SEO Agent SaaS - Crawl Queue Manager
Redis-based queue system for distributed crawl task management
"""
import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from enum import Enum

import redis.asyncio as redis
from pydantic import BaseModel, ConfigDict, Field
import structlog

logger = structlog.get_logger(__name__)


class TaskStatus(str, Enum):
    """Status of a crawl task"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"


class TaskPriority(int, Enum):
    """Priority levels for crawl tasks"""
    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


class CrawlTask(BaseModel):
    """Represents a single crawl task in the queue"""
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    crawl_job_id: str
    url: str
    depth: int = 0
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    worker_id: Optional[str] = None
    
    # Task metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @property
    def score(self) -> float:
        """Calculate priority score for sorted set ordering"""
        # Higher priority = lower score (processed first)
        # Within same priority, earlier created = lower score
        priority_offset = {
            TaskPriority.LOW: 1000,
            TaskPriority.NORMAL: 500,
            TaskPriority.HIGH: 100,
            TaskPriority.CRITICAL: 0,
        }
        offset = priority_offset.get(self.priority, 500)
        created_timestamp = self.created_at.timestamp() if self.created_at else time.time()
        return offset + created_timestamp
    
    def to_json(self) -> str:
        """Serialize task to JSON"""
        data = self.model_dump()
        if self.created_at:
            data['created_at'] = self.created_at.isoformat()
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, data: str) -> 'CrawlTask':
        """Deserialize task from JSON"""
        task_data = json.loads(data)
        if 'created_at' in task_data and task_data['created_at']:
            task_data['created_at'] = datetime.fromisoformat(task_data['created_at'])
        if 'started_at' in task_data and task_data['started_at']:
            task_data['started_at'] = datetime.fromisoformat(task_data['started_at'])
        if 'completed_at' in task_data and task_data['completed_at']:
            task_data['completed_at'] = datetime.fromisoformat(task_data['completed_at'])
        return cls(**task_data)


class CrawlQueueManager:
    """
    Redis-based queue manager for distributed crawl operations.
    Uses sorted sets for priority queuing and handles task distribution
    across multiple workers.
    """
    
    # Queue key prefixes
    QUEUE_PREFIX = "crawl:queue"
    TASK_PREFIX = "crawl:task"
    JOB_PREFIX = "crawl:job"
    WORKER_PREFIX = "crawl:worker"
    DEDUP_PREFIX = "crawl:dedup"
    STATS_PREFIX = "crawl:stats"
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        queue_name: str = "default",
        task_ttl: int = 86400,  # 24 hours
    ):
        self.redis_url = redis_url
        self.queue_name = queue_name
        self.task_ttl = task_ttl
        self._redis: Optional[redis.Redis] = None
        self._connected = False
    
    async def connect(self):
        """Connect to Redis"""
        if not self._connected:
            self._redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            self._connected = True
            logger.info(f"Connected to Redis: {self.redis_url}")
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self._redis:
            await self._redis.close()
            self._connected = False
            logger.info("Disconnected from Redis")
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
    
    @property
    def _queue_key(self) -> str:
        """Get the main queue key"""
        return f"{self.QUEUE_PREFIX}:{self.queue_name}"
    
    @property
    def _processing_key(self) -> str:
        """Get the processing set key"""
        return f"{self.QUEUE_PREFIX}:{self.queue_name}:processing"
    
    @property
    def _delayed_key(self) -> str:
        """Get the delayed queue key"""
        return f"{self.QUEUE_PREFIX}:{self.queue_name}:delayed"
    
    @property
    def _failed_key(self) -> str:
        """Get the failed queue key"""
        return f"{self.QUEUE_PREFIX}:{self.queue_name}:failed"
    
    def _task_key(self, task_id: str) -> str:
        """Get the task data key"""
        return f"{self.TASK_PREFIX}:{task_id}"
    
    def _job_key(self, job_id: str) -> str:
        """Get the job data key"""
        return f"{self.JOB_PREFIX}:{job_id}"
    
    def _dedup_key(self, url_hash: str, job_id: str) -> str:
        """Get the per-job deduplication key for a URL."""
        return f"{self.DEDUP_PREFIX}:{self.queue_name}:{job_id}:{url_hash}"
    
    def _stats_key(self, job_id: str) -> str:
        """Get the stats key for a job"""
        return f"{self.STATS_PREFIX}:{job_id}"
    
    async def enqueue_task(self, task: CrawlTask) -> bool:
        """
        Add a task to the queue.
        
        Args:
            task: The crawl task to enqueue
            
        Returns:
            True if task was added, False if duplicate
        """
        if not self._connected:
            await self.connect()
        
        # Check for duplicates using URL hash
        url_hash = self._hash_url(task.url)
        dedup_key = self._dedup_key(url_hash, task.crawl_job_id)
        
        # Use SETNX for atomic duplicate check
        added = await self._redis.set(dedup_key, task.id, nx=True, ex=self.task_ttl)
        if not added:
            logger.debug(f"Duplicate task skipped: {task.url}")
            return False
        
        # Update task status
        task.status = TaskStatus.QUEUED
        
        # Add to sorted set with priority score
        await self._redis.zadd(
            self._queue_key,
            {task.id: task.score}
        )
        
        # Store task data
        await self._redis.setex(
            self._task_key(task.id),
            self.task_ttl,
            task.to_json()
        )
        
        # Update job stats
        await self._increment_stat(task.crawl_job_id, "pending")
        
        logger.debug(f"Enqueued task: {task.id} for {task.url}")
        return True
    
    async def enqueue_tasks_batch(self, tasks: List[CrawlTask]) -> Dict[str, int]:
        """
        Add multiple tasks to the queue in batch.
        
        Args:
            tasks: List of crawl tasks
            
        Returns:
            Dict with counts of added/duplicate tasks
        """
        if not self._connected:
            await self.connect()
        
        results = {"added": 0, "duplicates": 0}
        pipe = self._redis.pipeline()
        added_tasks: List[CrawlTask] = []
        
        for task in tasks:
            url_hash = self._hash_url(task.url)
            dedup_key = self._dedup_key(url_hash, task.crawl_job_id)
            
            # Check for duplicate
            exists = await self._redis.exists(dedup_key)
            if exists:
                results["duplicates"] += 1
                continue
            
            # Mark as added
            task.status = TaskStatus.QUEUED
            results["added"] += 1
            added_tasks.append(task)
            
            # Queue operations
            pipe.set(dedup_key, task.id, nx=True, ex=self.task_ttl)
            pipe.zadd(self._queue_key, {task.id: task.score})
            pipe.setex(self._task_key(task.id), self.task_ttl, task.to_json())
        
        if pipe.command_stack:
            for task in added_tasks:
                pipe.hincrby(self._stats_key(task.crawl_job_id), "pending", 1)
            await pipe.execute()
        
        return results
    
    async def dequeue_task(self, worker_id: str) -> Optional[CrawlTask]:
        """
        Get the next task from the queue.
        Uses atomic operations to ensure task is only given to one worker.
        
        Args:
            worker_id: ID of the worker claiming the task
            
        Returns:
            The next task or None if queue is empty
        """
        if not self._connected:
            await self.connect()
        
        # First, check delayed queue for tasks that are ready
        current_time = time.time()
        delayed_tasks = await self._redis.zrangebyscore(
            self._delayed_key,
            0,
            current_time,
            start=0,
            num=1,
        )
        
        if delayed_tasks:
            task_id = delayed_tasks[0]
            await self._redis.zrem(self._delayed_key, task_id)
            # Move to main queue
            task_data = await self._redis.get(self._task_key(task_id))
            if task_data:
                task = CrawlTask.from_json(task_data)
                task.status = TaskStatus.QUEUED
                await self._redis.zadd(self._queue_key, {task_id: task.score})
                await self._redis.setex(self._task_key(task_id), self.task_ttl, task.to_json())
                await self._decrement_stat(task.crawl_job_id, "retry")
                await self._increment_stat(task.crawl_job_id, "pending")
        
        # Get next task from main queue (atomic)
        tasks = await self._redis.zpopmin(self._queue_key, count=1)
        if not tasks:
            return None
        
        task_id = tasks[0][0]
        
        # Get task data
        task_data = await self._redis.get(self._task_key(task_id))
        if not task_data:
            return None
        
        task = CrawlTask.from_json(task_data)
        
        # Update task status
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        task.worker_id = worker_id
        
        # Move to processing set
        await self._redis.zadd(
            self._processing_key,
            {task_id: time.time()}
        )
        
        # Update task data
        await self._redis.setex(
            self._task_key(task_id),
            self.task_ttl,
            task.to_json()
        )
        
        # Update stats
        await self._increment_stat(task.crawl_job_id, "running")
        await self._decrement_stat(task.crawl_job_id, "pending")
        
        logger.debug(f"Dequeued task: {task.id} for worker {worker_id}")
        return task
    
    async def complete_task(self, task_id: str, success: bool = True, error_message: str = None):
        """
        Mark a task as completed.
        
        Args:
            task_id: ID of the completed task
            success: Whether the task completed successfully
            error_message: Error message if task failed
        """
        if not self._connected:
            await self.connect()
        
        task_data = await self._redis.get(self._task_key(task_id))
        if not task_data:
            return
        
        task = CrawlTask.from_json(task_data)
        task.completed_at = datetime.utcnow()
        
        # Remove from processing
        await self._redis.zrem(self._processing_key, task_id)
        
        if success:
            task.status = TaskStatus.COMPLETED
            
            # Update stats
            await self._increment_stat(task.crawl_job_id, "completed")
            await self._decrement_stat(task.crawl_job_id, "running")
            
        else:
            task.error_message = error_message
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = TaskStatus.RETRY
                
                # Add back to queue with delay (exponential backoff)
                delay = min(2 ** task.retry_count * 5, 300)  # Max 5 minutes
                await self._redis.zadd(
                    self._delayed_key,
                    {task_id: time.time() + delay}
                )
                
                await self._increment_stat(task.crawl_job_id, "retry")
                await self._decrement_stat(task.crawl_job_id, "running")
                logger.info(f"Task {task_id} scheduled for retry {task.retry_count}/{task.max_retries}")
            else:
                task.status = TaskStatus.FAILED
                
                # Move to failed set
                await self._redis.zadd(
                    self._failed_key,
                    {task_id: time.time()}
                )
                
                await self._increment_stat(task.crawl_job_id, "failed")
                await self._decrement_stat(task.crawl_job_id, "running")
                logger.warning(f"Task {task_id} permanently failed: {error_message}")
        
        # Update task data
        await self._redis.setex(
            self._task_key(task_id),
            self.task_ttl,
            task.to_json()
        )
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task.
        
        Args:
            task_id: ID of the task to cancel
            
        Returns:
            True if task was cancelled
        """
        if not self._connected:
            await self.connect()
        
        task_data = await self._redis.get(self._task_key(task_id))
        if not task_data:
            return False
        
        task = CrawlTask.from_json(task_data)
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            return False
        
        old_status = task.status
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        
        # Remove from all queues
        await self._redis.zrem(self._queue_key, task_id)
        await self._redis.zrem(self._processing_key, task_id)
        await self._redis.zrem(self._delayed_key, task_id)
        
        # Update task data
        await self._redis.setex(
            self._task_key(task_id),
            self.task_ttl,
            task.to_json()
        )

        if old_status in [TaskStatus.PENDING, TaskStatus.QUEUED]:
            await self._decrement_stat(task.crawl_job_id, "pending")
        elif old_status == TaskStatus.RUNNING:
            await self._decrement_stat(task.crawl_job_id, "running")
        elif old_status == TaskStatus.RETRY:
            await self._decrement_stat(task.crawl_job_id, "retry")
        await self._increment_stat(task.crawl_job_id, "cancelled")
        
        logger.info(f"Cancelled task: {task_id}")
        return True
    
    async def cancel_job_tasks(self, job_id: str) -> int:
        """
        Cancel all tasks for a crawl job.
        
        Args:
            job_id: ID of the crawl job
            
        Returns:
            Number of tasks cancelled
        """
        if not self._connected:
            await self.connect()
        
        cancelled = 0
        cursor = 0
        pattern = f"{self.TASK_PREFIX}:*"
        
        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor,
                match=pattern,
                count=100
            )
            
            for key in keys:
                task_data = await self._redis.get(key)
                if task_data:
                    task = CrawlTask.from_json(task_data)
                    if task.crawl_job_id == job_id and task.status in [
                        TaskStatus.PENDING,
                        TaskStatus.QUEUED,
                        TaskStatus.RUNNING,
                        TaskStatus.RETRY,
                    ]:
                        await self.cancel_task(task.id)
                        cancelled += 1
            
            if cursor == 0:
                break
        
        return cancelled
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get statistics about the queue"""
        if not self._connected:
            await self.connect()
        
        queue_size = await self._redis.zcard(self._queue_key)
        processing_count = await self._redis.zcard(self._processing_key)
        delayed_count = await self._redis.zcard(self._delayed_key)
        failed_count = await self._redis.zcard(self._failed_key)
        
        return {
            "queue_name": self.queue_name,
            "queued": queue_size,
            "processing": processing_count,
            "delayed": delayed_count,
            "failed": failed_count,
            "total": queue_size + processing_count + delayed_count + failed_count,
        }
    
    async def get_task(self, task_id: str) -> Optional[CrawlTask]:
        """Get a specific task by ID"""
        if not self._connected:
            await self.connect()
        
        task_data = await self._redis.get(self._task_key(task_id))
        if task_data:
            return CrawlTask.from_json(task_data)
        return None
    
    async def get_job_tasks(
        self,
        job_id: str,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> List[CrawlTask]:
        """Get all tasks for a crawl job"""
        if not self._connected:
            await self.connect()
        
        tasks = []
        cursor = 0
        pattern = f"{self.TASK_PREFIX}:*"
        
        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor,
                match=pattern,
                count=100
            )
            
            for key in keys:
                task_data = await self._redis.get(key)
                if task_data:
                    task = CrawlTask.from_json(task_data)
                    if task.crawl_job_id == job_id:
                        if status is None or task.status == status:
                            tasks.append(task)
                            if len(tasks) >= limit:
                                return tasks
            
            if cursor == 0:
                break
        
        return tasks
    
    async def register_worker(self, worker_id: str, metadata: Dict[str, Any] = None):
        """Register a worker"""
        if not self._connected:
            await self.connect()
        
        worker_data = {
            "worker_id": worker_id,
            "registered_at": datetime.utcnow().isoformat(),
            "last_heartbeat": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }
        
        await self._redis.setex(
            f"{self.WORKER_PREFIX}:{worker_id}",
            300,  # 5 minute TTL
            json.dumps(worker_data)
        )
    
    async def worker_heartbeat(self, worker_id: str):
        """Update worker heartbeat"""
        if not self._connected:
            await self.connect()
        
        worker_data = await self._redis.get(f"{self.WORKER_PREFIX}:{worker_id}")
        if worker_data:
            data = json.loads(worker_data)
            data["last_heartbeat"] = datetime.utcnow().isoformat()
            await self._redis.setex(
                f"{self.WORKER_PREFIX}:{worker_id}",
                300,
                json.dumps(data)
            )
    
    async def _increment_stat(self, job_id: str, stat: str):
        """Increment a job statistic"""
        if self._redis:
            await self._redis.hincrby(self._stats_key(job_id), stat, 1)
    
    async def _decrement_stat(self, job_id: str, stat: str):
        """Decrement a job statistic"""
        if self._redis:
            await self._redis.hincrby(self._stats_key(job_id), stat, -1)
    
    async def get_job_stats(self, job_id: str) -> Dict[str, Any]:
        """Get statistics for a crawl job"""
        if not self._connected:
            await self.connect()
        
        stats = await self._redis.hgetall(self._stats_key(job_id))
        return {
            "job_id": job_id,
            "pending": int(stats.get("pending", 0)),
            "running": int(stats.get("running", 0)),
            "completed": int(stats.get("completed", 0)),
            "failed": int(stats.get("failed", 0)),
            "retry": int(stats.get("retry", 0)),
            "cancelled": int(stats.get("cancelled", 0)),
        }
    
    @staticmethod
    def _hash_url(url: str) -> str:
        """Generate a hash for URL deduplication"""
        import hashlib
        normalized = url.lower().strip().rstrip('/')
        if not normalized.endswith('/'):
            normalized += '/'
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    async def clear_queue(self):
        """Clear all tasks from the queue"""
        if not self._connected:
            await self.connect()
        
        # Clear all queue-related keys
        keys_to_delete = [
            self._queue_key,
            self._processing_key,
            self._delayed_key,
            self._failed_key,
        ]
        
        # Also clear task data keys
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor,
                match=f"{self.TASK_PREFIX}:*",
                count=100
            )
            keys_to_delete.extend(keys)
            if cursor == 0:
                break
        
        # Clear dedup keys
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor,
                match=f"{self.DEDUP_PREFIX}:*",
                count=100
            )
            keys_to_delete.extend(keys)
            if cursor == 0:
                break
        
        if keys_to_delete:
            await self._redis.delete(*keys_to_delete)
        
        logger.info(f"Cleared queue: {self.queue_name}")

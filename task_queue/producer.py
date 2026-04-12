"""Redis Streams Task Producer

Publishes tasks to Redis Streams with priority queuing, deduplication,
batch processing, and reliable error handling.

Provides the publishing interface for SEO agent task orchestration.
"""

import asyncio
import json
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
import structlog
from .models import TaskMessage, TaskType, TaskPriority, TaskResult, StreamConfig
from .exceptions import (
    QueueConnectionError,
    TaskValidationError,
    TaskPublishError,
    DuplicateTaskError,
    CircuitBreakerError
)
from .utils import (
    CircuitBreaker,
    RetryPolicy,
    generate_task_id,
    calculate_task_hash,
    sanitize_consumer_name,
    format_stream_id
)

logger = structlog.get_logger()


class TaskProducer:
    """Redis Streams task producer for SEO automation.
    
    Handles task publishing with features:
    - Priority-based queuing
    - Content-based deduplication
    - Batch publishing for efficiency
    - Circuit breaker for reliability
    - Comprehensive error handling
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        stream_config: Optional[StreamConfig] = None
    ):
        """Initialize task producer.
        
        Args:
            redis_client: Optional Redis client instance
            stream_config: Optional stream configuration
        """
        from config import get_settings
        
        self.settings = get_settings()
        self.redis_config = self.settings.redis
        self.stream_config = stream_config or StreamConfig()
        
        self._redis_client = redis_client
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30,
            expected_exception=(RedisError, QueueConnectionError),
            name="task_producer"
        )
        self._retry_policy = RetryPolicy(
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            backoff_factor=2.0
        )
        
        # Task deduplication cache
        self._deduplication_cache: Set[str] = set()
        self._cache_last_refresh = datetime.utcnow()
        self._cache_refresh_interval = timedelta(minutes=5)
        
        # Batch publishing
        self._batch_queue: List[TaskMessage] = []
        self._batch_lock = asyncio.Lock()
        self._batch_timer: Optional[asyncio.Task] = None

    @property
    async def redis_client(self) -> redis.Redis:
        """Get Redis client instance with connection pooling."""
        if self._redis_client is None:
            try:
                self._redis_client = redis.from_url(
                    self.redis_config.connection_url,
                    max_connections=self.redis_config.max_connections,
                    socket_timeout=self.redis_config.socket_timeout,
                    socket_connect_timeout=self.redis_config.socket_connect_timeout,
                    decode_responses=True
                )
                
                # Test connection
                await self._circuit_breaker.call(
                    lambda: self._redis_client.ping()
                )
                
                logger.info("redis_connection_established", 
                           host=self.redis_config.host,
                           port=self.redis_config.port)
                
            except RedisError as e:
                logger.error("redis_connection_failed", error=str(e))
                raise QueueConnectionError(
                    f"Failed to connect to Redis: {e}",
                    {"redis_url": self.redis_config.connection_url}
                )
        
        return self._redis_client

    async def _ensure_streams_exist(self):
        """Ensure required Redis Streams exist with proper configuration."""
        client = await self.redis_client
        
        streams_to_create = [
            self.stream_config.tasks_stream,
            self.stream_config.results_stream,
            self.stream_config.failed_tasks_stream
        ]
        
        for stream_name in streams_to_create:
            try:
                # Check if stream exists
                try:
                    await client.xinfo_stream(stream_name)
                except redis.ResponseError as e:
                    if "no such key" in str(e).lower():
                        # Stream doesn't exist, create it with a dummy message
                        await client.xadd(
                            stream_name,
                            {"_init": "stream_created", "timestamp": datetime.utcnow().isoformat()},
                            id="0-1"
                        )
                        
                        # Remove the dummy message
                        await client.xdel(stream_name, "0-1")
                        
                        logger.info("stream_created", stream=stream_name)
                    else:
                        raise
                
                # Set stream max length if configured
                if self.stream_config.max_stream_length > 0:
                    await client.xtrim(
                        stream_name,
                        maxlen=self.stream_config.max_stream_length,
                        approximate=True
                    )
                
            except RedisError as e:
                logger.error("stream_creation_failed", stream=stream_name, error=str(e))
                raise QueueConnectionError(
                    f"Failed to ensure stream {stream_name} exists: {e}",
                    {"stream_name": stream_name}
                )

    async def _refresh_deduplication_cache(self):
        """Refresh deduplication cache from Redis."""
        now = datetime.utcnow()
        if now - self._cache_last_refresh < self._cache_refresh_interval:
            return
        
        try:
            client = await self.redis_client
            
            # Get recent tasks from the stream to build deduplication cache
            messages = await client.xrange(
                self.stream_config.tasks_stream,
                min="-",
                max="+",
                count=1000
            )
            
            self._deduplication_cache.clear()
            for msg_id, fields in messages:
                if "content_hash" in fields:
                    self._deduplication_cache.add(fields["content_hash"])
            
            self._cache_last_refresh = now
            
            logger.debug("deduplication_cache_refreshed", 
                        cache_size=len(self._deduplication_cache))
                        
        except RedisError as e:
            logger.warning("deduplication_cache_refresh_failed", error=str(e))
            # Continue without cache refresh - degraded mode

    async def _check_duplicate_task(self, task: TaskMessage) -> bool:
        """Check if task is duplicate based on content hash.
        
        Args:
            task: Task to check for duplicates
            
        Returns:
            True if task is duplicate
            
        Raises:
            DuplicateTaskError: If duplicate is found
        """
        content_hash = task.content_hash
        
        # Refresh cache if needed
        await self._refresh_deduplication_cache()
        
        # Check cache first
        if content_hash in self._deduplication_cache:
            # Double-check in Redis to be sure
            try:
                client = await self.redis_client
                
                # Search for existing task with same hash
                messages = await client.xrange(
                    self.stream_config.tasks_stream,
                    min="-",
                    max="+",
                    count=100  # Check recent tasks
                )
                
                for msg_id, fields in messages:
                    if fields.get("content_hash") == content_hash:
                        existing_task_id = fields.get("task_id", msg_id)
                        raise DuplicateTaskError(content_hash, existing_task_id)
                
                # Not found in Redis, remove from cache
                self._deduplication_cache.discard(content_hash)
                
            except RedisError as e:
                logger.warning("duplicate_check_failed", error=str(e))
                # Continue without duplicate check - degraded mode
        
        return False

    async def publish_task(
        self,
        task_type: TaskType,
        payload: Dict[str, Any],
        priority: TaskPriority = TaskPriority.MEDIUM,
        user_id: Optional[str] = None,
        site_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        timeout_seconds: int = 1800,
        max_retries: int = 3,
        skip_deduplication: bool = False
    ) -> str:
        """Publish a single task to the queue.
        
        Args:
            task_type: Type of task to publish
            payload: Task-specific data
            priority: Task priority level
            user_id: Optional user ID for task tracking
            site_id: Optional site ID for task tracking
            parent_task_id: Optional parent task ID for workflow tracking
            dependencies: Optional list of task IDs this task depends on
            timeout_seconds: Task execution timeout
            max_retries: Maximum retry attempts
            skip_deduplication: Skip duplicate checking
            
        Returns:
            Published task ID
            
        Raises:
            TaskValidationError: Invalid task data
            DuplicateTaskError: Task already exists
            TaskPublishError: Publishing failed
            QueueConnectionError: Redis connection issues
        """
        # Create task message
        task = TaskMessage(
            task_type=task_type,
            priority=priority,
            payload=payload,
            user_id=user_id,
            site_id=site_id,
            parent_task_id=parent_task_id,
            dependencies=dependencies or [],
            timeout_seconds=timeout_seconds,
            max_retries=max_retries
        )
        
        # Validate task
        try:
            task.model_validate(task.model_dump())
        except Exception as e:
            raise TaskValidationError(f"Task validation failed: {e}")
        
        # Check for duplicates unless skipped
        if not skip_deduplication:
            await self._check_duplicate_task(task)
        
        # Ensure streams exist
        await self._ensure_streams_exist()
        
        # Publish task
        async def _publish():
            client = await self.redis_client
            
            # Convert task to Redis fields
            fields = task.to_redis_fields()
            
            # Add to stream with priority-based ID
            stream_id = await client.xadd(
                self.stream_config.tasks_stream,
                fields,
                maxlen=self.stream_config.max_stream_length,
                approximate=True
            )
            
            # Update deduplication cache
            self._deduplication_cache.add(task.content_hash)
            
            return stream_id
        
        try:
            stream_id = await self._circuit_breaker.call(_publish)
            
            logger.info("task_published",
                       task_id=task.task_id,
                       task_type=task_type.value,
                       priority=priority.value,
                       stream_id=stream_id)
            
            return task.task_id
            
        except (RedisError, CircuitBreakerError) as e:
            logger.error("task_publish_failed",
                        task_id=task.task_id,
                        error=str(e))
            raise TaskPublishError(
                f"Failed to publish task {task.task_id}: {e}",
                {"task_id": task.task_id, "task_type": task_type.value}
            )

    async def publish_task_batch(
        self,
        tasks: List[Dict[str, Any]],
        skip_deduplication: bool = False
    ) -> List[str]:
        """Publish multiple tasks in a batch operation.
        
        Args:
            tasks: List of task definitions
            skip_deduplication: Skip duplicate checking for all tasks
            
        Returns:
            List of published task IDs
            
        Raises:
            TaskValidationError: Invalid task data
            TaskPublishError: Batch publishing failed
        """
        if not tasks:
            return []
        
        published_ids = []
        failed_tasks = []
        
        # Process each task
        for task_def in tasks:
            try:
                task_id = await self.publish_task(
                    skip_deduplication=skip_deduplication,
                    **task_def
                )
                published_ids.append(task_id)
                
            except Exception as e:
                failed_tasks.append({
                    "task_def": task_def,
                    "error": str(e)
                })
                logger.warning("batch_task_failed", 
                              task_def=task_def, 
                              error=str(e))
        
        if failed_tasks:
            logger.error("batch_publish_partial_failure",
                        total_tasks=len(tasks),
                        published=len(published_ids),
                        failed=len(failed_tasks))
            
            # For now, continue with partial success
            # In production, you might want different behavior
        
        return published_ids

    async def add_to_batch(
        self,
        task_type: TaskType,
        payload: Dict[str, Any],
        **kwargs
    ):
        """Add task to batch queue for later publishing.
        
        Tasks will be automatically published when batch size is reached
        or after a timeout period.
        
        Args:
            task_type: Type of task to add
            payload: Task-specific data
            **kwargs: Additional task parameters
        """
        async with self._batch_lock:
            # Create task message
            task = TaskMessage(
                task_type=task_type,
                payload=payload,
                **kwargs
            )
            
            self._batch_queue.append(task)
            
            logger.debug("task_added_to_batch", 
                        task_id=task.task_id,
                        batch_size=len(self._batch_queue))
            
            # Auto-publish if batch is full
            if len(self._batch_queue) >= self.stream_config.batch_size:
                await self._publish_batch()
            
            # Schedule batch timer if not already running
            elif self._batch_timer is None or self._batch_timer.done():
                self._batch_timer = asyncio.create_task(
                    self._batch_timer_handler()
                )

    async def _batch_timer_handler(self):
        """Handle batch publishing timer."""
        try:
            await asyncio.sleep(self.stream_config.max_batch_wait_ms / 1000.0)
            async with self._batch_lock:
                if self._batch_queue:
                    await self._publish_batch()
        except asyncio.CancelledError:
            pass  # Timer was cancelled, which is normal

    async def _publish_batch(self):
        """Publish queued batch tasks."""
        if not self._batch_queue:
            return
        
        tasks_to_publish = self._batch_queue.copy()
        self._batch_queue.clear()
        
        # Cancel timer if running
        if self._batch_timer and not self._batch_timer.done():
            self._batch_timer.cancel()
        
        try:
            # Convert tasks to batch format
            task_defs = []
            for task in tasks_to_publish:
                task_def = {
                    "task_type": task.task_type,
                    "payload": task.payload,
                    "priority": task.priority,
                    "user_id": task.user_id,
                    "site_id": task.site_id,
                    "parent_task_id": task.parent_task_id,
                    "dependencies": task.dependencies,
                    "timeout_seconds": task.timeout_seconds,
                    "max_retries": task.max_retries
                }
                task_defs.append(task_def)
            
            published_ids = await self.publish_task_batch(task_defs)
            
            logger.info("batch_published",
                       batch_size=len(tasks_to_publish),
                       published_count=len(published_ids))
                       
        except Exception as e:
            logger.error("batch_publish_failed", 
                        batch_size=len(tasks_to_publish),
                        error=str(e))
            
            # Re-add failed tasks to queue for retry
            self._batch_queue.extend(tasks_to_publish)

    async def flush_batch(self) -> List[str]:
        """Force publish any queued batch tasks.
        
        Returns:
            List of published task IDs
        """
        async with self._batch_lock:
            if self._batch_queue:
                await self._publish_batch()
                return [task.task_id for task in self._batch_queue]
            return []

    async def publish_result(
        self,
        task_id: str,
        status: str,
        result_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        processing_time_seconds: Optional[float] = None,
        agent_id: Optional[str] = None
    ) -> str:
        """Publish task result to results stream.
        
        Args:
            task_id: ID of completed task
            status: Task completion status
            result_data: Optional result data
            error_message: Optional error message
            processing_time_seconds: Optional processing duration
            agent_id: Optional agent identifier
            
        Returns:
            Stream entry ID
            
        Raises:
            TaskPublishError: Result publishing failed
        """
        from .models import TaskStatus
        
        result = TaskResult(
            task_id=task_id,
            status=TaskStatus(status),
            result_data=result_data,
            error_message=error_message,
            processing_time_seconds=processing_time_seconds,
            agent_id=agent_id
        )
        
        async def _publish_result():
            client = await self.redis_client
            
            stream_id = await client.xadd(
                self.stream_config.results_stream,
                result.to_redis_fields(),
                maxlen=self.stream_config.max_stream_length,
                approximate=True
            )
            
            return stream_id
        
        try:
            await self._ensure_streams_exist()
            stream_id = await self._circuit_breaker.call(_publish_result)
            
            logger.info("result_published",
                       task_id=task_id,
                       status=status,
                       stream_id=stream_id)
            
            return stream_id
            
        except (RedisError, CircuitBreakerError) as e:
            logger.error("result_publish_failed",
                        task_id=task_id,
                        error=str(e))
            raise TaskPublishError(
                f"Failed to publish result for task {task_id}: {e}",
                {"task_id": task_id, "status": status}
            )

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get task queue statistics.
        
        Returns:
            Queue statistics dictionary
        """
        try:
            client = await self.redis_client
            
            # Get stream lengths
            tasks_len = await client.xlen(self.stream_config.tasks_stream)
            results_len = await client.xlen(self.stream_config.results_stream)
            failed_len = await client.xlen(self.stream_config.failed_tasks_stream)
            
            # Get recent activity (last hour)
            one_hour_ago = int((datetime.utcnow() - timedelta(hours=1)).timestamp() * 1000)
            
            recent_tasks = await client.xrange(
                self.stream_config.tasks_stream,
                min=f"{one_hour_ago}-0",
                max="+",
                count=1000
            )
            
            stats = {
                "stream_lengths": {
                    "tasks": tasks_len,
                    "results": results_len,
                    "failed": failed_len
                },
                "recent_activity": {
                    "tasks_last_hour": len(recent_tasks)
                },
                "batch_queue_size": len(self._batch_queue),
                "circuit_breaker": {
                    "state": self._circuit_breaker.state.value,
                    "failure_count": self._circuit_breaker.failure_count
                },
                "deduplication_cache_size": len(self._deduplication_cache)
            }
            
            return stats
            
        except RedisError as e:
            logger.error("queue_stats_failed", error=str(e))
            return {"error": str(e)}

    async def close(self):
        """Clean up producer resources."""
        # Flush any remaining batch tasks
        await self.flush_batch()
        
        # Cancel batch timer
        if self._batch_timer and not self._batch_timer.done():
            self._batch_timer.cancel()
        
        # Close Redis connection
        if self._redis_client:
            await self._redis_client.aclose()
            self._redis_client = None
        
        logger.info("task_producer_closed")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
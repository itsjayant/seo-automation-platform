"""Redis Streams Task Consumer

Consumes tasks from Redis Streams with consumer group management,
automatic acknowledgment, dead letter queue handling, and health monitoring.

Provides the consumption interface for SEO agent task processing.
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional, AsyncGenerator, Callable, Awaitable
from datetime import datetime, timedelta
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
import structlog
from .models import (
    TaskMessage, 
    TaskStatus, 
    TaskResult, 
    StreamConfig, 
    ConsumerHealth
)
from .exceptions import (
    QueueConnectionError,
    TaskProcessingError,
    ConsumerGroupError,
    RetryExhaustedException,
    TaskTimeoutError,
    CircuitBreakerError
)
from .utils import (
    CircuitBreaker,
    RetryPolicy,
    sanitize_consumer_name,
    parse_stream_id,
    format_stream_id
)

logger = structlog.get_logger()


class TaskConsumer:
    """Redis Streams task consumer for SEO automation.
    
    Handles task consumption with features:
    - Consumer group management
    - Automatic task acknowledgment
    - Dead letter queue for failed tasks
    - Health monitoring and recovery
    - Configurable retry policies
    """

    def __init__(
        self,
        consumer_name: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
        stream_config: Optional[StreamConfig] = None,
        auto_acknowledge: bool = True
    ):
        """Initialize task consumer.
        
        Args:
            consumer_name: Unique consumer identifier
            redis_client: Optional Redis client instance
            stream_config: Optional stream configuration
            auto_acknowledge: Automatically acknowledge processed tasks
        """
        from config import get_settings
        
        self.settings = get_settings()
        self.redis_config = self.settings.redis
        self.stream_config = stream_config or StreamConfig()
        self.auto_acknowledge = auto_acknowledge
        
        # Consumer identity
        import socket
        import os
        hostname = socket.gethostname()
        pid = os.getpid()
        
        self.consumer_name = sanitize_consumer_name(
            consumer_name or f"{hostname}-{pid}"
        )
        self.consumer_id = f"{self.stream_config.consumer_name_prefix}-{self.consumer_name}"
        
        self._redis_client = redis_client
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30,
            expected_exception=(RedisError, QueueConnectionError),
            name=f"task_consumer_{self.consumer_id}"
        )
        self._retry_policy = RetryPolicy(
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            backoff_factor=2.0
        )
        
        # Consumer state
        self._running = False
        self._health = ConsumerHealth(
            consumer_id=self.consumer_id,
            consumer_group=self.stream_config.consumer_group
        )
        self._start_time = datetime.utcnow()
        
        # Task processing state
        self._current_task_id: Optional[str] = None
        self._task_handlers: Dict[str, Callable] = {}
        
        # Heartbeat and monitoring
        self._heartbeat_interval = 30.0  # seconds
        self._heartbeat_task: Optional[asyncio.Task] = None

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
                
                logger.info("consumer_redis_connection_established",
                           consumer_id=self.consumer_id,
                           host=self.redis_config.host,
                           port=self.redis_config.port)
                
            except RedisError as e:
                logger.error("consumer_redis_connection_failed", 
                            consumer_id=self.consumer_id,
                            error=str(e))
                raise QueueConnectionError(
                    f"Consumer {self.consumer_id} failed to connect to Redis: {e}",
                    {"consumer_id": self.consumer_id, "redis_url": self.redis_config.connection_url}
                )
        
        return self._redis_client

    async def _ensure_consumer_group_exists(self):
        """Ensure consumer group exists for the tasks stream."""
        client = await self.redis_client
        
        try:
            # Try to create consumer group
            await client.xgroup_create(
                self.stream_config.tasks_stream,
                self.stream_config.consumer_group,
                id="0",  # Start from beginning
                mkstream=True  # Create stream if it doesn't exist
            )
            logger.info("consumer_group_created",
                       group=self.stream_config.consumer_group,
                       stream=self.stream_config.tasks_stream)
                       
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Consumer group already exists
                logger.debug("consumer_group_exists",
                            group=self.stream_config.consumer_group)
            else:
                logger.error("consumer_group_creation_failed",
                            group=self.stream_config.consumer_group,
                            error=str(e))
                raise ConsumerGroupError(
                    f"Failed to create consumer group {self.stream_config.consumer_group}: {e}",
                    {"consumer_group": self.stream_config.consumer_group}
                )

    async def _claim_stale_messages(self):
        """Claim messages from other consumers that may have failed."""
        client = await self.redis_client
        
        try:
            # Get pending messages older than claim timeout
            pending_info = await client.xpending_range(
                self.stream_config.tasks_stream,
                self.stream_config.consumer_group,
                min="-",
                max="+",
                count=100,
                idle=self.stream_config.claim_timeout_ms
            )
            
            if pending_info:
                # Extract message IDs
                message_ids = [info["message_id"] for info in pending_info]
                
                # Claim the messages
                claimed = await client.xclaim(
                    self.stream_config.tasks_stream,
                    self.stream_config.consumer_group,
                    self.consumer_id,
                    min_idle_time=self.stream_config.claim_timeout_ms,
                    message_ids=message_ids
                )
                
                if claimed:
                    logger.info("stale_messages_claimed",
                               consumer_id=self.consumer_id,
                               count=len(claimed))
                    
                    return claimed
            
            return []
            
        except RedisError as e:
            logger.warning("stale_message_claim_failed",
                          consumer_id=self.consumer_id,
                          error=str(e))
            return []

    async def _process_task_message(
        self,
        message_id: str,
        fields: Dict[str, str],
        task_handler: Optional[Callable] = None
    ) -> bool:
        """Process a single task message.
        
        Args:
            message_id: Redis Stream message ID
            fields: Message field data
            task_handler: Optional custom task handler
            
        Returns:
            True if task processed successfully
        """
        try:
            # Parse task from Redis fields
            task = TaskMessage.from_redis_fields(message_id, fields)
            self._current_task_id = task.task_id
            
            logger.info("task_processing_started",
                       task_id=task.task_id,
                       task_type=task.task_type.value,
                       consumer_id=self.consumer_id)
            
            # Check if task is expired
            if task.is_expired:
                await self._handle_expired_task(message_id, task)
                return False
            
            # Update task to processing state
            task.assigned_to = self.consumer_id
            task.started_at = datetime.utcnow()
            
            start_time = time.time()
            
            try:
                # Use custom handler or default handler
                if task_handler:
                    result = await task_handler(task)
                elif task.task_type.value in self._task_handlers:
                    result = await self._task_handlers[task.task_type.value](task)
                else:
                    # Default handler - log and acknowledge
                    logger.info("task_processed_default",
                               task_id=task.task_id,
                               task_type=task.task_type.value)
                    result = {"status": "processed", "handler": "default"}
                
                processing_time = time.time() - start_time
                
                # Publish successful result
                from .producer import TaskProducer
                producer = TaskProducer(self._redis_client, self.stream_config)
                
                await producer.publish_result(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED.value,
                    result_data=result,
                    processing_time_seconds=processing_time,
                    agent_id=self.consumer_id
                )
                
                # Update health stats
                self._health.tasks_processed += 1
                
                logger.info("task_processing_completed",
                           task_id=task.task_id,
                           processing_time=processing_time,
                           consumer_id=self.consumer_id)
                
                return True
                
            except Exception as e:
                processing_time = time.time() - start_time
                
                logger.error("task_processing_failed",
                            task_id=task.task_id,
                            error=str(e),
                            processing_time=processing_time,
                            consumer_id=self.consumer_id)
                
                # Handle failure based on retry policy
                await self._handle_failed_task(message_id, task, str(e))
                
                # Update health stats
                self._health.tasks_failed += 1
                
                return False
                
        except Exception as e:
            logger.error("task_message_processing_error",
                        message_id=message_id,
                        error=str(e),
                        consumer_id=self.consumer_id)
            return False
        finally:
            self._current_task_id = None

    async def _handle_failed_task(self, message_id: str, task: TaskMessage, error_message: str):
        """Handle a failed task with retry logic.
        
        Args:
            message_id: Redis Stream message ID
            task: Failed task
            error_message: Error description
        """
        task.retry_count += 1
        task.error_message = error_message
        
        if task.can_retry:
            logger.info("task_retry_scheduled",
                       task_id=task.task_id,
                       retry_count=task.retry_count,
                       max_retries=task.max_retries)
            
            # Calculate retry delay
            retry_delay = self._retry_policy.calculate_delay(task.retry_count)
            
            # Re-publish task for retry (with updated retry count)
            from .producer import TaskProducer
            producer = TaskProducer(self._redis_client, self.stream_config)
            
            # Schedule retry after delay
            await asyncio.sleep(retry_delay)
            
            await producer.publish_task(
                task_type=task.task_type,
                payload=task.payload,
                priority=task.priority,
                user_id=task.user_id,
                site_id=task.site_id,
                parent_task_id=task.parent_task_id,
                dependencies=task.dependencies,
                timeout_seconds=task.timeout_seconds,
                max_retries=task.max_retries,
                skip_deduplication=True  # Allow retry
            )
            
            # Publish retry result 
            await producer.publish_result(
                task_id=task.task_id,
                status=TaskStatus.RETRYING.value,
                error_message=error_message,
                agent_id=self.consumer_id
            )
            
        else:
            # Move to dead letter queue
            await self._move_to_dead_letter(task, error_message)

    async def _handle_expired_task(self, message_id: str, task: TaskMessage):
        """Handle a task that has exceeded its timeout.
        
        Args:
            message_id: Redis Stream message ID  
            task: Expired task
        """
        elapsed = (datetime.utcnow() - task.started_at).total_seconds() if task.started_at else 0
        
        logger.warning("task_expired",
                      task_id=task.task_id,
                      timeout_seconds=task.timeout_seconds,
                      elapsed_seconds=elapsed,
                      consumer_id=self.consumer_id)
        
        error_message = f"Task timed out after {elapsed:.1f}s (limit: {task.timeout_seconds}s)"
        
        # Move to dead letter queue
        await self._move_to_dead_letter(task, error_message)

    async def _move_to_dead_letter(self, task: TaskMessage, error_message: str):
        """Move failed task to dead letter queue.
        
        Args:
            task: Task to move to dead letter queue
            error_message: Failure reason
        """
        try:
            client = await self.redis_client
            
            # Add to dead letter stream
            dead_fields = task.to_redis_fields()
            dead_fields.update({
                "dead_letter_reason": error_message,
                "dead_letter_timestamp": datetime.utcnow().isoformat(),
                "final_consumer_id": self.consumer_id
            })
            
            await client.xadd(
                self.stream_config.failed_tasks_stream,
                dead_fields,
                maxlen=self.stream_config.max_stream_length,
                approximate=True
            )
            
            # Publish dead letter result
            from .producer import TaskProducer
            producer = TaskProducer(self._redis_client, self.stream_config)
            
            await producer.publish_result(
                task_id=task.task_id,
                status=TaskStatus.DEAD_LETTER.value,
                error_message=error_message,
                agent_id=self.consumer_id
            )
            
            logger.warning("task_moved_to_dead_letter",
                          task_id=task.task_id,
                          error_message=error_message,
                          consumer_id=self.consumer_id)
            
        except RedisError as e:
            logger.error("dead_letter_move_failed",
                        task_id=task.task_id,
                        error=str(e),
                        consumer_id=self.consumer_id)
            raise TaskProcessingError(
                f"Failed to move task {task.task_id} to dead letter queue: {e}",
                {"task_id": task.task_id, "consumer_id": self.consumer_id}
            )

    async def acknowledge_task(self, message_id: str) -> bool:
        """Acknowledge task completion.
        
        Args:
            message_id: Redis Stream message ID to acknowledge
            
        Returns:
            True if acknowledgment successful
        """
        try:
            client = await self.redis_client
            
            ack_count = await client.xack(
                self.stream_config.tasks_stream,
                self.stream_config.consumer_group,
                message_id
            )
            
            if ack_count > 0:
                logger.debug("task_acknowledged",
                            message_id=message_id,
                            consumer_id=self.consumer_id)
                return True
            else:
                logger.warning("task_acknowledge_failed",
                              message_id=message_id,
                              consumer_id=self.consumer_id)
                return False
                
        except RedisError as e:
            logger.error("task_acknowledge_error",
                        message_id=message_id,
                        error=str(e),
                        consumer_id=self.consumer_id)
            return False

    def register_task_handler(self, task_type: str, handler: Callable[[TaskMessage], Awaitable[Any]]):
        """Register a handler for specific task types.
        
        Args:
            task_type: Task type to handle
            handler: Async function to process tasks
        """
        self._task_handlers[task_type] = handler
        logger.info("task_handler_registered",
                   task_type=task_type,
                   consumer_id=self.consumer_id)

    async def consume_tasks(
        self,
        task_handler: Optional[Callable] = None,
        count: int = 1
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Consume tasks from the queue stream.
        
        Args:
            task_handler: Optional custom task handler
            count: Number of messages to read per batch
            
        Yields:
            Task processing results
        """
        await self._ensure_consumer_group_exists()
        
        # Claim any stale messages first
        stale_messages = await self._claim_stale_messages()
        for message_id, fields in stale_messages:
            success = await self._process_task_message(message_id, fields, task_handler)
            if success and self.auto_acknowledge:
                await self.acknowledge_task(message_id)
            
            yield {
                "message_id": message_id,
                "success": success,
                "claimed": True
            }
        
        # Start consuming new messages
        self._running = True
        
        logger.info("consumer_started",
                   consumer_id=self.consumer_id,
                   consumer_group=self.stream_config.consumer_group)
        
        while self._running:
            try:
                async def _read_messages():
                    client = await self.redis_client
                    
                    messages = await client.xreadgroup(
                        self.stream_config.consumer_group,
                        self.consumer_id,
                        {self.stream_config.tasks_stream: ">"},
                        count=count,
                        block=self.stream_config.block_timeout_ms
                    )
                    
                    return messages
                
                messages = await self._circuit_breaker.call(_read_messages)
                
                # Process each message
                for stream_name, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        success = await self._process_task_message(
                            message_id, fields, task_handler
                        )
                        
                        if success and self.auto_acknowledge:
                            await self.acknowledge_task(message_id)
                        
                        yield {
                            "message_id": message_id,
                            "success": success,
                            "claimed": False
                        }
                
            except CircuitBreakerError:
                logger.warning("consumer_circuit_breaker_open",
                              consumer_id=self.consumer_id)
                await asyncio.sleep(5)  # Wait before retrying
                
            except RedisError as e:
                logger.error("consumer_redis_error",
                            consumer_id=self.consumer_id,
                            error=str(e))
                await asyncio.sleep(1)  # Brief pause before retry
                
            except Exception as e:
                logger.error("consumer_unexpected_error",
                            consumer_id=self.consumer_id,
                            error=str(e))
                await asyncio.sleep(1)

    async def _start_heartbeat(self):
        """Start consumer heartbeat for health monitoring.""" 
        async def heartbeat_loop():
            while self._running:
                try:
                    self._health.last_heartbeat = datetime.utcnow()
                    self._health.uptime_seconds = (
                        datetime.utcnow() - self._start_time
                    ).total_seconds()
                    
                    # Could publish heartbeat to monitoring stream
                    logger.debug("consumer_heartbeat",
                                consumer_id=self.consumer_id,
                                uptime=self._health.uptime_seconds)
                    
                    await asyncio.sleep(self._heartbeat_interval)
                    
                except Exception as e:
                    logger.error("heartbeat_error",
                                consumer_id=self.consumer_id,
                                error=str(e))
                    await asyncio.sleep(self._heartbeat_interval)
        
        self._heartbeat_task = asyncio.create_task(heartbeat_loop())

    async def start(self, task_handler: Optional[Callable] = None) -> AsyncGenerator:
        """Start the consumer and begin processing tasks.
        
        Args:
            task_handler: Optional custom task handler
            
        Yields:
            Task processing results
        """
        await self._start_heartbeat()
        
        try:
            async for result in self.consume_tasks(task_handler):
                yield result
        finally:
            await self.stop()

    async def stop(self):
        """Stop the consumer and clean up resources."""
        self._running = False
        
        # Stop heartbeat
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Mark consumer as inactive
        self._health.is_active = False
        
        logger.info("consumer_stopped",
                   consumer_id=self.consumer_id,
                   tasks_processed=self._health.tasks_processed,
                   tasks_failed=self._health.tasks_failed,
                   success_rate=self._health.success_rate)

    async def get_health_status(self) -> ConsumerHealth:
        """Get current consumer health status.
        
        Returns:
            Consumer health information
        """
        self._health.uptime_seconds = (
            datetime.utcnow() - self._start_time
        ).total_seconds()
        
        return self._health.model_copy()

    async def get_consumer_info(self) -> Dict[str, Any]:
        """Get consumer information and statistics.
        
        Returns:
            Consumer information dictionary
        """
        try:
            client = await self.redis_client
            
            # Get consumer group info
            group_info = await client.xinfo_consumers(
                self.stream_config.tasks_stream,
                self.stream_config.consumer_group
            )
            
            # Find this consumer's info
            consumer_info = None
            for info in group_info:
                if info["name"] == self.consumer_id:
                    consumer_info = info
                    break
            
            return {
                "consumer_id": self.consumer_id,
                "consumer_group": self.stream_config.consumer_group,
                "running": self._running,
                "current_task_id": self._current_task_id,
                "health": self._health.model_dump(),
                "redis_info": consumer_info,
                "registered_handlers": list(self._task_handlers.keys())
            }
            
        except RedisError as e:
            logger.error("consumer_info_failed",
                        consumer_id=self.consumer_id,
                        error=str(e))
            return {
                "consumer_id": self.consumer_id,
                "error": str(e)
            }

    async def close(self):
        """Clean up consumer resources."""
        await self.stop()
        
        # Close Redis connection
        if self._redis_client:
            await self._redis_client.aclose()
            self._redis_client = None
        
        logger.info("consumer_closed", consumer_id=self.consumer_id)

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
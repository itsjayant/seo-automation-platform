"""Queue-specific Exceptions

Custom exception classes for Redis Streams task queue operations.
Provides detailed error context for different failure scenarios.
"""

from typing import Optional, Dict, Any


class QueueError(Exception):
    """Base exception for all queue-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class QueueConnectionError(QueueError):
    """Redis connection or communication errors.
    
    Raised when Redis is unavailable, network issues occur,
    or authentication fails.
    """
    pass


class TaskValidationError(QueueError):
    """Task data validation errors.
    
    Raised when task payload is invalid, missing required fields,
    or exceeds size limits.
    """
    pass


class TaskPublishError(QueueError):
    """Task publishing errors.
    
    Raised when tasks cannot be published to Redis Streams,
    stream limits are exceeded, or deduplication conflicts occur.
    """
    pass


class TaskProcessingError(QueueError):
    """Task processing and execution errors.
    
    Raised during task execution, timeout handling,
    or result publishing failures.
    """
    pass


class ConsumerGroupError(QueueError):
    """Consumer group management errors.
    
    Raised during consumer group creation, consumer registration,
    or group coordination failures.
    """
    pass


class DeadLetterError(QueueError):
    """Dead letter queue handling errors.
    
    Raised when moving tasks to dead letter queue fails
    or dead letter processing encounters issues.
    """
    pass


class CircuitBreakerError(QueueError):
    """Circuit breaker state errors.
    
    Raised when circuit breaker is open and operations
    are being blocked to prevent cascade failures.
    """
    pass


class RetryExhaustedException(QueueError):
    """Task retry attempts exhausted.
    
    Raised when a task has failed maximum number of times
    and will be moved to dead letter queue.
    """
    
    def __init__(self, task_id: str, retry_count: int, max_retries: int, last_error: str):
        message = f"Task {task_id} exhausted {retry_count}/{max_retries} retries: {last_error}"
        super().__init__(message, {
            "task_id": task_id,
            "retry_count": retry_count,
            "max_retries": max_retries,
            "last_error": last_error
        })
        self.task_id = task_id
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.last_error = last_error


class TaskTimeoutError(QueueError):
    """Task execution timeout errors.
    
    Raised when task processing exceeds the configured timeout
    and needs to be reclaimed or moved to dead letter queue.
    """
    
    def __init__(self, task_id: str, timeout_seconds: int, elapsed_seconds: int):
        message = f"Task {task_id} timed out after {elapsed_seconds}s (limit: {timeout_seconds}s)"
        super().__init__(message, {
            "task_id": task_id,
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": elapsed_seconds
        })
        self.task_id = task_id
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds


class DuplicateTaskError(QueueError):
    """Duplicate task detection errors.
    
    Raised when attempting to publish a task that already exists
    in the queue based on content hash deduplication.
    """
    
    def __init__(self, content_hash: str, existing_task_id: str):
        message = f"Task with hash {content_hash} already exists as {existing_task_id}"
        super().__init__(message, {
            "content_hash": content_hash,
            "existing_task_id": existing_task_id
        })
        self.content_hash = content_hash
        self.existing_task_id = existing_task_id
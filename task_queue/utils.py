"""Queue Utility Functions

Utility functions for task ID generation, hashing, circuit breaker pattern,
retry policies, and other queue operations.
"""

import hashlib
import json
import asyncio
import time
from typing import Dict, Any, Optional, Callable, Awaitable
from uuid import uuid4
from datetime import datetime, timedelta
from enum import Enum
import structlog

from .exceptions import CircuitBreakerError

logger = structlog.get_logger()


def generate_task_id() -> str:
    """Generate a unique task ID.
    
    Returns:
        UUID-based task identifier
    """
    return str(uuid4())


def calculate_task_hash(task_type: str, payload: Dict[str, Any]) -> str:
    """Calculate content hash for task deduplication.
    
    Args:
        task_type: Type of task
        payload: Task payload data
        
    Returns:
        SHA256 hash of task content
    """
    content = {
        "task_type": task_type,
        "payload": payload
    }
    content_str = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(content_str.encode()).hexdigest()


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"    # Normal operation
    OPEN = "open"        # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker pattern for Redis connection reliability.
    
    Prevents cascade failures by monitoring error rates and temporarily
    blocking operations when Redis is experiencing issues.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        expected_exception: type = Exception,
        name: str = "redis_circuit_breaker"
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name
        
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = CircuitBreakerState.CLOSED
        
    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state
    
    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count
    
    def _can_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self._last_failure_time is None:
            return True
        return time.time() - self._last_failure_time >= self.recovery_timeout
    
    def _update_state(self):
        """Update circuit breaker state based on current conditions."""
        if self._state == CircuitBreakerState.OPEN and self._can_attempt_reset():
            self._state = CircuitBreakerState.HALF_OPEN
            logger.info("circuit_breaker_half_open", name=self.name)
    
    def _on_success(self):
        """Handle successful operation."""
        self._failure_count = 0
        self._last_failure_time = None
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.CLOSED
            logger.info("circuit_breaker_closed", name=self.name)
    
    def _on_failure(self):
        """Handle failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._failure_count >= self.failure_threshold:
            if self._state == CircuitBreakerState.CLOSED:
                self._state = CircuitBreakerState.OPEN
                logger.warning(
                    "circuit_breaker_opened",
                    name=self.name,
                    failure_count=self._failure_count
                )
            elif self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.OPEN
                logger.warning(
                    "circuit_breaker_reopened",
                    name=self.name,
                    failure_count=self._failure_count
                )
    
    async def call(self, func: Callable[[], Awaitable[Any]]) -> Any:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: When circuit breaker is open
            Exception: Original function exceptions
        """
        self._update_state()
        
        if self._state == CircuitBreakerState.OPEN:
            raise CircuitBreakerError(
                f"Circuit breaker {self.name} is open",
                {
                    "failure_count": self._failure_count,
                    "last_failure_time": self._last_failure_time
                }
            )
        
        try:
            result = await func()
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def reset(self):
        """Manually reset circuit breaker to closed state."""
        self._failure_count = 0
        self._last_failure_time = None
        self._state = CircuitBreakerState.CLOSED
        logger.info("circuit_breaker_reset", name=self.name)


class RetryPolicy:
    """Retry policy with exponential backoff.
    
    Manages retry attempts with configurable backoff strategies
    for reliable task processing.
    """
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter: bool = True
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number.
        
        Args:
            attempt: Attempt number (0-indexed)
            
        Returns:
            Delay in seconds
        """
        if attempt <= 0:
            return 0.0
        
        # Exponential backoff: base_delay * (backoff_factor ^ (attempt - 1))
        delay = self.base_delay * (self.backoff_factor ** (attempt - 1))
        
        # Cap at max_delay
        delay = min(delay, self.max_delay)
        
        # Add jitter to prevent thundering herd
        if self.jitter:
            import random
            jitter = random.uniform(0.1, 0.9)
            delay = delay * jitter
        
        return delay
    
    async def execute_with_retry(
        self,
        func: Callable[[], Awaitable[Any]],
        on_retry: Optional[Callable[[int, Exception], Awaitable[None]]] = None
    ) -> Any:
        """Execute function with retry logic.
        
        Args:
            func: Async function to execute
            on_retry: Optional callback on retry attempts
            
        Returns:
            Function result
            
        Raises:
            Exception: Last exception after all retries exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_attempts):
            try:
                return await func()
            except Exception as e:
                last_exception = e
                
                if attempt == self.max_attempts - 1:
                    # Last attempt failed, raise the exception
                    break
                
                # Calculate delay and wait
                delay = self.calculate_delay(attempt + 1)
                
                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    max_attempts=self.max_attempts,
                    delay=delay,
                    error=str(e)
                )
                
                if on_retry:
                    await on_retry(attempt + 1, e)
                
                await asyncio.sleep(delay)
        
        # All attempts failed
        raise last_exception


def sanitize_consumer_name(name: str) -> str:
    """Sanitize consumer name for Redis compatibility.
    
    Args:
        name: Raw consumer name
        
    Returns:
        Sanitized consumer name safe for Redis
    """
    # Replace invalid characters with underscores
    sanitized = ""
    for char in name:
        if char.isalnum() or char in "-_":
            sanitized += char
        else:
            sanitized += "_"
    
    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = "c_" + sanitized
    
    # Limit length
    return sanitized[:64]


def format_stream_id(timestamp: Optional[datetime] = None) -> str:
    """Format timestamp for Redis Stream ID.
    
    Args:
        timestamp: Optional timestamp (defaults to now)
        
    Returns:
        Redis Stream ID format (timestamp-sequence)
    """
    if timestamp is None:
        timestamp = datetime.utcnow()
    
    # Convert to milliseconds since epoch
    millis = int(timestamp.timestamp() * 1000)
    return f"{millis}-0"


def parse_stream_id(stream_id: str) -> datetime:
    """Parse Redis Stream ID to datetime.
    
    Args:
        stream_id: Redis Stream ID (timestamp-sequence)
        
    Returns:
        Parsed datetime
    """
    timestamp_part = stream_id.split("-")[0]
    millis = int(timestamp_part)
    return datetime.utcfromtimestamp(millis / 1000.0)


def calculate_priority_score(priority: str, created_at: datetime) -> float:
    """Calculate numeric priority score for task ordering.
    
    Higher scores indicate higher priority. Age is factored in to prevent
    starvation of lower priority tasks.
    
    Args:
        priority: Task priority (high/medium/low)
        created_at: Task creation timestamp
        
    Returns:
        Numeric priority score
    """
    priority_weights = {
        "high": 1000,
        "medium": 100, 
        "low": 10
    }
    
    base_score = priority_weights.get(priority.lower(), 1)
    
    # Add age factor (1 point per hour)
    age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600
    age_score = min(age_hours, 100)  # Cap at 100 hours
    
    return base_score + age_score
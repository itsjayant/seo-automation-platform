"""Exponential Backoff with Jitter for API Rate Limiting

Production-grade backoff strategies for external API integrations with
rate limit consideration and circuit breaker coordination.
"""

import asyncio
import random
import time
from typing import Optional, Union, Callable, Any, Type
from dataclasses import dataclass
from datetime import datetime, timedelta
import structlog
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)


@dataclass
class BackoffConfig:
    """Configuration for exponential backoff strategy."""
    
    # Base configuration
    base_delay: float = 1.0          # Initial delay in seconds
    max_delay: float = 300.0         # Maximum delay (5 minutes)
    max_attempts: int = 5            # Maximum retry attempts
    backoff_factor: float = 2.0      # Exponential multiplier
    
    # Jitter configuration
    jitter_type: str = "full"        # "none", "equal", "full", "decorrelated"
    jitter_factor: float = 1.0       # Jitter randomization factor
    
    # Rate limit integration
    respect_rate_limits: bool = True # Honor rate limit headers
    rate_limit_buffer: float = 1.1   # Buffer multiplier for rate limit delays
    
    # Exception handling
    retryable_exceptions: tuple = (
        ConnectionError,
        TimeoutError,
        RedisError,
    )
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.backoff_factor <= 1:
            raise ValueError("backoff_factor must be > 1")
        if self.jitter_type not in ["none", "equal", "full", "decorrelated"]:
            raise ValueError("Invalid jitter_type")


class ExponentialBackoff:
    """Exponential backoff implementation with jitter and rate limit integration.
    
    Features:
    - Multiple jitter strategies to prevent thundering herd
    - Rate limit header integration
    - Circuit breaker coordination
    - Detailed retry metrics and logging
    - Configurable exception handling
    """

    def __init__(self, config: Optional[BackoffConfig] = None):
        """Initialize backoff strategy.
        
        Args:
            config: Backoff configuration, uses defaults if None
        """
        self.config = config or BackoffConfig()
        self._attempt_count = 0
        self._total_delay = 0.0
        self._start_time: Optional[float] = None
        self._last_delay: Optional[float] = None

    @property
    def attempt_count(self) -> int:
        """Get current attempt count."""
        return self._attempt_count

    @property
    def total_delay(self) -> float:
        """Get total delay accumulated."""
        return self._total_delay

    @property
    def elapsed_time(self) -> float:
        """Get total elapsed time since first attempt."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def reset(self):
        """Reset backoff state for new operation."""
        self._attempt_count = 0
        self._total_delay = 0.0
        self._start_time = None
        self._last_delay = None

    def _calculate_base_delay(self, attempt: int) -> float:
        """Calculate base exponential delay for attempt."""
        return min(
            self.config.base_delay * (self.config.backoff_factor ** attempt),
            self.config.max_delay
        )

    def _apply_jitter(self, delay: float, attempt: int) -> float:
        """Apply jitter to delay based on configuration."""
        if self.config.jitter_type == "none":
            return delay
        
        elif self.config.jitter_type == "equal":
            # Equal jitter: delay ± (delay * jitter_factor / 2)
            jitter_range = delay * self.config.jitter_factor / 2
            return delay + random.uniform(-jitter_range, jitter_range)
        
        elif self.config.jitter_type == "full":
            # Full jitter: random value between 0 and delay
            return random.uniform(0, delay * self.config.jitter_factor)
        
        elif self.config.jitter_type == "decorrelated":
            # Decorrelated jitter: based on previous delay
            if self._last_delay is None:
                return random.uniform(0, delay)
            
            # Use decorrelated formula: random(base_delay, last_delay * 3)
            min_delay = self.config.base_delay
            max_delay = min(self._last_delay * 3, self.config.max_delay)
            return random.uniform(min_delay, max_delay)
        
        else:
            return delay

    def _extract_rate_limit_delay(self, exception: Exception) -> Optional[float]:
        """Extract rate limit delay from exception or headers."""
        # Check for rate limit information in exception
        if hasattr(exception, 'retry_after'):
            retry_after = getattr(exception, 'retry_after')
            if retry_after:
                try:
                    delay = float(retry_after)
                    return delay * self.config.rate_limit_buffer
                except (ValueError, TypeError):
                    pass
        
        # Check for HTTP response headers if available
        if hasattr(exception, 'response') and exception.response:
            response = exception.response
            
            # Standard Retry-After header
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    return float(retry_after) * self.config.rate_limit_buffer
                except ValueError:
                    # Might be a date string, parse it
                    try:
                        retry_date = datetime.fromisoformat(retry_after.replace('Z', '+00:00'))
                        delay = (retry_date - datetime.utcnow()).total_seconds()
                        return max(0, delay * self.config.rate_limit_buffer)
                    except ValueError:
                        pass
            
            # X-RateLimit headers
            reset_time = response.headers.get('X-RateLimit-Reset')
            if reset_time:
                try:
                    reset_timestamp = int(reset_time)
                    delay = reset_timestamp - time.time()
                    return max(0, delay * self.config.rate_limit_buffer)
                except (ValueError, TypeError):
                    pass
        
        return None

    def calculate_delay(self, exception: Optional[Exception] = None) -> float:
        """Calculate next delay considering rate limits and backoff strategy.
        
        Args:
            exception: Optional exception that triggered the retry
            
        Returns:
            Delay in seconds before next attempt
        """
        if self._start_time is None:
            self._start_time = time.time()

        # Check if we should respect rate limit delays
        rate_limit_delay = None
        if self.config.respect_rate_limits and exception:
            rate_limit_delay = self._extract_rate_limit_delay(exception)

        # Calculate exponential backoff delay
        backoff_delay = self._calculate_base_delay(self._attempt_count)
        backoff_delay = self._apply_jitter(backoff_delay, self._attempt_count)

        # Use the larger of rate limit delay or backoff delay
        if rate_limit_delay is not None:
            delay = max(rate_limit_delay, backoff_delay)
            logger.info(
                "backoff_rate_limit_delay",
                rate_limit_delay=rate_limit_delay,
                backoff_delay=backoff_delay,
                chosen_delay=delay,
                attempt=self._attempt_count + 1
            )
        else:
            delay = backoff_delay

        # Ensure delay doesn't exceed maximum
        delay = min(delay, self.config.max_delay)
        
        self._last_delay = delay
        return delay

    def should_retry(self, exception: Exception) -> bool:
        """Determine if operation should be retried.
        
        Args:
            exception: Exception that occurred
            
        Returns:
            True if retry should be attempted
        """
        # Check attempt limit
        if self._attempt_count >= self.config.max_attempts:
            return False
        
        # Check if exception is retryable
        if not isinstance(exception, self.config.retryable_exceptions):
            return False
        
        return True

    async def wait(self, exception: Optional[Exception] = None) -> float:
        """Wait for calculated backoff delay.
        
        Args:
            exception: Exception that triggered the wait
            
        Returns:
            Actual delay time waited
        """
        delay = self.calculate_delay(exception)
        
        logger.info(
            "backoff_waiting",
            delay=delay,
            attempt=self._attempt_count + 1,
            max_attempts=self.config.max_attempts,
            elapsed_time=self.elapsed_time,
            total_delay=self._total_delay
        )
        
        await asyncio.sleep(delay)
        
        self._attempt_count += 1
        self._total_delay += delay
        
        return delay

    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute function with exponential backoff retry logic.
        
        Args:
            func: Function to execute (can be async or sync)
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: Last exception if all retries exhausted
        """
        self.reset()
        last_exception = None
        
        while True:
            try:
                # Execute function
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                # Success - log metrics and return
                if self._attempt_count > 0:
                    logger.info(
                        "backoff_success",
                        attempts=self._attempt_count + 1,
                        total_delay=self._total_delay,
                        elapsed_time=self.elapsed_time
                    )
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # Check if we should retry
                if not self.should_retry(e):
                    logger.error(
                        "backoff_exhausted",
                        exception=str(e),
                        exception_type=type(e).__name__,
                        attempts=self._attempt_count + 1,
                        total_delay=self._total_delay,
                        elapsed_time=self.elapsed_time
                    )
                    raise e
                
                # Wait before retry
                await self.wait(e)

    def __call__(self, func: Callable) -> Callable:
        """Decorator interface for backoff retry."""
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                return await self.execute_with_retry(func, *args, **kwargs)
            return async_wrapper
        else:
            async def sync_wrapper(*args, **kwargs):
                return await self.execute_with_retry(func, *args, **kwargs)
            return sync_wrapper


def create_api_backoff(
    service_name: str,
    base_delay: float = 1.0,
    max_attempts: int = 3
) -> ExponentialBackoff:
    """Create preconfigured backoff for API services.
    
    Args:
        service_name: Name of the API service (for logging)
        base_delay: Base delay in seconds
        max_attempts: Maximum retry attempts
        
    Returns:
        Configured ExponentialBackoff instance
    """
    config = BackoffConfig(
        base_delay=base_delay,
        max_delay=min(300.0, base_delay * (2 ** max_attempts)),
        max_attempts=max_attempts,
        backoff_factor=2.0,
        jitter_type="full",
        respect_rate_limits=True,
        rate_limit_buffer=1.1,
        retryable_exceptions=(
            ConnectionError,
            TimeoutError,
            RedisError,
            # Add API-specific exceptions as needed
        )
    )
    
    return ExponentialBackoff(config)
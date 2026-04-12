"""Circuit Breaker Pattern for External API Reliability

Enhanced circuit breaker implementation for rate limiter integration.
Provides fail-fast behavior with configurable thresholds and recovery logic.
"""

import asyncio
import time
from enum import Enum
from typing import Optional, Type, Union, Callable, Any, Dict
from datetime import datetime, timedelta
import structlog
from threading import Lock

logger = structlog.get_logger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing fast
    HALF_OPEN = "half_open" # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class CircuitBreaker:
    """Production-grade circuit breaker with rate limiter integration.
    
    Features:
    - Configurable failure thresholds and timeouts
    - Thread-safe operation for concurrent access
    - Integration with exponential backoff
    - Detailed metrics and logging
    - Recovery monitoring and half-open state management
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        success_threshold: int = 3,
        timeout: float = 30.0,
        expected_exception: Union[Type[Exception], tuple] = Exception,
        name: str = "api_circuit_breaker"
    ):
        """Initialize circuit breaker.
        
        Args:
            failure_threshold: Failures needed to open circuit
            recovery_timeout: Seconds to wait before half-open
            success_threshold: Successes needed to close from half-open
            timeout: Operation timeout in seconds
            expected_exception: Exception types to count as failures
            name: Circuit breaker identifier for logging
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        self.name = name
        
        # Thread-safe state management
        self._lock = Lock()
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = CircuitBreakerState.CLOSED
        
        # Metrics tracking
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._state_changes: Dict[str, int] = {
            "opened": 0,
            "closed": 0,
            "half_opened": 0
        }

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        with self._lock:
            self._update_state()
            return self._state

    @property
    def metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics."""
        with self._lock:
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "total_successes": self._total_successes,
                "state_changes": self._state_changes.copy(),
                "failure_rate": self._total_failures / max(1, self._total_calls),
                "time_since_last_failure": (
                    time.time() - self._last_failure_time 
                    if self._last_failure_time else None
                )
            }

    def _can_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self._last_failure_time is None:
            return True
        return time.time() - self._last_failure_time >= self.recovery_timeout

    def _update_state(self):
        """Update circuit breaker state based on current conditions."""
        if self._state == CircuitBreakerState.OPEN and self._can_attempt_reset():
            self._state = CircuitBreakerState.HALF_OPEN
            self._success_count = 0  # Reset success counter for half-open
            self._state_changes["half_opened"] += 1
            logger.info(
                "circuit_breaker_half_open",
                name=self.name,
                failure_count=self._failure_count,
                recovery_timeout=self.recovery_timeout
            )

    def _on_success(self):
        """Handle successful operation."""
        with self._lock:
            self._total_calls += 1
            self._total_successes += 1
            
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    # Reset to closed state
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._last_failure_time = None
                    self._state_changes["closed"] += 1
                    logger.info(
                        "circuit_breaker_closed",
                        name=self.name,
                        success_count=self._success_count,
                        success_threshold=self.success_threshold
                    )
            elif self._state == CircuitBreakerState.CLOSED:
                # Reset failure count on successful operation
                self._failure_count = 0

    def _on_failure(self, exception: Exception):
        """Handle failed operation."""
        with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            # Log failure details
            logger.warning(
                "circuit_breaker_failure",
                name=self.name,
                failure_count=self._failure_count,
                exception=str(exception),
                exception_type=type(exception).__name__
            )
            
            # Check if we should open the circuit
            if (self._failure_count >= self.failure_threshold and 
                self._state != CircuitBreakerState.OPEN):
                
                self._state = CircuitBreakerState.OPEN
                self._state_changes["opened"] += 1
                logger.error(
                    "circuit_breaker_opened",
                    name=self.name,
                    failure_count=self._failure_count,
                    failure_threshold=self.failure_threshold,
                    recovery_timeout=self.recovery_timeout
                )

    def _should_allow_request(self) -> bool:
        """Check if request should be allowed."""
        with self._lock:
            self._update_state()
            
            if self._state == CircuitBreakerState.OPEN:
                return False
            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Allow limited requests in half-open state
                return True
            else:  # CLOSED
                return True

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: When circuit is open
            TimeoutError: When operation exceeds timeout
            Exception: Original function exceptions
        """
        if not self._should_allow_request():
            retry_after = (
                self.recovery_timeout - (time.time() - self._last_failure_time)
                if self._last_failure_time else self.recovery_timeout
            )
            raise CircuitBreakerError(
                f"Circuit breaker '{self.name}' is open",
                retry_after=max(0, retry_after)
            )
        
        try:
            # Execute with timeout
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs), 
                    timeout=self.timeout
                )
            else:
                result = func(*args, **kwargs)
            
            self._on_success()
            return result
            
        except asyncio.TimeoutError as e:
            self._on_failure(e)
            raise TimeoutError(f"Operation timed out after {self.timeout}s") from e
            
        except self.expected_exception as e:
            self._on_failure(e)
            raise
        
        except Exception as e:
            # Unexpected exceptions don't trigger circuit breaker
            logger.warning(
                "circuit_breaker_unexpected_exception",
                name=self.name,
                exception=str(e),
                exception_type=type(e).__name__
            )
            raise

    def __call__(self, func: Callable) -> Callable:
        """Decorator interface for circuit breaker."""
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                return await self.call(func, *args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                return asyncio.run(self.call(func, *args, **kwargs))
            return sync_wrapper

    def reset(self):
        """Manually reset circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            logger.info("circuit_breaker_reset", name=self.name)

    def force_open(self):
        """Manually force circuit breaker to open state."""
        with self._lock:
            self._state = CircuitBreakerState.OPEN
            self._last_failure_time = time.time()
            self._state_changes["opened"] += 1
            logger.warning("circuit_breaker_forced_open", name=self.name)
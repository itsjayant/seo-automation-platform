"""Agent utility functions for common operations.

Provides shared utilities for agent implementations including
telemetry helpers, configuration validation, and resource management.
"""

import time
import psutil
import asyncio
from typing import Dict, Any, Optional, Callable, TypeVar, Union
from contextlib import asynccontextmanager, contextmanager
from functools import wraps

import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .models import AgentMetrics
from .exceptions import AgentTimeoutError

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

T = TypeVar('T')


def get_agent_logger(agent_name: str, context: Optional[Dict[str, Any]] = None) -> structlog.BoundLogger:
    """Get a structured logger with agent context.
    
    Args:
        agent_name: Name of the agent for logging context
        context: Additional context to bind to the logger
        
    Returns:
        Bound logger with agent context
    """
    bound_logger = logger.bind(agent=agent_name)
    if context:
        bound_logger = bound_logger.bind(**context)
    return bound_logger


def measure_execution_time(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to measure and log function execution time.
    
    Args:
        func: Function to measure
        
    Returns:
        Decorated function with timing
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs) -> T:
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            execution_time = (time.perf_counter() - start_time) * 1000
            logger.debug(
                "Function execution completed",
                function=func.__name__,
                execution_time_ms=execution_time
            )
            return result
        except Exception as e:
            execution_time = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Function execution failed",
                function=func.__name__,
                execution_time_ms=execution_time,
                error=str(e)
            )
            raise
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs) -> T:
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            execution_time = (time.perf_counter() - start_time) * 1000
            logger.debug(
                "Function execution completed",
                function=func.__name__,
                execution_time_ms=execution_time
            )
            return result
        except Exception as e:
            execution_time = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Function execution failed",  
                function=func.__name__,
                execution_time_ms=execution_time,
                error=str(e)
            )
            raise
    
    # Return appropriate wrapper based on whether function is async
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


@asynccontextmanager
async def timeout_context(timeout_seconds: Optional[float]):
    """Context manager for operation timeouts.
    
    Args:
        timeout_seconds: Maximum execution time, None for no timeout
        
    Raises:
        AgentTimeoutError: If operation exceeds timeout
    """
    if timeout_seconds is None:
        yield
        return
        
    try:
        # Use asyncio.wait_for for Python 3.10 compatibility
        # The actual timeout handling is done by the caller using asyncio.wait_for
        yield
    except asyncio.TimeoutError:
        raise AgentTimeoutError(
            f"Operation exceeded timeout of {timeout_seconds} seconds",
            timeout_seconds=timeout_seconds
        )


class ResourceMonitor:
    """Monitor resource usage during agent execution."""
    
    def __init__(self):
        self.process = psutil.Process()
        self._start_memory: Optional[float] = None
        self._start_cpu_time: Optional[float] = None
        self._peak_memory: float = 0.0
    
    def start_monitoring(self) -> None:
        """Start resource monitoring."""
        memory_info = self.process.memory_info()
        self._start_memory = memory_info.rss / 1024 / 1024  # MB
        self._start_cpu_time = self.process.cpu_times().user
        self._peak_memory = self._start_memory
    
    def update_peak_memory(self) -> None:
        """Update peak memory usage."""
        if self._start_memory is None:
            return
            
        current_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        self._peak_memory = max(self._peak_memory, current_memory)
    
    def get_metrics(self) -> Dict[str, float]:
        """Get current resource metrics."""
        if self._start_memory is None or self._start_cpu_time is None:
            return {}
        
        self.update_peak_memory()
        current_cpu_time = self.process.cpu_times().user
        
        return {
            "memory_peak_mb": self._peak_memory,
            "cpu_time_ms": (current_cpu_time - self._start_cpu_time) * 1000
        }


def create_telemetry_span(
    name: str,
    attributes: Optional[Dict[str, Union[str, int, float, bool]]] = None
) -> trace.Span:
    """Create an OpenTelemetry span with standard attributes.
    
    Args:
        name: Span name
        attributes: Additional span attributes
        
    Returns:
        OpenTelemetry span
    """
    span = tracer.start_span(name)
    
    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)
    
    return span


def set_span_error(span: trace.Span, error: Exception) -> None:
    """Set span status and attributes for an error.
    
    Args:
        span: OpenTelemetry span
        error: Exception that occurred
    """
    span.set_status(Status(StatusCode.ERROR, str(error)))
    span.set_attribute("error.type", error.__class__.__name__)
    span.set_attribute("error.message", str(error))


def validate_agent_config(config: Dict[str, Any], required_fields: list[str]) -> None:
    """Validate agent configuration has required fields.
    
    Args:
        config: Agent configuration dictionary
        required_fields: List of required field names
        
    Raises:
        AgentConfigurationError: If required fields are missing
    """
    from .exceptions import AgentConfigurationError
    
    missing_fields = []
    for field in required_fields:
        if field not in config or config[field] is None:
            missing_fields.append(field)
    
    if missing_fields:
        raise AgentConfigurationError(
            f"Missing required configuration fields: {missing_fields}",
            context={"missing_fields": missing_fields, "provided_config": list(config.keys())}
        )


@contextmanager
def error_context(operation: str, logger: structlog.BoundLogger):
    """Context manager for consistent error handling and logging.
    
    Args:
        operation: Description of the operation being performed
        logger: Structured logger instance
    """
    try:
        logger.debug(f"Starting {operation}")
        yield
        logger.debug(f"Completed {operation}")
    except Exception as e:
        logger.error(
            f"Failed {operation}",
            error_type=e.__class__.__name__,
            error_message=str(e)
        )
        raise
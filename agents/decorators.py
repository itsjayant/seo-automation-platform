"""Agent utility decorators for common functionality.

Provides decorators for tracing, error handling, retry logic,
and other cross-cutting concerns for agent implementations.
"""

import asyncio
import time
from typing import Callable, TypeVar, Optional, Dict, Any, Union
from functools import wraps

import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .exceptions import AgentException, AgentTimeoutError
from .utils import create_telemetry_span, set_span_error, ResourceMonitor

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

T = TypeVar('T')


def with_telemetry(
    operation_name: Optional[str] = None,
    attributes: Optional[Dict[str, Union[str, int, float, bool]]] = None
):
    """Decorator to add OpenTelemetry tracing to agent methods.
    
    Args:
        operation_name: Name for the span (defaults to function name)
        attributes: Additional span attributes
        
    Returns:
        Decorated function with telemetry
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        span_name = operation_name or f"agent.{func.__name__}"
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            span_attributes = attributes or {}
            
            # Add agent context if available
            if args and hasattr(args[0], '__class__'):
                span_attributes["agent.type"] = args[0].__class__.__name__
            
            with create_telemetry_span(span_name, span_attributes) as span:
                try:
                    start_time = time.perf_counter()
                    result = await func(*args, **kwargs)
                    
                    # Record successful execution
                    execution_time_ms = (time.perf_counter() - start_time) * 1000
                    span.set_attribute("agent.execution_time_ms", execution_time_ms)
                    span.set_status(Status(StatusCode.OK))
                    
                    return result
                except Exception as e:
                    set_span_error(span, e)
                    raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            span_attributes = attributes or {}
            
            # Add agent context if available
            if args and hasattr(args[0], '__class__'):
                span_attributes["agent.type"] = args[0].__class__.__name__
            
            with create_telemetry_span(span_name, span_attributes) as span:
                try:
                    start_time = time.perf_counter()
                    result = func(*args, **kwargs)
                    
                    # Record successful execution
                    execution_time_ms = (time.perf_counter() - start_time) * 1000
                    span.set_attribute("agent.execution_time_ms", execution_time_ms)
                    span.set_status(Status(StatusCode.OK))
                    
                    return result
                except Exception as e:
                    set_span_error(span, e)
                    raise
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def with_timeout(timeout_seconds: float):
    """Decorator to add timeout protection to agent methods.
    
    Args:
        timeout_seconds: Maximum execution time
        
    Returns:
        Decorated function with timeout
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                raise AgentTimeoutError(
                    f"Operation {func.__name__} exceeded timeout of {timeout_seconds} seconds",
                    timeout_seconds=timeout_seconds
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            # For sync functions, we can't provide real timeout protection
            # This would require threading or signal handling which adds complexity
            # For now, just execute normally and let the caller handle timeouts
            logger.warning(
                "Timeout decorator on sync function has no effect",
                function=func.__name__,
                timeout_seconds=timeout_seconds
            )
            return func(*args, **kwargs)
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def with_resource_monitoring():
    """Decorator to monitor resource usage during agent execution.
    
    Returns:
        Decorated function with resource monitoring
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            monitor = ResourceMonitor()
            monitor.start_monitoring()
            
            try:
                result = await func(*args, **kwargs)
                
                # Log resource usage
                metrics = monitor.get_metrics()
                logger.info(
                    "Agent execution completed",
                    function=func.__name__,
                    **metrics
                )
                
                return result
            except Exception as e:
                metrics = monitor.get_metrics()
                logger.error(
                    "Agent execution failed", 
                    function=func.__name__,
                    error=str(e),
                    **metrics
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            monitor = ResourceMonitor()
            monitor.start_monitoring()
            
            try:
                result = func(*args, **kwargs)
                
                # Log resource usage
                metrics = monitor.get_metrics()
                logger.info(
                    "Agent execution completed",
                    function=func.__name__,
                    **metrics
                )
                
                return result
            except Exception as e:
                metrics = monitor.get_metrics()
                logger.error(
                    "Agent execution failed",
                    function=func.__name__,
                    error=str(e),
                    **metrics
                )
                raise
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def with_error_handling(error_context: Optional[str] = None):
    """Decorator to provide consistent error handling for agent methods.
    
    Args:
        error_context: Additional context for error messages
        
    Returns:
        Decorated function with error handling
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except AgentException:
                # Re-raise agent exceptions as-is
                raise
            except Exception as e:
                # Wrap other exceptions as AgentException
                context = {"function": func.__name__}
                if error_context:
                    context["error_context"] = error_context
                
                raise AgentException(
                    f"Unexpected error in {func.__name__}: {str(e)}",
                    context=context,
                    cause=e
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except AgentException:
                # Re-raise agent exceptions as-is
                raise
            except Exception as e:
                # Wrap other exceptions as AgentException
                context = {"function": func.__name__}
                if error_context:
                    context["error_context"] = error_context
                
                raise AgentException(
                    f"Unexpected error in {func.__name__}: {str(e)}",
                    context=context,
                    cause=e
                )
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def agent_lifecycle_method(state_transition: str):
    """Decorator to mark agent lifecycle methods and track state transitions.
    
    Args:
        state_transition: Description of the state transition
        
    Returns:
        Decorated function with lifecycle tracking
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(self, *args, **kwargs) -> T:
            logger.info(
                "Agent lifecycle transition",
                agent=self.__class__.__name__,
                method=func.__name__,
                transition=state_transition
            )
            
            try:
                result = await func(self, *args, **kwargs)
                logger.debug(
                    "Agent lifecycle method completed",
                    agent=self.__class__.__name__,
                    method=func.__name__
                )
                return result
            except Exception as e:
                logger.error(
                    "Agent lifecycle method failed",
                    agent=self.__class__.__name__,
                    method=func.__name__,
                    error=str(e)
                )
                raise
        
        @wraps(func)
        def sync_wrapper(self, *args, **kwargs) -> T:
            logger.info(
                "Agent lifecycle transition",
                agent=self.__class__.__name__,
                method=func.__name__,
                transition=state_transition
            )
            
            try:
                result = func(self, *args, **kwargs)
                logger.debug(
                    "Agent lifecycle method completed",
                    agent=self.__class__.__name__,
                    method=func.__name__
                )
                return result
            except Exception as e:
                logger.error(
                    "Agent lifecycle method failed",
                    agent=self.__class__.__name__,
                    method=func.__name__,
                    error=str(e)
                )
                raise
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator
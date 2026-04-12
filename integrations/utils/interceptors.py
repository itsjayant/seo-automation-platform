"""Request/Response Interceptors for HTTP Client

Provides middleware functionality for request/response processing including
authentication, logging, metrics collection, caching, and custom transformations.
"""

import asyncio
import json
import time
from typing import (
    Dict, Any, Optional, List, Callable, Awaitable, Union, Protocol
)
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import httpx
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class InterceptorType(str, Enum):
    """Types of interceptors."""
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    BOTH = "both"


class InterceptorPriority(int, Enum):
    """Interceptor execution priorities (higher = earlier execution)."""
    HIGHEST = 1000
    HIGH = 750
    NORMAL = 500  
    LOW = 250
    LOWEST = 0


@dataclass
class InterceptorContext:
    """Context passed through interceptor chain."""
    
    # Request/response data
    request: httpx.Request
    response: Optional[httpx.Response] = None
    exception: Optional[Exception] = None
    
    # Metadata
    start_time: float = 0.0
    elapsed_time: Optional[float] = None
    retry_count: int = 0
    attempt_number: int = 1
    
    # Custom attributes for interceptor communication
    attributes: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.attributes is None:
            self.attributes = {}
        if self.start_time == 0.0:
            self.start_time = time.time()
    
    def set_attribute(self, key: str, value: Any):
        """Set context attribute."""
        self.attributes[key] = value
    
    def get_attribute(self, key: str, default: Any = None) -> Any:
        """Get context attribute."""
        return self.attributes.get(key, default)
    
    def has_attribute(self, key: str) -> bool:
        """Check if context has attribute."""
        return key in self.attributes


class RequestInterceptor(ABC):
    """Abstract base class for request interceptors."""
    
    priority: int = InterceptorPriority.NORMAL
    
    @abstractmethod
    async def intercept_request(
        self, 
        context: InterceptorContext
    ) -> InterceptorContext:
        """Intercept and potentially modify request.
        
        Args:
            context: Interceptor context with request
            
        Returns:
            Modified context
        """
        pass


class ResponseInterceptor(ABC):
    """Abstract base class for response interceptors."""
    
    priority: int = InterceptorPriority.NORMAL
    
    @abstractmethod
    async def intercept_response(
        self, 
        context: InterceptorContext
    ) -> InterceptorContext:
        """Intercept and potentially modify response.
        
        Args:
            context: Interceptor context with request and response
            
        Returns:
            Modified context
        """
        pass


class ErrorInterceptor(ABC):
    """Abstract base class for error interceptors."""
    
    priority: int = InterceptorPriority.NORMAL
    
    @abstractmethod  
    async def intercept_error(
        self, 
        context: InterceptorContext
    ) -> InterceptorContext:
        """Intercept and potentially handle errors.
        
        Args:
            context: Interceptor context with request and exception
            
        Returns:
            Modified context (can clear exception to suppress it)
        """
        pass


class LoggingInterceptor(RequestInterceptor, ResponseInterceptor, ErrorInterceptor):
    """Comprehensive logging interceptor with structured data."""
    
    priority = InterceptorPriority.HIGH
    
    def __init__(
        self,
        log_headers: bool = True,
        log_body: bool = False,
        sanitize_auth: bool = True,
        max_body_size: int = 1024
    ):
        """Initialize logging interceptor.
        
        Args:
            log_headers: Whether to log request/response headers
            log_body: Whether to log request/response bodies
            sanitize_auth: Whether to sanitize authentication headers
            max_body_size: Maximum body size to log (bytes)
        """
        self.log_headers = log_headers
        self.log_body = log_body
        self.sanitize_auth = sanitize_auth
        self.max_body_size = max_body_size
    
    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Sanitize sensitive headers for logging."""
        if not self.sanitize_auth:
            return headers
        
        sensitive_keys = {
            "authorization", "x-api-key", "x-auth-token",
            "cookie", "set-cookie", "x-forwarded-authorization"
        }
        
        sanitized = {}
        for key, value in headers.items():
            if key.lower() in sensitive_keys:
                sanitized[key] = "*****"
            else:
                sanitized[key] = value
        return sanitized
    
    def _format_body(self, content: bytes) -> Optional[str]:
        """Format body content for logging."""
        if not self.log_body or not content:
            return None
        
        if len(content) > self.max_body_size:
            return f"[Body too large: {len(content)} bytes]"
        
        try:
            # Try to decode as text
            text = content.decode('utf-8')
            
            # Try to parse as JSON for pretty printing
            try:
                json_data = json.loads(text)
                return json.dumps(json_data, indent=2)
            except json.JSONDecodeError:
                return text
                
        except UnicodeDecodeError:
            return f"[Binary content: {len(content)} bytes]"
    
    async def intercept_request(self, context: InterceptorContext) -> InterceptorContext:
        """Log outgoing request."""
        request = context.request
        
        log_data = {
            "method": request.method,
            "url": str(request.url),
            "attempt": context.attempt_number
        }
        
        if self.log_headers and request.headers:
            log_data["headers"] = self._sanitize_headers(dict(request.headers))
        
        if request.content:
            log_data["body"] = self._format_body(request.content)
        
        logger.info("HTTP request starting", **log_data)
        return context
    
    async def intercept_response(self, context: InterceptorContext) -> InterceptorContext:
        """Log received response."""
        request = context.request  
        response = context.response
        
        if not response:
            return context
        
        elapsed_ms = int((time.time() - context.start_time) * 1000)
        
        log_data = {
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "content_length": len(response.content) if response.content else 0
        }
        
        if self.log_headers and response.headers:
            log_data["response_headers"] = dict(response.headers)
        
        if response.content:
            log_data["response_body"] = self._format_body(response.content)
        
        if response.status_code >= 400:
            logger.warning("HTTP request failed", **log_data)
        else:
            logger.info("HTTP request completed", **log_data)
        
        return context
    
    async def intercept_error(self, context: InterceptorContext) -> InterceptorContext:
        """Log request errors."""
        request = context.request
        exception = context.exception
        
        if not exception:
            return context
        
        elapsed_ms = int((time.time() - context.start_time) * 1000)
        
        log_data = {
            "method": request.method,
            "url": str(request.url),
            "error": str(exception),
            "error_type": type(exception).__name__,
            "elapsed_ms": elapsed_ms,
            "retry_count": context.retry_count
        }
        
        logger.error("HTTP request error", **log_data)
        return context


class MetricsInterceptor(RequestInterceptor, ResponseInterceptor, ErrorInterceptor):
    """Metrics collection interceptor for HTTP client monitoring."""
    
    priority = InterceptorPriority.NORMAL
    
    def __init__(self):
        """Initialize metrics interceptor."""
        self.metrics = {
            "requests_total": 0,
            "requests_successful": 0,
            "requests_failed": 0,
            "requests_by_method": {},
            "requests_by_status": {},
            "response_times": [],
            "content_sizes": []
        }
    
    async def intercept_request(self, context: InterceptorContext) -> InterceptorContext:
        """Record request start metrics."""
        self.metrics["requests_total"] += 1
        
        method = context.request.method
        self.metrics["requests_by_method"][method] = (
            self.metrics["requests_by_method"].get(method, 0) + 1
        )
        
        context.set_attribute("metrics_start_time", time.time())
        return context
    
    async def intercept_response(self, context: InterceptorContext) -> InterceptorContext:
        """Record response metrics."""
        response = context.response
        if not response:
            return context
        
        # Record response time
        start_time = context.get_attribute("metrics_start_time")
        if start_time:
            response_time = time.time() - start_time
            self.metrics["response_times"].append(response_time)
        
        # Record status code
        status_code = response.status_code
        self.metrics["requests_by_status"][status_code] = (
            self.metrics["requests_by_status"].get(status_code, 0) + 1
        )
        
        # Record content size
        if response.content:
            self.metrics["content_sizes"].append(len(response.content))
        
        # Count success/failure
        if 200 <= status_code < 400:
            self.metrics["requests_successful"] += 1
        else:
            self.metrics["requests_failed"] += 1
        
        return context
    
    async def intercept_error(self, context: InterceptorContext) -> InterceptorContext:
        """Record error metrics."""
        self.metrics["requests_failed"] += 1
        return context
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics with computed stats."""
        metrics = self.metrics.copy()
        
        # Compute response time statistics
        if self.metrics["response_times"]:
            response_times = self.metrics["response_times"]
            metrics["avg_response_time"] = sum(response_times) / len(response_times)
            metrics["min_response_time"] = min(response_times)
            metrics["max_response_time"] = max(response_times)
        
        # Compute content size statistics
        if self.metrics["content_sizes"]:
            content_sizes = self.metrics["content_sizes"]
            metrics["avg_content_size"] = sum(content_sizes) / len(content_sizes)
            metrics["min_content_size"] = min(content_sizes)
            metrics["max_content_size"] = max(content_sizes)
        
        return metrics


class TracingInterceptor(RequestInterceptor, ResponseInterceptor, ErrorInterceptor):
    """OpenTelemetry tracing interceptor."""
    
    priority = InterceptorPriority.HIGHEST
    
    def __init__(self, service_name: str = "http_client"):
        """Initialize tracing interceptor.
        
        Args:
            service_name: Service name for tracing spans
        """
        self.service_name = service_name
    
    async def intercept_request(self, context: InterceptorContext) -> InterceptorContext:
        """Start tracing span for request."""
        request = context.request
        
        span_name = f"http_{request.method.lower()}"
        span = tracer.start_span(
            span_name,
            attributes={
                "http.method": request.method,
                "http.url": str(request.url),
                "http.scheme": request.url.scheme,
                "http.host": request.url.host,
                "service.name": self.service_name
            }
        )
        
        context.set_attribute("tracing_span", span)
        return context
    
    async def intercept_response(self, context: InterceptorContext) -> InterceptorContext:
        """Complete tracing span with response data."""
        span = context.get_attribute("tracing_span")
        response = context.response
        
        if span and response:
            span.set_attribute("http.status_code", response.status_code)
            span.set_attribute("http.response.body.size", len(response.content))
            
            if response.status_code >= 400:
                span.set_status(trace.Status(trace.StatusCode.ERROR))
            else:
                span.set_status(trace.Status(trace.StatusCode.OK))
            
            span.end()
        
        return context
    
    async def intercept_error(self, context: InterceptorContext) -> InterceptorContext:
        """Complete tracing span with error data."""
        span = context.get_attribute("tracing_span")
        exception = context.exception
        
        if span and exception:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exception)))
            span.record_exception(exception)
            span.end()
        
        return context


class AuthenticationInterceptor(RequestInterceptor):
    """Authentication interceptor that applies auth to requests."""
    
    priority = InterceptorPriority.HIGH
    
    def __init__(self, auth: httpx.Auth):
        """Initialize authentication interceptor.
        
        Args:
            auth: httpx authentication instance
        """
        self.auth = auth
    
    async def intercept_request(self, context: InterceptorContext) -> InterceptorContext:
        """Apply authentication to request."""
        request = context.request
        
        # Apply authentication using httpx auth flow
        auth_flow = self.auth.auth_flow(request)
        try:
            authenticated_request = next(auth_flow)
            context.request = authenticated_request
        except StopIteration:
            pass  # No authentication applied
        
        return context


class CachingInterceptor(RequestInterceptor, ResponseInterceptor):
    """Response caching interceptor with TTL and cache keys."""
    
    priority = InterceptorPriority.LOW
    
    def __init__(
        self,
        ttl_seconds: int = 300,
        max_cache_size: int = 1000,
        cache_get_only: bool = True
    ):
        """Initialize caching interceptor.
        
        Args:
            ttl_seconds: Time to live for cached responses
            max_cache_size: Maximum number of cached responses
            cache_get_only: Only cache GET requests
        """
        self.ttl_seconds = ttl_seconds
        self.max_cache_size = max_cache_size
        self.cache_get_only = cache_get_only
        self._cache: Dict[str, tuple] = {}  # key -> (response, timestamp)
    
    def _generate_cache_key(self, request: httpx.Request) -> str:
        """Generate cache key for request."""
        return f"{request.method}:{request.url}"
    
    def _is_cacheable(self, request: httpx.Request) -> bool:
        """Check if request is cacheable."""
        if self.cache_get_only and request.method != "GET":
            return False
        return True
    
    def _is_cache_valid(self, timestamp: float) -> bool:
        """Check if cache entry is still valid."""
        return (time.time() - timestamp) < self.ttl_seconds
    
    def _evict_expired_entries(self):
        """Remove expired cache entries."""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if (current_time - timestamp) >= self.ttl_seconds
        ]
        for key in expired_keys:
            self._cache.pop(key, None)
    
    async def intercept_request(self, context: InterceptorContext) -> InterceptorContext:
        """Check cache for existing response.""" 
        request = context.request
        
        if not self._is_cacheable(request):
            return context
        
        cache_key = self._generate_cache_key(request)
        cached_entry = self._cache.get(cache_key)
        
        if cached_entry:
            cached_response, timestamp = cached_entry
            
            if self._is_cache_valid(timestamp):
                # Return cached response
                context.response = cached_response
                context.set_attribute("cache_hit", True)
                
                logger.debug(
                    "Cache hit",
                    method=request.method,
                    url=str(request.url),
                    cache_key=cache_key
                )
        
        return context
    
    async def intercept_response(self, context: InterceptorContext) -> InterceptorContext:
        """Cache successful response."""
        request = context.request
        response = context.response
        
        if (
            not context.get_attribute("cache_hit", False) and
            response and 
            self._is_cacheable(request) and
            200 <= response.status_code < 300
        ):
            cache_key = self._generate_cache_key(request)
            
            # Evict expired entries periodically
            if len(self._cache) > self.max_cache_size * 0.8:
                self._evict_expired_entries()
            
            # Add to cache if space available
            if len(self._cache) < self.max_cache_size:
                self._cache[cache_key] = (response, time.time())
                
                logger.debug(
                    "Response cached",
                    method=request.method,
                    url=str(request.url),
                    cache_key=cache_key,
                    status_code=response.status_code
                )
        
        return context


class InterceptorChain:
    """Manages execution of request/response interceptors."""
    
    def __init__(self):
        """Initialize empty interceptor chain."""
        self.request_interceptors: List[RequestInterceptor] = []
        self.response_interceptors: List[ResponseInterceptor] = []
        self.error_interceptors: List[ErrorInterceptor] = []
    
    def add_interceptor(
        self, 
        interceptor: Union[RequestInterceptor, ResponseInterceptor, ErrorInterceptor]
    ):
        """Add interceptor to appropriate chain(s).
        
        Args:
            interceptor: Interceptor instance to add
        """
        if isinstance(interceptor, RequestInterceptor):
            self.request_interceptors.append(interceptor)
            self.request_interceptors.sort(key=lambda x: x.priority, reverse=True)
        
        if isinstance(interceptor, ResponseInterceptor):
            self.response_interceptors.append(interceptor)
            self.response_interceptors.sort(key=lambda x: x.priority, reverse=True)
        
        if isinstance(interceptor, ErrorInterceptor):
            self.error_interceptors.append(interceptor)
            self.error_interceptors.sort(key=lambda x: x.priority, reverse=True)
    
    def remove_interceptor(self, interceptor_type: type):
        """Remove all interceptors of specified type.
        
        Args:
            interceptor_type: Type of interceptor to remove
        """
        self.request_interceptors = [
            i for i in self.request_interceptors 
            if not isinstance(i, interceptor_type)
        ]
        self.response_interceptors = [
            i for i in self.response_interceptors
            if not isinstance(i, interceptor_type) 
        ]
        self.error_interceptors = [
            i for i in self.error_interceptors
            if not isinstance(i, interceptor_type)
        ]
    
    async def process_request(self, context: InterceptorContext) -> InterceptorContext:
        """Process request through interceptor chain.
        
        Args:
            context: Request context
            
        Returns:
            Modified context
        """
        for interceptor in self.request_interceptors:
            try:
                context = await interceptor.intercept_request(context)
            except Exception as e:
                logger.error(
                    "Request interceptor failed",
                    interceptor=type(interceptor).__name__,
                    error=str(e)
                )
                # Continue with other interceptors
        
        return context
    
    async def process_response(self, context: InterceptorContext) -> InterceptorContext:
        """Process response through interceptor chain.
        
        Args:
            context: Response context
            
        Returns:
            Modified context
        """
        for interceptor in self.response_interceptors:
            try:
                context = await interceptor.intercept_response(context)
            except Exception as e:
                logger.error(
                    "Response interceptor failed",
                    interceptor=type(interceptor).__name__,
                    error=str(e)
                )
                # Continue with other interceptors
        
        return context
    
    async def process_error(self, context: InterceptorContext) -> InterceptorContext:
        """Process error through interceptor chain.
        
        Args:
            context: Error context
            
        Returns:
            Modified context (exception may be cleared)
        """
        for interceptor in self.error_interceptors:
            try:
                context = await interceptor.intercept_error(context)
            except Exception as e:
                logger.error(
                    "Error interceptor failed",
                    interceptor=type(interceptor).__name__,
                    error=str(e)
                )
                # Continue with other interceptors
        
        return context
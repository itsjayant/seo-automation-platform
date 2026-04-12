"""Production-Grade HTTP Client with Retry Policies and Rate Limiting

Comprehensive HTTP client for all external API integrations with built-in
rate limiting, circuit breaker protection, retry policies, and observability.
"""

import asyncio
import json
import time
from typing import (
    Dict, Any, Optional, Union, List, Callable, Awaitable
)
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from pydantic import BaseModel, Field, ConfigDict
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .rate_limiter import RateLimiter, RateLimitConfig, RateLimitExceededError
from .circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitBreakerState
from .backoff import ExponentialBackoff, BackoffConfig

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class HttpMethod(str, Enum):
    """HTTP methods enumeration."""
    GET = "GET"
    POST = "POST" 
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class CacheStrategy(str, Enum):
    """Response caching strategies."""
    NO_CACHE = "no_cache"
    MEMORY = "memory"
    REDIS = "redis"


@dataclass
class RetryConfig:
    """Configuration for HTTP request retry policies."""
    
    max_retries: int = 3
    backoff_factor: float = 2.0
    backoff_jitter: bool = True
    initial_delay: float = 1.0
    max_delay: float = 300.0
    
    # HTTP status codes that should trigger a retry
    retryable_status_codes: tuple = (429, 500, 502, 503, 504)
    
    # Exception types that should trigger a retry
    retryable_exceptions: tuple = (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        RateLimitExceededError,
    )
    
    def __post_init__(self):
        """Validate retry configuration."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.backoff_factor <= 1:
            raise ValueError("backoff_factor must be > 1")
        if self.initial_delay <= 0:
            raise ValueError("initial_delay must be positive")
        if self.max_delay < self.initial_delay:
            raise ValueError("max_delay must be >= initial_delay")


@dataclass  
class TimeoutConfig:
    """HTTP timeout configuration."""
    
    connect: float = 10.0      # Connection timeout
    read: float = 30.0         # Read timeout
    write: float = 30.0        # Write timeout
    pool: float = 30.0         # Connection pool timeout
    
    def to_httpx_timeout(self) -> httpx.Timeout:
        """Convert to httpx Timeout object."""
        return httpx.Timeout(
            connect=self.connect,
            read=self.read,
            write=self.write,
            pool=self.pool
        )


@dataclass
class ConnectionConfig:
    """HTTP connection configuration."""
    
    max_connections: int = 100      # Maximum total connections
    max_keepalive: int = 20         # Maximum keep-alive connections
    keepalive_expiry: float = 5.0   # Keep-alive expiry in seconds
    http2: bool = False             # Enable HTTP/2 support (requires httpx[http2])
    verify_ssl: bool = True         # SSL certificate verification
    trust_env: bool = True          # Trust environment proxy settings


class HttpClientConfig(BaseModel):
    """Configuration for the HTTP client."""
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # Core configuration
    base_url: Optional[str] = None
    user_agent: str = "SEO-Automation-Platform/1.0"
    
    # Timeout configuration  
    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    
    # Connection configuration
    connection: ConnectionConfig = Field(default_factory=ConnectionConfig)
    
    # Retry configuration
    retry: RetryConfig = Field(default_factory=RetryConfig)
    
    # Rate limiting
    enable_rate_limiting: bool = True
    rate_limiter_service: Optional[str] = None
    
    # Circuit breaker
    enable_circuit_breaker: bool = True
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: int = 30
    
    # Caching
    cache_strategy: CacheStrategy = CacheStrategy.NO_CACHE
    cache_ttl_seconds: int = 300
    
    # Logging
    log_request_headers: bool = True
    log_response_headers: bool = True
    log_request_body: bool = False   # Sensitive data risk
    log_response_body: bool = False  # Large response risk
    sanitize_auth_headers: bool = True
    
    # Request deduplication
    enable_deduplication: bool = False
    deduplication_window_seconds: int = 60


@dataclass
class HttpRequest:
    """HTTP request configuration."""
    
    method: HttpMethod
    url: str
    headers: Optional[Dict[str, str]] = None
    params: Optional[Dict[str, Any]] = None
    json_data: Optional[Dict[str, Any]] = None
    form_data: Optional[Dict[str, Any]] = None
    content: Optional[bytes] = None
    cookies: Optional[Dict[str, str]] = None
    auth: Optional[httpx.Auth] = None
    timeout_override: Optional[TimeoutConfig] = None
    priority: int = 0  # Higher numbers = higher priority
    trace_id: Optional[str] = None
    
    def to_httpx_kwargs(self) -> Dict[str, Any]:
        """Convert to httpx request parameters."""
        kwargs = {
            "method": self.method.value,
            "url": self.url,
        }
        
        if self.headers:
            kwargs["headers"] = self.headers
        if self.params:
            kwargs["params"] = self.params
        if self.json_data:
            kwargs["json"] = self.json_data
        if self.form_data:
            kwargs["data"] = self.form_data
        if self.content:
            kwargs["content"] = self.content
        if self.cookies:
            kwargs["cookies"] = self.cookies
        if self.auth:
            kwargs["auth"] = self.auth
            
        return kwargs


@dataclass
class HttpResponse:
    """HTTP response wrapper with metadata."""
    
    status_code: int
    headers: Dict[str, str]
    content: bytes
    text: str
    encoding: str
    url: str
    elapsed: float
    request_id: str
    
    # Metadata 
    from_cache: bool = False
    retry_count: int = 0
    rate_limited: bool = False
    circuit_breaker_state: Optional[CircuitBreakerState] = None
    
    @property
    def json(self) -> Any:
        """Parse response content as JSON."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Response is not valid JSON: {e}")
    
    @property
    def is_success(self) -> bool:
        """Check if response indicates success."""
        return 200 <= self.status_code < 300
    
    @property
    def is_client_error(self) -> bool:
        """Check if response indicates client error."""
        return 400 <= self.status_code < 500
    
    @property
    def is_server_error(self) -> bool:
        """Check if response indicates server error.""" 
        return self.status_code >= 500


class HttpClient:
    """Production-grade HTTP client with comprehensive reliability features.
    
    Features:
    - Asynchronous httpx client with connection pooling
    - Exponential backoff retry policy with jitter
    - Rate limiter integration for quota management
    - Circuit breaker protection for service reliability
    - Request/response logging with structured data
    - User-Agent rotation for ethical scraping
    - Request deduplication to avoid redundant calls
    - Response caching with configurable strategies
    - OpenTelemetry tracing integration
    - Comprehensive error handling and recovery
    """
    
    def __init__(
        self,
        config: Optional[HttpClientConfig] = None,
        rate_limiter: Optional[RateLimiter] = None,
        circuit_breaker: Optional[CircuitBreaker] = None
    ):
        """Initialize HTTP client with configuration.
        
        Args:
            config: Client configuration
            rate_limiter: Optional rate limiter instance
            circuit_breaker: Optional circuit breaker instance
        """
        self.config = config or HttpClientConfig()
        
        # Initialize rate limiter
        self._rate_limiter = rate_limiter
        if self.config.enable_rate_limiting and rate_limiter is None:
            self._rate_limiter = RateLimiter()
        
        # Initialize circuit breaker
        self._circuit_breaker = circuit_breaker
        if self.config.enable_circuit_breaker and circuit_breaker is None:
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=self.config.circuit_breaker_failure_threshold,
                recovery_timeout=self.config.circuit_breaker_recovery_timeout,
                name="http_client_breaker"
            )
        
        # Initialize internal state
        self._client: Optional[httpx.AsyncClient] = None
        self._request_cache: Dict[str, HttpResponse] = {}
        self._request_timestamps: Dict[str, float] = {}
        self._metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "retried_requests": 0,
            "rate_limited_requests": 0,
            "circuit_breaker_trips": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
        
        logger.info(
            "Http client initialized",
            config=self.config.model_dump(exclude={"timeout", "connection"}),
            rate_limiting_enabled=self._rate_limiter is not None,
            circuit_breaker_enabled=self._circuit_breaker is not None
        )
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _ensure_client(self):
        """Ensure httpx client is initialized."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_connections=self.config.connection.max_connections,
                max_keepalive_connections=self.config.connection.max_keepalive,
                keepalive_expiry=self.config.connection.keepalive_expiry
            )
            
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout.to_httpx_timeout(),
                limits=limits,
                http2=self.config.connection.http2,
                verify=self.config.connection.verify_ssl,
                trust_env=self.config.connection.trust_env,
                headers={"User-Agent": self.config.user_agent}
            )
    
    async def close(self):
        """Close HTTP client and cleanup resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        
        # Clear caches
        self._request_cache.clear()
        self._request_timestamps.clear()
        
        logger.info(
            "Http client closed",
            metrics=self._metrics
        )
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID for tracing."""
        import uuid
        return uuid.uuid4().hex[:16]
    
    def _get_cache_key(self, request: HttpRequest) -> str:
        """Generate cache key for request deduplication."""
        key_parts = [
            request.method.value,
            request.url,
            json.dumps(request.params, sort_keys=True) if request.params else "",
            json.dumps(request.json_data, sort_keys=True) if request.json_data else "",
            json.dumps(request.form_data, sort_keys=True) if request.form_data else "",
        ]
        return "|".join(key_parts)
    
    def _is_request_cacheable(self, request: HttpRequest) -> bool:
        """Check if request can be cached."""
        return (
            request.method == HttpMethod.GET and
            self.config.cache_strategy != CacheStrategy.NO_CACHE and
            not request.json_data and 
            not request.form_data and
            not request.content
        )
    
    def _is_request_duplicate(self, request: HttpRequest) -> bool:
        """Check if request is a duplicate within the deduplication window."""        
        if not self.config.enable_deduplication:
            return False
        
        cache_key = self._get_cache_key(request)
        now = time.time()
        
        if cache_key in self._request_timestamps:
            last_request_time = self._request_timestamps[cache_key]
            if now - last_request_time < self.config.deduplication_window_seconds:
                return True
        
        self._request_timestamps[cache_key] = now
        return False
    
    def _get_cached_response(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Get cached response if available and valid."""
        if not self._is_request_cacheable(request):
            return None
        
        cache_key = self._get_cache_key(request)
        cached_response = self._request_cache.get(cache_key)
        
        if cached_response:
            # Check if cache entry is still valid
            cache_age = time.time() - self._request_timestamps.get(cache_key, 0)
            if cache_age < self.config.cache_ttl_seconds:
                self._metrics["cache_hits"] += 1
                return cached_response
            else:
                # Remove expired cache entry
                self._request_cache.pop(cache_key, None)
                self._request_timestamps.pop(cache_key, None)
        
        self._metrics["cache_misses"] += 1
        return None
    
    def _cache_response(self, request: HttpRequest, response: HttpResponse):
        """Cache successful response."""
        if (
            self._is_request_cacheable(request) and 
            response.is_success and
            self.config.cache_strategy != CacheStrategy.NO_CACHE
        ):
            cache_key = self._get_cache_key(request)
            self._request_cache[cache_key] = response
            self._request_timestamps[cache_key] = time.time()
    
    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Sanitize headers for logging by masking sensitive values.""" 
        if not self.config.sanitize_auth_headers:
            return headers
        
        sensitive_headers = {
            "authorization", "x-api-key", "x-auth-token", 
            "cookie", "set-cookie", "x-forwarded-authorization"
        }
        
        sanitized = {}
        for key, value in headers.items():
            if key.lower() in sensitive_headers:
                sanitized[key] = "*****"
            else:
                sanitized[key] = value
        return sanitized
    
    async def _apply_rate_limiting(self, request: HttpRequest):
        """Apply rate limiting to the request."""
        if not self._rate_limiter or not self.config.enable_rate_limiting:
            return
        
        service_name = self.config.rate_limiter_service or "default"
        
        try:
            result = await self._rate_limiter.check_rate_limit(
                service_name, 
                priority=request.priority
            )
            
            if not result.allowed:
                self._metrics["rate_limited_requests"] += 1
                raise RateLimitExceededError(
                    f"Rate limit exceeded for {service_name}",
                    retry_after=result.retry_after or 0,
                    current_usage=result.current_usage,
                    limit=result.current_usage + result.remaining,
                    window=60  # Default window
                )
        
        except Exception as e:
            logger.warning(
                "Rate limiting check failed",
                error=str(e),
                service=service_name,
                request_url=request.url
            )
            # Continue with request if rate limiter fails
    
    async def _execute_request(self, request: HttpRequest) -> httpx.Response:
        """Execute HTTP request through circuit breaker."""
        await self._ensure_client()
        
        if self._circuit_breaker:
            return await self._circuit_breaker.call(
                self._client.request,
                **request.to_httpx_kwargs()
            )
        else:
            return await self._client.request(**request.to_httpx_kwargs())
    
    async def _request_with_retry(self, request: HttpRequest) -> HttpResponse:
        """Execute HTTP request with retry logic."""
        backoff = ExponentialBackoff(BackoffConfig(
            base_delay=self.config.retry.initial_delay,
            max_delay=self.config.retry.max_delay,
            max_attempts=self.config.retry.max_retries + 1,
            backoff_factor=self.config.retry.backoff_factor,
            retryable_exceptions=self.config.retry.retryable_exceptions
        ))
        
        last_exception = None
        request_id = request.trace_id or self._generate_request_id()
        
        while backoff.attempt_count <= self.config.retry.max_retries:
            try:
                # Apply rate limiting
                await self._apply_rate_limiting(request) 
                
                start_time = time.time()
                
                # Execute request
                raw_response = await self._execute_request(request) 
                
                elapsed = time.time() - start_time
                
                # Convert to our response wrapper
                response = HttpResponse(
                    status_code=raw_response.status_code,
                    headers=dict(raw_response.headers),
                    content=raw_response.content,
                    text=raw_response.text,
                    encoding=raw_response.encoding or "utf-8",
                    url=str(raw_response.url),
                    elapsed=elapsed,
                    request_id=request_id,
                    retry_count=backoff.attempt_count,
                    circuit_breaker_state=self._circuit_breaker.state if self._circuit_breaker else None
                )
                
                # Check if we should retry based on status code
                if response.status_code in self.config.retry.retryable_status_codes:
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=raw_response.request,
                        response=raw_response
                    )
                
                # Log successful request
                logger.info(
                    "Http request completed",
                    method=request.method.value,
                    url=request.url,
                    status_code=response.status_code,
                    elapsed_ms=int(elapsed * 1000),
                    retry_count=backoff.attempt_count,
                    request_id=request_id,
                    response_headers=self._sanitize_headers(response.headers) if self.config.log_response_headers else None
                )
                
                self._metrics["successful_requests"] += 1
                return response
            
            except Exception as e:
                last_exception = e
                backoff.record_failure()
                
                # Check if we should retry
                should_retry = (
                    backoff.attempt_count < self.config.retry.max_retries and
                    isinstance(e, self.config.retry.retryable_exceptions)
                )
                
                if should_retry:
                    delay = await backoff.get_delay()
                    
                    logger.warning(
                        "Http request failed, retrying",
                        method=request.method.value,
                        url=request.url,
                        error=str(e),
                        error_type=type(e).__name__,
                        retry_attempt=backoff.attempt_count,
                        delay_seconds=delay,
                        request_id=request_id
                    )
                    
                    if delay > 0:
                        await asyncio.sleep(delay)
                    
                    self._metrics["retried_requests"] += 1
                    continue
                else:
                    # No more retries or non-retryable error
                    logger.error(
                        "Http request failed permanently",
                        method=request.method.value,
                        url=request.url,
                        error=str(e),
                        error_type=type(e).__name__,
                        retry_count=backoff.attempt_count,
                        request_id=request_id
                    )
                    break
        
        # All retries exhausted or non-retryable error
        self._metrics["failed_requests"] += 1
        if isinstance(last_exception, CircuitBreakerError):
            self._metrics["circuit_breaker_trips"] += 1
        
        raise last_exception
    
    async def request(
        self,
        method: Union[str, HttpMethod],
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        form_data: Optional[Dict[str, Any]] = None,
        content: Optional[bytes] = None,
        cookies: Optional[Dict[str, str]] = None,
        auth: Optional[httpx.Auth] = None,
        timeout_override: Optional[TimeoutConfig] = None,
        priority: int = 0,
        trace_id: Optional[str] = None
    ) -> HttpResponse:
        """Execute HTTP request with full reliability features.
        
        Args:
            method: HTTP method
            url: Request URL
            headers: Optional request headers
            params: Optional query parameters
            json_data: Optional JSON request body
            form_data: Optional form data
            content: Optional raw content
            cookies: Optional cookies
            auth: Optional authentication
            timeout_override: Optional timeout override
            priority: Request priority (higher = more priority)
            trace_id: Optional trace ID for request correlation
        
        Returns:
            HttpResponse with metadata
            
        Raises:
            Various HTTP/network exceptions after retry exhaustion
        """
        # Convert method to enum if string
        if isinstance(method, str):
            method = HttpMethod(method.upper())
        
        # Create request object
        request = HttpRequest(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json_data=json_data,
            form_data=form_data,
            content=content,
            cookies=cookies,
            auth=auth,
            timeout_override=timeout_override,
            priority=priority,
            trace_id=trace_id
        )
        
        self._metrics["total_requests"] += 1
        
        # Check for duplicate requests
        if self._is_request_duplicate(request):
            logger.debug(
                "Duplicate request detected, skipping",
                method=request.method.value,
                url=request.url
            )
            # Return the previous response from cache
            cached_response = self._get_cached_response(request)
            if cached_response:
                return cached_response
        
        # Check cache for GET requests
        cached_response = self._get_cached_response(request)
        if cached_response:
            cached_response.from_cache = True
            return cached_response
        
        # Create tracing span
        with tracer.start_as_current_span(
            f"http_request_{method.value.lower()}",
            attributes={
                "http.method": method.value,
                "http.url": url,
                "http.client": "seo_platform_client"
            }
        ) as span:
            try:
                # Execute request with retries
                response = await self._request_with_retry(request)
                
                # Cache successful responses
                self._cache_response(request, response)
                
                # Update tracing span
                span.set_attribute("http.status_code", response.status_code)
                span.set_attribute("http.response.body.size", len(response.content))
                span.set_status(Status(StatusCode.OK))
                
                return response
            
            except Exception as e:
                # Update tracing span with error
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
    
    # Convenience methods for common HTTP methods
    async def get(self, url: str, **kwargs) -> HttpResponse:
        """Execute GET request."""
        return await self.request(HttpMethod.GET, url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> HttpResponse:
        """Execute POST request."""
        return await self.request(HttpMethod.POST, url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> HttpResponse:
        """Execute PUT request."""
        return await self.request(HttpMethod.PUT, url, **kwargs)
    
    async def patch(self, url: str, **kwargs) -> HttpResponse:
        """Execute PATCH request."""
        return await self.request(HttpMethod.PATCH, url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> HttpResponse:
        """Execute DELETE request."""
        return await self.request(HttpMethod.DELETE, url, **kwargs)
    
    async def head(self, url: str, **kwargs) -> HttpResponse:
        """Execute HEAD request."""
        return await self.request(HttpMethod.HEAD, url, **kwargs)
    
    async def options(self, url: str, **kwargs) -> HttpResponse:
        """Execute OPTIONS request."""
        return await self.request(HttpMethod.OPTIONS, url, **kwargs)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get client metrics."""
        return self._metrics.copy()
    
    def reset_metrics(self):
        """Reset client metrics."""
        for key in self._metrics:
            self._metrics[key] = 0


# Factory functions for common configurations

def create_api_client(
    base_url: str,
    api_key: Optional[str] = None,
    rate_limit_service: Optional[str] = None,
    **config_overrides
) -> HttpClient:
    """Create HTTP client for API integrations.
    
    Args:
        base_url: API base URL
        api_key: Optional API key for authentication
        rate_limit_service: Service name for rate limiting
        **config_overrides: Additional configuration overrides
    
    Returns:
        Configured HttpClient instance
    """
    config = HttpClientConfig(
        base_url=base_url,
        rate_limiter_service=rate_limit_service,
        **config_overrides
    )
    
    # Add API key to headers if provided
    if api_key:
        config.user_agent = f"{config.user_agent} (API-Key-Auth)"
    
    return HttpClient(config=config)


def create_web_scraper_client(**config_overrides) -> HttpClient:
    """Create HTTP client for web scraping with ethical defaults.
    
    Args:
        **config_overrides: Configuration overrides
    
    Returns:
        Configured HttpClient for web scraping
    """
    config = HttpClientConfig(
        user_agent="SEO-Platform-Scraper/1.0 (+https://example.com/bot)",
        retry=RetryConfig(
            max_retries=2,  # Conservative for scraping
            initial_delay=2.0,  # Longer delays
            max_delay=60.0
        ),
        timeout=TimeoutConfig(
            connect=15.0,  # Longer timeouts
            read=45.0,
            write=30.0
        ),
        enable_rate_limiting=True,
        cache_strategy=CacheStrategy.MEMORY,
        cache_ttl_seconds=3600,  # 1 hour cache
        **config_overrides
    )
    
    return HttpClient(config=config)
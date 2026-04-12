"""Production-Grade Rate Limiter with Circuit Breaker Pattern

Comprehensive rate limiting for external API integrations with Redis-backed
sliding window algorithm, circuit breaker protection, and distributed coordination.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional, Union, Type
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
import structlog
from threading import Lock

from .circuit_breaker import CircuitBreaker, CircuitBreakerState, CircuitBreakerError
from .backoff import ExponentialBackoff, BackoffConfig, create_api_backoff

logger = structlog.get_logger(__name__)


class RateLimitAlgorithm(Enum):
    """Rate limiting algorithms."""
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""
    
    def __init__(
        self, 
        message: str, 
        retry_after: float,
        current_usage: int,
        limit: int,
        window: int
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.current_usage = current_usage
        self.limit = limit
        self.window = window


@dataclass
class RateLimitConfig:
    """Configuration for a specific API endpoint rate limit."""
    
    # Basic rate limit parameters
    requests: int                          # Requests allowed per window
    window: int                           # Window size in seconds
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    
    # Advanced features
    burst_capacity: Optional[int] = None   # Allow temporary burst above limit
    priority_reserve: float = 0.1         # Reserve % of quota for high priority
    
    # Circuit breaker configuration
    circuit_breaker_enabled: bool = True
    failure_threshold: int = 5
    recovery_timeout: int = 60
    
    # Redis key configuration
    key_prefix: str = "rate_limit"
    key_suffix: str = ""
    
    def __post_init__(self):
        """Validate configuration."""
        if self.requests <= 0:
            raise ValueError("requests must be positive")
        if self.window <= 0:
            raise ValueError("window must be positive")
        if self.burst_capacity and self.burst_capacity < self.requests:
            raise ValueError("burst_capacity must be >= requests")
        if not 0 <= self.priority_reserve <= 1:
            raise ValueError("priority_reserve must be between 0 and 1")

    @property
    def redis_key(self) -> str:
        """Generate Redis key for this rate limit."""
        parts = [self.key_prefix]
        if self.key_suffix:
            parts.append(self.key_suffix)
        return ":".join(parts)


class RateLimitResult:
    """Result of rate limit check."""
    
    def __init__(
        self,
        allowed: bool,
        current_usage: int,
        remaining: int,
        reset_time: datetime,
        retry_after: Optional[float] = None
    ):
        self.allowed = allowed
        self.current_usage = current_usage
        self.remaining = remaining
        self.reset_time = reset_time
        self.retry_after = retry_after

    @property
    def headers(self) -> Dict[str, str]:
        """Generate HTTP headers for rate limit status."""
        headers = {
            "X-RateLimit-Limit": str(self.current_usage + self.remaining),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(int(self.reset_time.timestamp())),
        }
        
        if self.retry_after:
            headers["Retry-After"] = str(int(self.retry_after))
        
        return headers


class RateLimiter:
    """Production-grade distributed rate limiter.
    
    Features:
    - Redis-backed sliding window and token bucket algorithms
    - Circuit breaker integration for reliability
    - Per-service configurable limits with priority queuing
    - Burst handling and priority reservations
    - Comprehensive metrics and monitoring
    - Thread-safe concurrent operation
    - Lua scripts for atomic operations
    """

    # Default rate limit configurations for API services
    DEFAULT_CONFIGS = {
        "gsc_api": RateLimitConfig(
            requests=200, 
            window=60, 
            key_suffix="gsc",
            burst_capacity=250
        ),
        "ga4_api": RateLimitConfig(
            requests=200, 
            window=60, 
            key_suffix="ga4",
            burst_capacity=250
        ),
        "serpapi": RateLimitConfig(
            requests=100, 
            window=60, 
            key_suffix="serpapi",
            burst_capacity=120
        ),
    }

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        configs: Optional[Dict[str, RateLimitConfig]] = None,
        settings=None  # Allow injection of settings for testing
    ):
        """Initialize rate limiter.
        
        Args:
            redis_client: Optional Redis client instance
            configs: Optional custom rate limit configurations
            settings: Optional settings instance (for testing)
        """
        # Settings setup with optional injection for testing
        if settings is not None:
            self.settings = settings
            self.redis_config = settings.redis
        else:
            try:
                from config import get_settings
                self.settings = get_settings()
                self.redis_config = self.settings.redis
            except Exception:
                # Fallback for testing without full config
                self.settings = None
                self.redis_config = None
        
        # Redis client setup
        self._redis_client = redis_client
        self._redis_lock = Lock()
        
        # Rate limit configurations
        self.configs = configs or self.DEFAULT_CONFIGS.copy()
        
        # Circuit breakers per service
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._init_circuit_breakers()
        
        # Backoff strategies per service
        self._backoff_strategies: Dict[str, ExponentialBackoff] = {}
        self._init_backoff_strategies()
        
        # Lua scripts (loaded lazily)
        self._lua_scripts: Dict[str, Any] = {}
        
        # Metrics tracking
        self._metrics: Dict[str, Dict[str, Any]] = {}
        
    def _init_circuit_breakers(self):
        """Initialize circuit breakers for each configured service."""
        for service_name, config in self.configs.items():
            if config.circuit_breaker_enabled:
                self._circuit_breakers[service_name] = CircuitBreaker(
                    failure_threshold=config.failure_threshold,
                    recovery_timeout=config.recovery_timeout,
                    expected_exception=(
                        RedisError, 
                        RateLimitExceededError,
                        ConnectionError
                    ),
                    name=f"rate_limiter_{service_name}"
                )
    
    def _init_backoff_strategies(self):
        """Initialize backoff strategies for each service."""
        for service_name in self.configs:
            self._backoff_strategies[service_name] = create_api_backoff(
                service_name=service_name,
                base_delay=1.0,
                max_attempts=3
            )

    async def _get_redis_client(self) -> redis.Redis:
        """Get Redis client with connection pool."""
        if self._redis_client is None:
            with self._redis_lock:
                if self._redis_client is None:
                    if self.redis_config:
                        # Use real Redis configuration
                        self._redis_client = redis.from_url(
                            self.redis_config.connection_url,
                            max_connections=self.redis_config.max_connections,
                            socket_timeout=self.redis_config.socket_timeout,
                            socket_connect_timeout=self.redis_config.socket_connect_timeout,
                            decode_responses=True
                        )
                    else:
                        # Fallback for testing - use localhost defaults
                        self._redis_client = redis.from_url(
                            "redis://localhost:6379/0",
                            decode_responses=True
                        )
        return self._redis_client

    async def _load_lua_script(self, script_name: str) -> Any:
        """Load and register Lua script with Redis."""
        if script_name not in self._lua_scripts:
            script_path = f"integrations/utils/lua_scripts/{script_name}.lua"
            
            try:
                with open(script_path, 'r') as f:
                    script_content = f.read()
                
                redis_client = await self._get_redis_client()
                script = redis_client.register_script(script_content)
                self._lua_scripts[script_name] = script
                
                logger.debug(
                    "lua_script_loaded",
                    script_name=script_name,
                    script_path=script_path
                )
                
            except FileNotFoundError:
                logger.error(
                    "lua_script_not_found",
                    script_name=script_name,
                    script_path=script_path
                )
                raise
        
        return self._lua_scripts[script_name]

    async def _check_sliding_window(
        self, 
        config: RateLimitConfig,
        priority: bool = False
    ) -> RateLimitResult:
        """Check rate limit using sliding window algorithm."""
        script = await self._load_lua_script("sliding_window")
        redis_key = config.redis_key
        current_time_ms = int(time.time() * 1000)
        
        # Adjust limit for priority requests
        effective_limit = config.requests
        if priority and config.priority_reserve > 0:
            effective_limit = int(config.requests * (1 + config.priority_reserve))
        
        try:
            # Execute Lua script atomically
            result = await script(
                keys=[redis_key],
                args=[config.window, effective_limit, current_time_ms]
            )
            
            allowed = bool(result[0])
            current_usage = int(result[1])
            remaining = int(result[2])
            reset_time_ms = int(result[3])
            
            reset_time = datetime.fromtimestamp(reset_time_ms / 1000)
            retry_after = None if allowed else (reset_time_ms - current_time_ms) / 1000
            
            return RateLimitResult(
                allowed=allowed,
                current_usage=current_usage,
                remaining=remaining,
                reset_time=reset_time,
                retry_after=retry_after
            )
            
        except RedisError as e:
            logger.error(
                "rate_limit_redis_error",
                service=config.key_suffix,
                redis_key=redis_key,
                error=str(e)
            )
            raise

    async def _check_token_bucket(
        self,
        config: RateLimitConfig,
        tokens_requested: int = 1
    ) -> RateLimitResult:
        """Check rate limit using token bucket algorithm."""
        script = await self._load_lua_script("token_bucket")
        redis_key = config.redis_key
        current_time_ms = int(time.time() * 1000)
        
        # Calculate refill rate (tokens per second)
        capacity = config.burst_capacity or config.requests
        refill_rate = config.requests / config.window
        
        try:
            result = await script(
                keys=[redis_key],
                args=[capacity, refill_rate, current_time_ms, tokens_requested]
            )
            
            allowed = bool(result[0])
            tokens_available = int(result[1])
            next_refill_ms = int(result[2])
            
            remaining = tokens_available
            reset_time = datetime.fromtimestamp(next_refill_ms / 1000)
            retry_after = None if allowed else (next_refill_ms - current_time_ms) / 1000
            
            # Calculate current usage (capacity - tokens_available)
            current_usage = capacity - tokens_available
            
            return RateLimitResult(
                allowed=allowed,
                current_usage=current_usage,
                remaining=remaining,
                reset_time=reset_time,
                retry_after=retry_after
            )
            
        except RedisError as e:
            logger.error(
                "rate_limit_redis_error",
                service=config.key_suffix,
                redis_key=redis_key,
                error=str(e)
            )
            raise

    async def check_rate_limit(
        self,
        service: str,
        priority: bool = False,
        tokens: int = 1
    ) -> RateLimitResult:
        """Check if request is allowed under rate limit.
        
        Args:
            service: Service name (e.g., 'gsc_api', 'ga4_api', 'serpapi')
            priority: Whether this is a high-priority request
            tokens: Number of tokens to consume (for token bucket)
            
        Returns:
            RateLimitResult with allow/deny decision and metadata
            
        Raises:
            ValueError: If service is not configured
            CircuitBreakerError: If circuit breaker is open
            RedisError: If Redis operations fail
        """
        if service not in self.configs:
            raise ValueError(f"Unknown service: {service}")
        
        config = self.configs[service]
        
        # Check circuit breaker if enabled
        circuit_breaker = self._circuit_breakers.get(service)
        if circuit_breaker and circuit_breaker.state == CircuitBreakerState.OPEN:
            raise CircuitBreakerError(
                f"Rate limiter circuit breaker open for {service}",
                retry_after=circuit_breaker.recovery_timeout
            )
        
        try:
            # Execute rate limit check based on algorithm
            if config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                result = await self._check_sliding_window(config, priority)
            elif config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                result = await self._check_token_bucket(config, tokens)
            else:
                raise ValueError(f"Unknown algorithm: {config.algorithm}")
            
            # Update circuit breaker on success
            if circuit_breaker:
                circuit_breaker._on_success()
            
            # Update metrics
            self._update_metrics(service, result)
            
            # Log result
            logger.info(
                "rate_limit_check",
                service=service,
                allowed=result.allowed,
                current_usage=result.current_usage,
                remaining=result.remaining,
                priority=priority,
                tokens=tokens
            )
            
            return result
            
        except Exception as e:
            # Update circuit breaker on failure
            if circuit_breaker:
                circuit_breaker._on_failure(e)
            raise

    async def acquire(
        self,
        service: str,
        priority: bool = False,
        tokens: int = 1,
        timeout: Optional[float] = None
    ) -> RateLimitResult:
        """Acquire rate limit permission with automatic retry.
        
        Args:
            service: Service name
            priority: High-priority request flag
            tokens: Tokens to consume
            timeout: Maximum wait time in seconds
            
        Returns:
            RateLimitResult when permission granted
            
        Raises:
            RateLimitExceededError: If rate limit exceeded after retries
            TimeoutError: If timeout exceeded
            CircuitBreakerError: If circuit breaker is open
        """
        start_time = time.time()
        backoff = self._backoff_strategies.get(service)
        
        while True:
            try:
                result = await self.check_rate_limit(service, priority, tokens)
                
                if result.allowed:
                    return result
                
                # Rate limit exceeded - check timeout
                if timeout and (time.time() - start_time) >= timeout:
                    raise TimeoutError(
                        f"Rate limit acquisition timed out for {service} "
                        f"after {timeout}s"
                    )
                
                # Wait based on retry_after or backoff strategy
                if result.retry_after:
                    wait_time = min(result.retry_after, 300)  # Cap at 5 minutes
                    logger.info(
                        "rate_limit_waiting",
                        service=service,
                        retry_after=result.retry_after,
                        wait_time=wait_time
                    )
                    await asyncio.sleep(wait_time)
                elif backoff:
                    await backoff.wait()
                else:
                    # Default backoff if no strategy configured
                    await asyncio.sleep(min(1.0, result.retry_after or 1.0))
                
            except (CircuitBreakerError, TimeoutError):
                raise
            except Exception as e:
                if backoff and backoff.should_retry(e):
                    await backoff.wait(e)
                else:
                    raise

    async def acquire_with_retry(
        self,
        service: str,
        func,
        *args,
        priority: bool = False,
        timeout: Optional[float] = None,
        **kwargs
    ):
        """Execute function with rate limit acquisition and retry logic.
        
        Args:
            service: Service name for rate limiting
            func: Function to execute (can be async or sync)
            *args: Function arguments
            priority: High-priority request flag
            timeout: Maximum wait time for rate limit
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
        """
        # Acquire rate limit permission
        await self.acquire(service, priority=priority, timeout=timeout)
        
        # Execute function with circuit breaker protection
        circuit_breaker = self._circuit_breakers.get(service)
        if circuit_breaker:
            return await circuit_breaker.call(func, *args, **kwargs)
        else:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

    def _update_metrics(self, service: str, result: RateLimitResult):
        """Update rate limiter metrics."""
        if service not in self._metrics:
            self._metrics[service] = {
                "total_requests": 0,
                "allowed_requests": 0,
                "denied_requests": 0,
                "current_usage": 0,
                "last_check": datetime.utcnow()
            }
        
        metrics = self._metrics[service]
        metrics["total_requests"] += 1
        metrics["current_usage"] = result.current_usage
        metrics["last_check"] = datetime.utcnow()
        
        if result.allowed:
            metrics["allowed_requests"] += 1
        else:
            metrics["denied_requests"] += 1

    def get_metrics(self, service: Optional[str] = None) -> Dict[str, Any]:
        """Get rate limiter metrics.
        
        Args:
            service: Optional service name, returns all if None
            
        Returns:
            Metrics dictionary
        """
        if service:
            return self._metrics.get(service, {})
        return self._metrics.copy()

    def get_circuit_breaker_status(self) -> Dict[str, Dict[str, Any]]:
        """Get circuit breaker status for all services."""
        status = {}
        for service, cb in self._circuit_breakers.items():
            status[service] = cb.metrics
        return status

    async def reset_rate_limit(self, service: str):
        """Reset rate limit for a service (admin function)."""
        if service not in self.configs:
            raise ValueError(f"Unknown service: {service}")
        
        config = self.configs[service]
        redis_client = await self._get_redis_client()
        
        try:
            await redis_client.delete(config.redis_key)
            logger.info("rate_limit_reset", service=service)
        except RedisError as e:
            logger.error(
                "rate_limit_reset_failed",
                service=service,
                error=str(e)
            )
            raise

    async def close(self):
        """Clean up resources."""
        if self._redis_client:
            await self._redis_client.close()


# Convenience functions for common use cases
async def check_api_rate_limit(service: str, priority: bool = False) -> bool:
    """Quick rate limit check for API services.
    
    Args:
        service: API service name
        priority: High-priority request flag
        
    Returns:
        True if request is allowed
    """
    limiter = RateLimiter()
    try:
        result = await limiter.check_rate_limit(service, priority)
        return result.allowed
    finally:
        await limiter.close()


async def with_rate_limit(service: str, func, *args, **kwargs):
    """Execute function with rate limiting.
    
    Args:
        service: Service name for rate limiting
        func: Function to execute
        *args: Function arguments  
        **kwargs: Function keyword arguments
        
    Returns:
        Function result
    """
    limiter = RateLimiter()
    try:
        return await limiter.acquire_with_retry(service, func, *args, **kwargs)
    finally:
        await limiter.close()
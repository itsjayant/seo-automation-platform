"""Unit and Integration Tests for Rate Limiter

Tests Redis-based rate limiting with sliding window and token bucket algorithms,
circuit breaker integration, and distributed coordination.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime, timedelta

import redis.asyncio as redis
from redis.exceptions import RedisError

from integrations.utils.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitResult,
    RateLimitAlgorithm,
    RateLimitExceededError,
    check_api_rate_limit,
    with_rate_limit
)
from integrations.utils.circuit_breaker import CircuitBreakerState
from config import get_settings


class TestRateLimitConfig:
    """Test suite for RateLimitConfig validation."""

    def test_valid_config(self):
        """Test valid configuration creates successfully."""
        config = RateLimitConfig(
            requests=100,
            window=60,
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            key_suffix="test"
        )
        
        assert config.requests == 100
        assert config.window == 60
        assert config.redis_key == "rate_limit:test"

    def test_invalid_requests(self):
        """Test invalid requests raises ValueError."""
        with pytest.raises(ValueError, match="requests must be positive"):
            RateLimitConfig(requests=0, window=60)

    def test_invalid_window(self):
        """Test invalid window raises ValueError.""" 
        with pytest.raises(ValueError, match="window must be positive"):
            RateLimitConfig(requests=100, window=0)

    def test_invalid_burst_capacity(self):
        """Test invalid burst_capacity raises ValueError."""
        with pytest.raises(ValueError, match="burst_capacity must be >= requests"):
            RateLimitConfig(requests=100, window=60, burst_capacity=50)

    def test_invalid_priority_reserve(self):
        """Test invalid priority_reserve raises ValueError."""
        with pytest.raises(ValueError, match="priority_reserve must be between 0 and 1"):
            RateLimitConfig(requests=100, window=60, priority_reserve=1.5)

    def test_redis_key_generation(self):
        """Test Redis key generation with different suffixes."""
        config1 = RateLimitConfig(requests=100, window=60, key_suffix="")
        assert config1.redis_key == "rate_limit"
        
        config2 = RateLimitConfig(requests=100, window=60, key_suffix="api")
        assert config2.redis_key == "rate_limit:api"


class TestRateLimitResult:
    """Test suite for RateLimitResult class."""

    def test_result_creation(self):
        """Test RateLimitResult creation and properties."""
        reset_time = datetime.utcnow() + timedelta(seconds=60)
        
        result = RateLimitResult(
            allowed=False,
            current_usage=95,
            remaining=5,
            reset_time=reset_time,
            retry_after=45.0
        )
        
        assert result.allowed is False
        assert result.current_usage == 95
        assert result.remaining == 5
        assert result.retry_after == 45.0

    def test_headers_generation(self):
        """Test HTTP headers generation from result."""
        reset_time = datetime.utcnow() + timedelta(seconds=60)
        
        result = RateLimitResult(
            allowed=True,
            current_usage=50,
            remaining=50,
            reset_time=reset_time
        )
        
        headers = result.headers
        
        assert headers["X-RateLimit-Limit"] == "100"  # current + remaining
        assert headers["X-RateLimit-Remaining"] == "50"
        assert headers["X-RateLimit-Reset"] == str(int(reset_time.timestamp()))
        assert "Retry-After" not in headers  # Only when not allowed

    def test_headers_with_retry_after(self):
        """Test headers include Retry-After when request denied."""
        reset_time = datetime.utcnow() + timedelta(seconds=60)
        
        result = RateLimitResult(
            allowed=False,
            current_usage=100,
            remaining=0,
            reset_time=reset_time,
            retry_after=30.0
        )
        
        headers = result.headers
        assert headers["Retry-After"] == "30"


class TestRateLimiter:
    """Test suite for RateLimiter class."""

    def setup_method(self):
        """Set up test fixtures."""
        # Mock Redis client
        self.mock_redis = AsyncMock(spec=redis.Redis)
        
        # Create rate limiter with mock Redis
        self.rate_limiter = RateLimiter(redis_client=self.mock_redis)

    def test_initialization(self):
        """Test rate limiter initializes with correct defaults."""
        limiter = RateLimiter()
        
        # Should have default configurations
        assert "gsc_api" in limiter.configs
        assert "ga4_api" in limiter.configs
        assert "serpapi" in limiter.configs
        
        # Check default config values
        gsc_config = limiter.configs["gsc_api"]
        assert gsc_config.requests == 200
        assert gsc_config.window == 60

    def test_circuit_breaker_initialization(self):
        """Test circuit breakers are initialized for each service."""
        limiter = RateLimiter()
        
        # Should have circuit breakers for enabled services
        assert "gsc_api" in limiter._circuit_breakers
        assert "ga4_api" in limiter._circuit_breakers
        
        # Check circuit breaker configuration
        cb = limiter._circuit_breakers["gsc_api"]
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60

    @pytest.mark.asyncio
    async def test_load_lua_script(self):
        """Test Lua script loading and registration."""
        # Mock script content and Redis registration
        mock_script = Mock()
        self.mock_redis.register_script.return_value = mock_script
        
        with patch("builtins.open", mock_open_lua_script()):
            script = await self.rate_limiter._load_lua_script("sliding_window")
        
        assert script == mock_script
        self.mock_redis.register_script.assert_called_once()

    @pytest.mark.asyncio
    async def test_sliding_window_algorithm_allowed(self):
        """Test sliding window algorithm allows requests under limit."""
        # Mock Lua script result: [allowed=1, current=50, remaining=50, reset=timestamp]
        current_time = int(time.time() * 1000)
        mock_result = [1, 50, 50, current_time + 60000]
        
        mock_script = AsyncMock()
        mock_script.return_value = mock_result
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        config = RateLimitConfig(requests=100, window=60, key_suffix="test")
        result = await self.rate_limiter._check_sliding_window(config)
        
        assert result.allowed is True
        assert result.current_usage == 50
        assert result.remaining == 50
        assert result.retry_after is None

    @pytest.mark.asyncio
    async def test_sliding_window_algorithm_denied(self):
        """Test sliding window algorithm denies requests over limit."""
        # Mock Lua script result: [allowed=0, current=100, remaining=0, reset=timestamp]
        current_time = int(time.time() * 1000)
        reset_time = current_time + 30000  # 30 seconds
        mock_result = [0, 100, 0, reset_time]
        
        mock_script = AsyncMock()
        mock_script.return_value = mock_result
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        config = RateLimitConfig(requests=100, window=60, key_suffix="test")
        result = await self.rate_limiter._check_sliding_window(config)
        
        assert result.allowed is False
        assert result.current_usage == 100
        assert result.remaining == 0
        assert result.retry_after == 30.0

    @pytest.mark.asyncio
    async def test_token_bucket_algorithm(self):
        """Test token bucket algorithm functionality."""
        # Mock Lua script result: [allowed=1, tokens=50, next_refill_time]
        current_time = int(time.time() * 1000)
        mock_result = [1, 50, current_time + 1000]
        
        mock_script = AsyncMock()
        mock_script.return_value = mock_result
        self.rate_limiter._lua_scripts["token_bucket"] = mock_script
        
        config = RateLimitConfig(
            requests=100, 
            window=60, 
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            burst_capacity=150,
            key_suffix="test"
        )
        
        result = await self.rate_limiter._check_token_bucket(config, tokens_requested=1)
        
        assert result.allowed is True
        assert result.remaining == 50
        assert result.current_usage == 100  # capacity - tokens_available

    @pytest.mark.asyncio
    async def test_check_rate_limit_success(self):
        """Test successful rate limit check."""
        # Mock sliding window script
        mock_script = AsyncMock()
        current_time = int(time.time() * 1000) 
        mock_script.return_value = [1, 10, 190, current_time + 60000]
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        result = await self.rate_limiter.check_rate_limit("gsc_api")
        
        assert result.allowed is True
        assert result.current_usage == 10
        assert result.remaining == 190

    @pytest.mark.asyncio
    async def test_check_rate_limit_with_priority(self):
        """Test rate limit check with priority flag."""
        mock_script = AsyncMock()
        current_time = int(time.time() * 1000)
        mock_script.return_value = [1, 5, 215, current_time + 60000]  # Higher limit for priority
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        result = await self.rate_limiter.check_rate_limit("gsc_api", priority=True)
        
        assert result.allowed is True
        # Verify script was called with increased limit (200 * 1.1 = 220)
        mock_script.assert_called_once()
        args = mock_script.call_args[1]["args"]
        assert int(args[1]) == 220  # Effective limit with priority reserve

    @pytest.mark.asyncio
    async def test_check_rate_limit_unknown_service(self):
        """Test rate limit check with unknown service raises ValueError."""
        with pytest.raises(ValueError, match="Unknown service: unknown"):
            await self.rate_limiter.check_rate_limit("unknown")

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_blocks_requests(self):
        """Test open circuit breaker blocks rate limit requests."""
        # Force circuit breaker open
        circuit_breaker = self.rate_limiter._circuit_breakers["gsc_api"]
        circuit_breaker.force_open()
        
        with pytest.raises(Exception):  # CircuitBreakerError or similar
            await self.rate_limiter.check_rate_limit("gsc_api")

    @pytest.mark.asyncio
    async def test_acquire_with_immediate_success(self):
        """Test acquire method with immediate success."""
        # Mock successful rate limit check
        mock_script = AsyncMock()
        current_time = int(time.time() * 1000)
        mock_script.return_value = [1, 1, 199, current_time + 60000]
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        result = await self.rate_limiter.acquire("gsc_api")
        
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_acquire_with_retry_and_success(self):
        """Test acquire method retries and eventually succeeds."""
        # Mock rate limit responses: first denied, then allowed
        mock_script = AsyncMock()
        current_time = int(time.time() * 1000)
        
        # First call: denied
        # Second call: allowed
        mock_script.side_effect = [
            [0, 200, 0, current_time + 1000],  # Denied, retry in 1s
            [1, 150, 50, current_time + 60000]  # Allowed
        ]
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await self.rate_limiter.acquire("gsc_api", timeout=5.0)
        
        assert result.allowed is True
        mock_sleep.assert_called_once()  # Should have waited

    @pytest.mark.asyncio
    async def test_acquire_timeout(self):
        """Test acquire method timeout behavior."""
        # Mock always denied responses
        mock_script = AsyncMock()
        current_time = int(time.time() * 1000)
        mock_script.return_value = [0, 200, 0, current_time + 60000]
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TimeoutError):
                await self.rate_limiter.acquire("gsc_api", timeout=0.1)

    @pytest.mark.asyncio
    async def test_acquire_with_retry_integration(self):
        """Test acquire_with_retry method executes function after acquiring limit."""
        # Mock successful rate limit
        mock_script = AsyncMock()
        current_time = int(time.time() * 1000)
        mock_script.return_value = [1, 1, 199, current_time + 60000]
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        # Mock function to execute
        async def test_func(value):
            return f"executed_{value}"
        
        result = await self.rate_limiter.acquire_with_retry(
            "gsc_api", 
            test_func, 
            "test_value"
        )
        
        assert result == "executed_test_value"

    def test_metrics_tracking(self):
        """Test rate limiter tracks metrics correctly."""
        # Simulate some activity
        result = RateLimitResult(
            allowed=True,
            current_usage=50,
            remaining=150,
            reset_time=datetime.utcnow()
        )
        
        self.rate_limiter._update_metrics("test_service", result)
        
        metrics = self.rate_limiter.get_metrics("test_service")
        assert metrics["total_requests"] == 1
        assert metrics["allowed_requests"] == 1
        assert metrics["current_usage"] == 50

    def test_circuit_breaker_status(self):
        """Test circuit breaker status retrieval."""
        status = self.rate_limiter.get_circuit_breaker_status()
        
        assert "gsc_api" in status
        assert "ga4_api" in status
        
        # Check status structure
        gsc_status = status["gsc_api"]
        assert "state" in gsc_status
        assert "failure_count" in gsc_status
        assert "total_calls" in gsc_status

    @pytest.mark.asyncio
    async def test_reset_rate_limit(self):
        """Test manual rate limit reset."""
        await self.rate_limiter.reset_rate_limit("gsc_api")
        
        # Verify Redis delete was called
        config = self.rate_limiter.configs["gsc_api"]
        self.mock_redis.delete.assert_called_once_with(config.redis_key)

    @pytest.mark.asyncio
    async def test_redis_error_handling(self):
        """Test Redis error handling in rate limit checks."""
        # Mock Redis error
        mock_script = AsyncMock()
        mock_script.side_effect = RedisError("Redis connection failed")
        self.rate_limiter._lua_scripts["sliding_window"] = mock_script
        
        with pytest.raises(RedisError):
            await self.rate_limiter.check_rate_limit("gsc_api")

    @pytest.mark.asyncio
    async def test_close_cleanup(self):
        """Test clean resource cleanup on close."""
        await self.rate_limiter.close()
        
        # Verify Redis client close was called
        self.mock_redis.close.assert_called_once()


class TestConvenienceFunctions:
    """Test convenience functions for common use cases."""

    @pytest.mark.asyncio
    @patch('integrations.utils.rate_limiter.RateLimiter')
    async def test_check_api_rate_limit(self, mock_limiter_class):
        """Test check_api_rate_limit convenience function."""
        # Mock rate limiter instance
        mock_limiter = AsyncMock()
        mock_result = Mock()
        mock_result.allowed = True
        mock_limiter.check_rate_limit.return_value = mock_result
        mock_limiter_class.return_value = mock_limiter
        
        result = await check_api_rate_limit("gsc_api", priority=True)
        
        assert result is True
        mock_limiter.check_rate_limit.assert_called_once_with("gsc_api", True)
        mock_limiter.close.assert_called_once()

    @pytest.mark.asyncio
    @patch('integrations.utils.rate_limiter.RateLimiter')
    async def test_with_rate_limit(self, mock_limiter_class):
        """Test with_rate_limit convenience function."""
        # Mock rate limiter instance
        mock_limiter = AsyncMock()
        mock_limiter.acquire_with_retry.return_value = "function_result"
        mock_limiter_class.return_value = mock_limiter
        
        async def test_func(arg):
            return f"result_{arg}"
        
        result = await with_rate_limit("serpapi", test_func, "test")
        
        assert result == "function_result"
        mock_limiter.acquire_with_retry.assert_called_once()
        mock_limiter.close.assert_called_once()


# Test utilities

def mock_open_lua_script():
    """Mock file opening for Lua scripts."""
    script_content = """
    -- Mock Lua script
    return {1, 50, 50, redis.call('TIME')[1] * 1000 + 60000}
    """
    
    mock_file = Mock()
    mock_file.read.return_value = script_content
    mock_file.__enter__.return_value = mock_file
    mock_file.__exit__.return_value = None
    
    return Mock(return_value=mock_file)


# Integration test fixtures (for running against real Redis)

@pytest.fixture
async def redis_client():
    """Provide Redis client for integration tests."""
    client = redis.from_url("redis://localhost:6379/15")  # Use test database
    yield client
    
    # Cleanup
    await client.flushdb()
    await client.close()


@pytest.mark.integration
class TestRateLimiterIntegration:
    """Integration tests with real Redis (requires Redis server)."""

    @pytest.mark.asyncio
    async def test_real_sliding_window(self, redis_client):
        """Test sliding window algorithm against real Redis."""
        rate_limiter = RateLimiter(redis_client=redis_client)
        
        # Should allow first requests
        for _ in range(5):
            result = await rate_limiter.check_rate_limit("gsc_api")
            assert result.allowed is True
        
        # Usage should accumulate
        result = await rate_limiter.check_rate_limit("gsc_api")
        assert result.current_usage == 6

    @pytest.mark.asyncio  
    async def test_real_rate_limit_exceeded(self, redis_client):
        """Test rate limit enforcement with real Redis."""
        # Create limiter with very low limit for testing
        custom_config = {
            "test_api": RateLimitConfig(
                requests=2,
                window=60,
                key_suffix="test_low_limit"
            )
        }
        
        rate_limiter = RateLimiter(
            redis_client=redis_client,
            configs=custom_config
        )
        
        # First 2 requests should succeed
        result1 = await rate_limiter.check_rate_limit("test_api")
        result2 = await rate_limiter.check_rate_limit("test_api")
        
        assert result1.allowed is True
        assert result2.allowed is True
        
        # Third request should be denied
        result3 = await rate_limiter.check_rate_limit("test_api")
        assert result3.allowed is False
        assert result3.retry_after is not None


if __name__ == "__main__":
    # Run unit tests by default, integration tests require --integration flag
    import sys
    if "--integration" in sys.argv:
        pytest.main([__file__, "-m", "integration", "-v"])
    else:
        pytest.main([__file__, "-m", "not integration", "-v"])
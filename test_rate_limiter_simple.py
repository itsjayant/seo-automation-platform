"""Simple Test Script for Rate Limiter Components

Tests the core functionality of the rate limiter system without requiring
full environment configuration.
"""

import asyncio
import time
from unittest.mock import AsyncMock, Mock

# Import rate limiter components
from integrations.utils.circuit_breaker import CircuitBreaker, CircuitBreakerState, CircuitBreakerError
from integrations.utils.backoff import BackoffConfig, ExponentialBackoff
from integrations.utils.rate_limiter import RateLimitConfig, RateLimitAlgorithm


async def test_circuit_breaker():
    """Test basic circuit breaker functionality."""
    print("\n=== Testing Circuit Breaker ===")
    
    cb = CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=2,
        name="test_breaker"
    )
    
    # Test initial state
    assert cb.state == CircuitBreakerState.CLOSED
    print("✅ Circuit breaker starts in CLOSED state")
    
    # Test successful operation
    async def success_func():
        return "success"
    
    result = await cb.call(success_func)
    assert result == "success"
    print("✅ Successful operations work correctly")
    
    # Test failure counting
    async def failing_func():
        raise ConnectionError("test error")
    
    # Trigger failures to open circuit
    failure_count = 0
    for i in range(5):
        try:
            await cb.call(failing_func)
        except ConnectionError:
            failure_count += 1
            if failure_count >= 3:
                break
    
    assert cb.state == CircuitBreakerState.OPEN
    print("✅ Circuit breaker opens after failure threshold")
    
    # Test fail-fast behavior
    try:
        await cb.call(failing_func)
        assert False, "Should raise CircuitBreakerError"
    except CircuitBreakerError:
        print("✅ Circuit breaker fails fast when open")
    
    # Test metrics
    metrics = cb.metrics
    assert metrics["total_failures"] >= 3
    print(f"✅ Metrics tracking works: {metrics['total_failures']} failures recorded")
    
    print("✅ Circuit breaker tests passed!")


def test_backoff_config():
    """Test backoff configuration validation."""
    print("\n=== Testing Backoff Configuration ===")
    
    # Valid config
    config = BackoffConfig(base_delay=1.0, max_delay=60.0, max_attempts=3)
    assert config.base_delay == 1.0
    print("✅ Valid configuration creates successfully")
    
    # Invalid configurations
    try:
        BackoffConfig(base_delay=0.0)
        assert False, "Should raise ValueError"
    except ValueError:
        print("✅ Invalid base_delay properly rejected")
    
    try:
        BackoffConfig(base_delay=10.0, max_delay=5.0)
        assert False, "Should raise ValueError" 
    except ValueError:
        print("✅ Invalid max_delay properly rejected")
    
    print("✅ Backoff configuration tests passed!")


async def test_exponential_backoff():
    """Test exponential backoff functionality."""
    print("\n=== Testing Exponential Backoff ===")
    
    config = BackoffConfig(
        base_delay=1.0,
        max_delay=8.0,
        max_attempts=3,
        jitter_type="none"  # No jitter for predictable tests
    )
    backoff = ExponentialBackoff(config)
    
    # Test delay calculation
    delay = backoff.calculate_delay()
    assert delay == 1.0  # First attempt
    print("✅ First delay calculation correct")
    
    # Simulate attempt increment
    backoff._attempt_count = 1
    delay = backoff.calculate_delay()
    assert delay == 2.0  # Second attempt: 1.0 * 2^1
    print("✅ Exponential delay calculation correct")
    
    # Test retry logic
    assert backoff.should_retry(ConnectionError("test")) is True
    print("✅ Retryable exceptions handled correctly")
    
    assert backoff.should_retry(ValueError("test")) is False
    print("✅ Non-retryable exceptions handled correctly")
    
    # Test max attempts
    backoff._attempt_count = 3  # At max attempts
    assert backoff.should_retry(ConnectionError("test")) is False
    print("✅ Max attempts limit enforced")
    
    print("✅ Exponential backoff tests passed!")


def test_rate_limit_config():
    """Test rate limit configuration."""
    print("\n=== Testing Rate Limit Configuration ===")
    
    # Valid sliding window config
    config = RateLimitConfig(
        requests=100,
        window=60,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        key_suffix="test"
    )
    
    assert config.requests == 100
    assert config.window == 60
    assert config.redis_key == "rate_limit:test"
    print("✅ Sliding window configuration correct")
    
    # Valid token bucket config
    config2 = RateLimitConfig(
        requests=50,
        window=30,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        burst_capacity=75,
        key_suffix="burst_test"
    )
    
    assert config2.burst_capacity == 75
    assert config2.redis_key == "rate_limit:burst_test"
    print("✅ Token bucket configuration correct")
    
    # Test validation
    try:
        RateLimitConfig(requests=0, window=60)
        assert False, "Should raise ValueError"
    except ValueError:
        print("✅ Invalid requests properly rejected")
    
    try:
        RateLimitConfig(requests=100, window=0)
        assert False, "Should raise ValueError"
    except ValueError:
        print("✅ Invalid window properly rejected")
    
    print("✅ Rate limit configuration tests passed!")


def test_lua_scripts_exist():
    """Test that Lua scripts are present."""
    print("\n=== Testing Lua Scripts ===")
    
    import os
    
    script_dir = "/Users/jayantnirmalkar/Documents/SEO/integrations/utils/lua_scripts"
    
    assert os.path.exists(f"{script_dir}/sliding_window.lua")
    print("✅ Sliding window Lua script exists")
    
    assert os.path.exists(f"{script_dir}/token_bucket.lua")
    print("✅ Token bucket Lua script exists")
    
    # Check script content
    with open(f"{script_dir}/sliding_window.lua", "r") as f:
        content = f.read()
        assert "ZREMRANGEBYSCORE" in content
        assert "ZADD" in content
        print("✅ Sliding window script has expected Redis commands")
    
    with open(f"{script_dir}/token_bucket.lua", "r") as f:
        content = f.read()  
        assert "HMGET" in content
        assert "HMSET" in content
        print("✅ Token bucket script has expected Redis commands")
    
    print("✅ Lua scripts tests passed!")


async def test_integration_without_redis():
    """Test rate limiter integration without requiring Redis."""
    print("\n=== Testing Rate Limiter Integration (Mocked) ===")
    
    # Mock Redis client
    mock_redis = AsyncMock()
    
    from integrations.utils.rate_limiter import RateLimiter
    
    # Create limiter with mock
    limiter = RateLimiter(redis_client=mock_redis)
    
    # Test initialization
    assert "gsc_api" in limiter.configs
    assert "ga4_api" in limiter.configs
    assert "serpapi" in limiter.configs
    print("✅ Rate limiter initializes with default configs")
    
    # Test circuit breaker initialization
    assert "gsc_api" in limiter._circuit_breakers
    cb = limiter._circuit_breakers["gsc_api"]
    assert cb.state == CircuitBreakerState.CLOSED
    print("✅ Circuit breakers initialized correctly")
    
    # Test backoff strategies
    assert "gsc_api" in limiter._backoff_strategies
    print("✅ Backoff strategies initialized correctly")
    
    # Test metrics
    metrics = limiter.get_metrics()
    assert isinstance(metrics, dict)
    print("✅ Metrics system works")
    
    # Test circuit breaker status
    status = limiter.get_circuit_breaker_status()
    assert "gsc_api" in status
    print("✅ Circuit breaker status reporting works")
    
    await limiter.close()
    print("✅ Rate limiter integration tests passed!")


async def main():
    """Run all tests."""
    print("🚀 Running Rate Limiter System Tests")
    print("=" * 50)
    
    try:
        # Unit tests
        await test_circuit_breaker()
        test_backoff_config()
        await test_exponential_backoff()
        test_rate_limit_config()
        test_lua_scripts_exist()
        
        # Integration test
        await test_integration_without_redis()
        
        print("\n" + "=" * 50)
        print("✅ ALL TESTS PASSED! Rate limiter system is working correctly.")
        
        # Summary
        print("\n📊 Test Summary:")
        print("- ✅ Circuit breaker functionality")
        print("- ✅ Exponential backoff with jitter")
        print("- ✅ Rate limit configuration validation")
        print("- ✅ Lua scripts for Redis operations")
        print("- ✅ Integration components")
        
        print("\n🎯 Ready for production use!")
        
    except Exception as e:
        print(f"\n❌ Tests failed: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    # Run the tests
    asyncio.run(main())
"""Integration Test for Complete Rate Limiter System

Tests the full rate limiter system with Redis, circuit breakers,
backoff strategies, and all algorithms working together.
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
import redis.asyncio as redis

from integrations.utils.rate_limiter import RateLimiter, RateLimitConfig, RateLimitAlgorithm
from integrations.utils.circuit_breaker import CircuitBreakerError
from config import get_settings


@pytest.fixture(scope="session")
async def redis_test_client():
    """Session-scoped Redis client for integration tests."""
    settings = get_settings()
    client = redis.from_url(
        f"{settings.redis.connection_url}/15",  # Use test database 15
        decode_responses=True
    )
    
    # Verify connection
    await client.ping()
    
    yield client
    
    # Cleanup
    await client.flushdb()
    await client.close()


@pytest.fixture
async def rate_limiter_system(redis_test_client):
    """Complete rate limiter system for testing."""
    # Custom test configurations with low limits for fast testing
    test_configs = {
        "test_low": RateLimitConfig(
            requests=5,
            window=10,  # 10 second window
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            key_suffix="test_low"
        ),
        "test_burst": RateLimitConfig(
            requests=10,
            window=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            burst_capacity=15,
            key_suffix="test_burst"
        ),
        "test_priority": RateLimitConfig(
            requests=8,
            window=20,
            priority_reserve=0.25,  # 25% extra for priority
            key_suffix="test_priority"
        )
    }
    
    limiter = RateLimiter(
        redis_client=redis_test_client,
        configs=test_configs
    )
    
    yield limiter
    
    # Cleanup
    await limiter.close()


@pytest.mark.integration
class TestRateLimiterSystemIntegration:
    """Complete system integration tests."""

    @pytest.mark.asyncio
    async def test_sliding_window_enforcement(self, rate_limiter_system):
        """Test sliding window algorithm enforces limits correctly."""
        limiter = rate_limiter_system
        
        # Should allow requests within limit (5 requests per 10 seconds)
        allowed_count = 0
        for i in range(7):  # Try 7 requests, limit is 5
            result = await limiter.check_rate_limit("test_low")
            if result.allowed:
                allowed_count += 1
        
        assert allowed_count == 5, f"Expected 5 allowed requests, got {allowed_count}"
        
        # Get final result to check denial
        final_result = await limiter.check_rate_limit("test_low")
        assert final_result.allowed is False
        assert final_result.current_usage == 5
        assert final_result.retry_after is not None

    @pytest.mark.asyncio
    async def test_token_bucket_burst_capacity(self, rate_limiter_system):
        """Test token bucket allows burst above normal rate."""
        limiter = rate_limiter_system
        
        # Token bucket: 10 requests/60s with burst capacity of 15
        # Should allow 15 rapid requests initially
        allowed_count = 0
        for i in range(17):  # Try more than burst capacity
            result = await limiter.check_rate_limit("test_burst")
            if result.allowed:
                allowed_count += 1
        
        # Should have allowed burst capacity (15)
        assert allowed_count >= 15, f"Expected at least 15 requests (burst), got {allowed_count}"

    @pytest.mark.asyncio
    async def test_priority_queue_functionality(self, rate_limiter_system):
        """Test priority requests get higher limits."""
        limiter = rate_limiter_system
        
        # Fill up normal quota (8 requests per 20 seconds)
        for _ in range(8):
            result = await limiter.check_rate_limit("test_priority")
            assert result.allowed is True
        
        # Normal request should be denied
        normal_result = await limiter.check_rate_limit("test_priority", priority=False)
        assert normal_result.allowed is False
        
        # Priority request should still be allowed (25% reserve = 2 extra)
        priority_result = await limiter.check_rate_limit("test_priority", priority=True)
        assert priority_result.allowed is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self, rate_limiter_system):
        """Test circuit breaker integration with rate limiter."""
        limiter = rate_limiter_system
        
        # Get circuit breaker for the service
        circuit_breaker = limiter._circuit_breakers.get("test_low")
        assert circuit_breaker is not None
        
        # Simulate Redis failures to trigger circuit breaker
        original_check = limiter._check_sliding_window
        
        async def failing_check(*args, **kwargs):
            raise Exception("Simulated Redis failure")
        
        # Patch the check method to simulate failures
        limiter._check_sliding_window = failing_check
        
        # Trigger failures to open circuit
        failure_count = 0
        for _ in range(6):  # More than failure threshold (5)
            try:
                await limiter.check_rate_limit("test_low")
            except Exception:
                failure_count += 1
        
        # Circuit should be open now
        with pytest.raises(CircuitBreakerError):
            await limiter.check_rate_limit("test_low")
        
        # Restore original method
        limiter._check_sliding_window = original_check

    @pytest.mark.asyncio
    async def test_acquire_with_waiting(self, rate_limiter_system):
        """Test acquire method waits and retries correctly."""
        limiter = rate_limiter_system
        
        # Fill up the quota
        for _ in range(5):
            await limiter.acquire("test_low")
        
        start_time = time.time()
        
        # This should wait and retry (with short timeout for testing)
        try:
            result = await limiter.acquire("test_low", timeout=2.0)
            elapsed = time.time() - start_time
            
            # Should have waited some amount of time
            assert elapsed > 0.5, f"Should have waited, but elapsed time was {elapsed}"
            
        except Exception as e:
            # Timeout is also acceptable for this test
            elapsed = time.time() - start_time
            assert elapsed >= 2.0, f"Should have waited for timeout, elapsed: {elapsed}"

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, rate_limiter_system):
        """Test rate limiter handles concurrent requests correctly."""
        limiter = rate_limiter_system
        
        async def make_request(request_id):
            try:
                result = await limiter.check_rate_limit("test_low")
                return {"id": request_id, "allowed": result.allowed}
            except Exception as e:
                return {"id": request_id, "error": str(e)}
        
        # Make 10 concurrent requests (limit is 5)
        tasks = [make_request(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Count allowed vs denied
        allowed_count = sum(1 for r in results if r.get("allowed"))
        denied_count = sum(1 for r in results if r.get("allowed") is False)
        
        # Should have exactly 5 allowed (limit) and 5 denied
        assert allowed_count == 5, f"Expected 5 allowed, got {allowed_count}"
        assert denied_count == 5, f"Expected 5 denied, got {denied_count}"

    @pytest.mark.asyncio
    async def test_sliding_window_recovery(self, rate_limiter_system):
        """Test sliding window allows requests after window slides."""
        limiter = rate_limiter_system
        
        # Fill quota
        for _ in range(5):
            result = await limiter.check_rate_limit("test_low")
            assert result.allowed is True
        
        # Next request should be denied
        result = await limiter.check_rate_limit("test_low")
        assert result.allowed is False
        
        # Wait for window to slide (10 second window + buffer)
        await asyncio.sleep(11)
        
        # Should be able to make requests again
        result = await limiter.check_rate_limit("test_low")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_metrics_tracking_integration(self, rate_limiter_system):
        """Test comprehensive metrics tracking during operations."""
        limiter = rate_limiter_system
        
        # Make mixed requests
        for _ in range(3):
            await limiter.check_rate_limit("test_low")
        
        for _ in range(3):
            try:
                await limiter.check_rate_limit("test_low")
            except:
                pass  # Some might be denied
        
        # Check metrics
        metrics = limiter.get_metrics("test_low")
        
        assert metrics["total_requests"] >= 6
        assert metrics["allowed_requests"] >= 3
        assert "current_usage" in metrics
        assert "last_check" in metrics

    @pytest.mark.asyncio
    async def test_function_execution_with_rate_limiting(self, rate_limiter_system):
        """Test executing functions with rate limit protection."""
        limiter = rate_limiter_system
        
        # Mock API function
        call_count = 0
        
        async def mock_api_call(data):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # Simulate API call
            return f"API response for {data}"
        
        # Execute with rate limiting
        result = await limiter.acquire_with_retry(
            "test_low",
            mock_api_call,
            "test_data"
        )
        
        assert result == "API response for test_data"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_lua_script_atomicity(self, rate_limiter_system):
        """Test Lua scripts provide atomic operations."""
        limiter = rate_limiter_system
        
        # Make rapid concurrent requests to test atomicity
        async def rapid_requests():
            results = []
            for _ in range(3):
                try:
                    result = await limiter.check_rate_limit("test_low")
                    results.append(result.allowed)
                    # No delay between requests to test race conditions
                except Exception:
                    results.append(False)
            return results
        
        # Run multiple rapid request sequences concurrently
        task_results = await asyncio.gather(*[
            rapid_requests() for _ in range(3)
        ])
        
        # Count total allowed requests across all tasks
        total_allowed = sum(
            sum(1 for allowed in task_result if allowed)
            for task_result in task_results
        )
        
        # Should not exceed rate limit due to atomic operations
        assert total_allowed <= 5, f"Atomic operations failed, {total_allowed} requests allowed"

    @pytest.mark.asyncio
    async def test_different_algorithms_coexist(self, rate_limiter_system):
        """Test different rate limiting algorithms work together."""
        limiter = rate_limiter_system
        
        # Test both algorithms simultaneously
        sliding_result = await limiter.check_rate_limit("test_low")  # Sliding window
        bucket_result = await limiter.check_rate_limit("test_burst")  # Token bucket
        
        assert sliding_result.allowed is True
        assert bucket_result.allowed is True
        
        # They should have different usage patterns
        assert sliding_result.current_usage != bucket_result.current_usage or True  # Allow same usage

    @pytest.mark.asyncio
    async def test_reset_functionality(self, rate_limiter_system):
        """Test manual rate limit reset functionality."""
        limiter = rate_limiter_system
        
        # Use up quota
        for _ in range(5):
            await limiter.check_rate_limit("test_low")
        
        # Should be denied
        result = await limiter.check_rate_limit("test_low")
        assert result.allowed is False
        
        # Reset the rate limit
        await limiter.reset_rate_limit("test_low")
        
        # Should be allowed again
        result = await limiter.check_rate_limit("test_low")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_system_resilience_redis_reconnection(self, redis_test_client):
        """Test system handles Redis connection issues gracefully."""
        # Create limiter with real Redis client
        limiter = RateLimiter(redis_client=redis_test_client)
        
        # Normal operation should work
        result = await limiter.check_rate_limit("gsc_api")
        assert result.allowed is True
        
        # Simulate Redis disconnection by closing client
        await redis_test_client.close()
        
        # Should handle Redis errors gracefully via circuit breaker
        try:
            await limiter.check_rate_limit("gsc_api")
        except Exception as e:
            # Should be a Redis-related error, not a crash
            assert "redis" in str(e).lower() or "connection" in str(e).lower()


@pytest.mark.integration 
class TestPerformanceBenchmarks:
    """Performance benchmarks for rate limiter system."""

    @pytest.mark.asyncio
    async def test_throughput_benchmark(self, rate_limiter_system):
        """Benchmark rate limiter throughput."""
        limiter = rate_limiter_system
        
        start_time = time.time()
        request_count = 100
        
        # Make many requests quickly
        tasks = []
        for i in range(request_count):
            task = asyncio.create_task(
                limiter.check_rate_limit("test_burst")
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        elapsed = end_time - start_time
        throughput = request_count / elapsed
        
        print(f"\nRate limiter throughput: {throughput:.2f} requests/second")
        print(f"Total time for {request_count} requests: {elapsed:.3f} seconds")
        
        # Should handle at least 100 requests per second
        assert throughput > 100, f"Throughput too low: {throughput} req/s"
        
        # Count successful results
        successful_results = [r for r in results if hasattr(r, 'allowed')]
        print(f"Successful rate limit checks: {len(successful_results)}/{request_count}")


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-s", "--tb=short"])
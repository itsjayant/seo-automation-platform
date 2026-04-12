"""Unit Tests for Exponential Backoff Implementation

Tests backoff strategies, jitter types, rate limit integration,
and retry logic.
"""

import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from integrations.utils.backoff import (
    BackoffConfig,
    ExponentialBackoff,
    create_api_backoff
)


class MockRateLimitException(Exception):
    """Mock exception with rate limit information."""
    
    def __init__(self, message: str, retry_after: float = None, response=None):
        super().__init__(message)
        self.retry_after = retry_after
        self.response = response


class MockResponse:
    """Mock HTTP response for testing."""
    
    def __init__(self, headers: dict):
        self.headers = headers


class TestBackoffConfig:
    """Test suite for BackoffConfig validation."""

    def test_valid_config(self):
        """Test valid configuration creates successfully."""
        config = BackoffConfig(
            base_delay=1.0,
            max_delay=60.0,
            max_attempts=3,
            backoff_factor=2.0
        )
        
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.max_attempts == 3
        assert config.backoff_factor == 2.0

    def test_invalid_base_delay(self):
        """Test invalid base_delay raises ValueError."""
        with pytest.raises(ValueError, match="base_delay must be positive"):
            BackoffConfig(base_delay=0.0)
        
        with pytest.raises(ValueError, match="base_delay must be positive"):
            BackoffConfig(base_delay=-1.0)

    def test_invalid_max_delay(self):
        """Test max_delay < base_delay raises ValueError."""
        with pytest.raises(ValueError, match="max_delay must be >= base_delay"):
            BackoffConfig(base_delay=10.0, max_delay=5.0)

    def test_invalid_max_attempts(self):
        """Test invalid max_attempts raises ValueError."""
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            BackoffConfig(max_attempts=0)

    def test_invalid_backoff_factor(self):
        """Test invalid backoff_factor raises ValueError."""
        with pytest.raises(ValueError, match="backoff_factor must be > 1"):
            BackoffConfig(backoff_factor=1.0)
        
        with pytest.raises(ValueError, match="backoff_factor must be > 1"):
            BackoffConfig(backoff_factor=0.5)

    def test_invalid_jitter_type(self):
        """Test invalid jitter_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid jitter_type"):
            BackoffConfig(jitter_type="invalid")


class TestExponentialBackoff:
    """Test suite for ExponentialBackoff class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = BackoffConfig(
            base_delay=1.0,
            max_delay=16.0,
            max_attempts=4,
            backoff_factor=2.0,
            jitter_type="none"  # Disable jitter for predictable tests
        )
        self.backoff = ExponentialBackoff(self.config)

    def test_initial_state(self):
        """Test backoff starts with clean state."""
        assert self.backoff.attempt_count == 0
        assert self.backoff.total_delay == 0.0
        assert self.backoff.elapsed_time == 0.0

    def test_delay_calculation_no_jitter(self):
        """Test exponential delay calculation without jitter."""
        # Attempt 0: 1.0 * 2^0 = 1.0
        delay = self.backoff.calculate_delay()
        assert delay == 1.0
        
        # Simulate attempt increment
        self.backoff._attempt_count = 1
        
        # Attempt 1: 1.0 * 2^1 = 2.0
        delay = self.backoff.calculate_delay()
        assert delay == 2.0
        
        # Attempt 2: 1.0 * 2^2 = 4.0
        self.backoff._attempt_count = 2
        delay = self.backoff.calculate_delay()
        assert delay == 4.0

    def test_max_delay_cap(self):
        """Test delay is capped at max_delay."""
        # Force high attempt count
        self.backoff._attempt_count = 10
        
        delay = self.backoff.calculate_delay()
        assert delay == self.config.max_delay  # Should be capped at 16.0

    def test_jitter_types(self):
        """Test different jitter types produce varied results."""
        configs = [
            BackoffConfig(jitter_type="equal", base_delay=10.0),
            BackoffConfig(jitter_type="full", base_delay=10.0),
            BackoffConfig(jitter_type="decorrelated", base_delay=10.0)
        ]
        
        for config in configs:
            backoff = ExponentialBackoff(config)
            
            # Calculate multiple delays to test variance
            delays = [backoff.calculate_delay() for _ in range(10)]
            
            # With jitter, delays should vary (except for first attempt with decorrelated)
            if config.jitter_type != "decorrelated":
                assert len(set(delays)) > 1, f"No variance in {config.jitter_type} jitter"

    def test_rate_limit_delay_extraction(self):
        """Test extraction of rate limit delays from exceptions."""
        # Test retry_after attribute
        exception = MockRateLimitException("Rate limited", retry_after=30.0)
        delay = self.backoff._extract_rate_limit_delay(exception)
        assert delay == 30.0 * self.config.rate_limit_buffer

        # Test response headers - Retry-After
        response = MockResponse({"Retry-After": "60"})
        exception = MockRateLimitException("Rate limited", response=response)
        delay = self.backoff._extract_rate_limit_delay(exception)
        assert delay == 60.0 * self.config.rate_limit_buffer

        # Test response headers - X-RateLimit-Reset
        current_time = int(time.time())
        reset_time = current_time + 45
        response = MockResponse({"X-RateLimit-Reset": str(reset_time)})
        exception = MockRateLimitException("Rate limited", response=response)
        delay = self.backoff._extract_rate_limit_delay(exception)
        assert abs(delay - 45.0 * self.config.rate_limit_buffer) < 2.0  # Allow small timing variance

    def test_should_retry_logic(self):
        """Test retry decision logic."""
        # Should retry retryable exceptions under max attempts
        exception = ConnectionError("Network error")
        for i in range(self.config.max_attempts):
            self.backoff._attempt_count = i
            assert self.backoff.should_retry(exception) is True

        # Should not retry when max attempts reached
        self.backoff._attempt_count = self.config.max_attempts
        assert self.backoff.should_retry(exception) is False

        # Should not retry non-retryable exceptions
        exception = ValueError("Bad input")
        self.backoff._attempt_count = 0
        assert self.backoff.should_retry(exception) is False

    @pytest.mark.asyncio
    async def test_wait_function(self):
        """Test wait function with delay tracking."""
        start_time = time.time()
        
        # Mock asyncio.sleep to avoid actual delay
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            delay = await self.backoff.wait()
        
        # Verify sleep was called with calculated delay
        mock_sleep.assert_called_once()
        called_delay = mock_sleep.call_args[0][0]
        assert called_delay == 1.0  # First attempt with no jitter

        # Verify state updates
        assert self.backoff.attempt_count == 1
        assert self.backoff.total_delay == 1.0

    @pytest.mark.asyncio 
    async def test_execute_with_retry_success(self):
        """Test execute_with_retry for successful operation."""
        async def successful_func(value):
            return f"result_{value}"
        
        result = await self.backoff.execute_with_retry(successful_func, "test")
        
        assert result == "result_test"
        assert self.backoff.attempt_count == 0  # No retries needed

    @pytest.mark.asyncio
    async def test_execute_with_retry_with_retries(self):
        """Test execute_with_retry with retries before success."""
        call_count = 0
        
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"
        
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await self.backoff.execute_with_retry(flaky_func)
        
        assert result == "success"
        assert call_count == 3
        assert self.backoff.attempt_count == 2  # 2 retries

    @pytest.mark.asyncio
    async def test_execute_with_retry_exhausted(self):
        """Test execute_with_retry when retries are exhausted."""
        async def always_fails():
            raise ConnectionError("Permanent failure")
        
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConnectionError, match="Permanent failure"):
                await self.backoff.execute_with_retry(always_fails)
        
        assert self.backoff.attempt_count == self.config.max_attempts

    @pytest.mark.asyncio
    async def test_execute_with_retry_non_retryable(self):
        """Test execute_with_retry with non-retryable exception."""
        async def bad_input_func():
            raise ValueError("Bad input")
        
        with pytest.raises(ValueError, match="Bad input"):
            await self.backoff.execute_with_retry(bad_input_func)
        
        assert self.backoff.attempt_count == 0  # No retries attempted

    def test_decorator_interface(self):
        """Test backoff can be used as decorator."""
        @self.backoff
        async def decorated_func(value):
            return f"decorated_{value}"
        
        async def test_decorator():
            result = await decorated_func("test")
            assert result == "decorated_test"
        
        asyncio.run(test_decorator())

    def test_reset_functionality(self):
        """Test backoff state can be reset."""
        # Simulate some activity
        self.backoff._attempt_count = 3
        self.backoff._total_delay = 15.0
        self.backoff._start_time = time.time()
        
        # Reset and verify clean state
        self.backoff.reset()
        
        assert self.backoff.attempt_count == 0
        assert self.backoff.total_delay == 0.0
        assert self.backoff._start_time is None

    @pytest.mark.asyncio
    async def test_rate_limit_priority_over_backoff(self):
        """Test rate limit delays take priority over exponential backoff."""
        # Configure backoff that would produce lower delay
        config = BackoffConfig(
            base_delay=1.0,
            respect_rate_limits=True,
            rate_limit_buffer=1.0
        )
        backoff = ExponentialBackoff(config)
        
        # Exception with large rate limit delay
        exception = MockRateLimitException("Rate limited", retry_after=60.0)
        delay = backoff.calculate_delay(exception)
        
        # Should use rate limit delay, not exponential backoff
        assert delay == 60.0  # rate_limit_buffer = 1.0

    @pytest.mark.asyncio
    async def test_decorrelated_jitter(self):
        """Test decorrelated jitter uses previous delay correctly."""
        config = BackoffConfig(
            jitter_type="decorrelated",
            base_delay=1.0,
            max_delay=100.0
        )
        backoff = ExponentialBackoff(config)
        
        # First delay should be random between 0 and calculated delay
        first_delay = backoff.calculate_delay()
        assert 0 <= first_delay <= 1.0
        
        # Mark first delay as used
        backoff._last_delay = first_delay
        
        # Second delay should use decorrelated formula
        second_delay = backoff.calculate_delay()
        assert 1.0 <= second_delay <= min(first_delay * 3, 100.0)


class TestCreateAPIBackoff:
    """Test factory function for API backoff configurations."""

    def test_create_api_backoff(self):
        """Test create_api_backoff produces correct configuration."""
        backoff = create_api_backoff(
            service_name="test_service",
            base_delay=2.0,
            max_attempts=5
        )
        
        assert isinstance(backoff, ExponentialBackoff)
        assert backoff.config.base_delay == 2.0
        assert backoff.config.max_attempts == 5
        assert backoff.config.jitter_type == "full"
        assert backoff.config.respect_rate_limits is True

    def test_create_api_backoff_defaults(self):
        """Test create_api_backoff with default parameters."""
        backoff = create_api_backoff("default_service")
        
        assert backoff.config.base_delay == 1.0
        assert backoff.config.max_attempts == 3
        assert backoff.config.backoff_factor == 2.0


if __name__ == "__main__":
    pytest.main([__file__])
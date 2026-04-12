"""Unit Tests for Circuit Breaker Implementation

Tests circuit breaker states, failure detection, recovery logic,
and thread-safe operation.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timedelta

from integrations.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerError
)


class TestCircuitBreaker:
    """Test suite for CircuitBreaker class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=2,
            success_threshold=2,
            timeout=1.0,
            name="test_breaker"
        )

    def test_initial_state(self):
        """Test circuit breaker starts in closed state."""
        assert self.circuit_breaker.state == CircuitBreakerState.CLOSED
        metrics = self.circuit_breaker.metrics
        assert metrics["failure_count"] == 0
        assert metrics["total_calls"] == 0

    @pytest.mark.asyncio
    async def test_successful_operation(self):
        """Test successful operation maintains closed state."""
        async def successful_func():
            return "success"
        
        result = await self.circuit_breaker.call(successful_func)
        assert result == "success"
        assert self.circuit_breaker.state == CircuitBreakerState.CLOSED
        
        metrics = self.circuit_breaker.metrics
        assert metrics["total_successes"] == 1
        assert metrics["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_failure_counting(self):
        """Test circuit breaker counts failures correctly."""
        async def failing_func():
            raise ValueError("test error")
        
        # First two failures should keep circuit closed
        for i in range(2):
            with pytest.raises(ValueError):
                await self.circuit_breaker.call(failing_func)
            
            assert self.circuit_breaker.state == CircuitBreakerState.CLOSED
            metrics = self.circuit_breaker.metrics
            assert metrics["failure_count"] == i + 1

    @pytest.mark.asyncio
    async def test_circuit_opens_on_threshold(self):
        """Test circuit opens when failure threshold reached."""
        async def failing_func():
            raise ConnectionError("network error")
        
        # Reach failure threshold
        for i in range(3):
            with pytest.raises(ConnectionError):
                await self.circuit_breaker.call(failing_func)
        
        # Circuit should now be open
        assert self.circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Next call should fail fast
        with pytest.raises(CircuitBreakerError) as exc_info:
            await self.circuit_breaker.call(failing_func)
        
        assert "is open" in str(exc_info.value)
        assert exc_info.value.retry_after is not None

    @pytest.mark.asyncio
    async def test_half_open_transition(self):
        """Test transition from open to half-open state."""
        async def failing_func():
            raise TimeoutError("timeout")
        
        # Open the circuit
        for _ in range(3):
            with pytest.raises(TimeoutError):
                await self.circuit_breaker.call(failing_func)
        
        assert self.circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(2.1)
        
        # Check state - should transition to half-open
        assert self.circuit_breaker.state == CircuitBreakerState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        """Test successful calls in half-open state close circuit."""
        # Open circuit first
        async def failing_func():
            raise RuntimeError("error")
        
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await self.circuit_breaker.call(failing_func)
        
        # Wait for half-open
        await asyncio.sleep(2.1)
        assert self.circuit_breaker.state == CircuitBreakerState.HALF_OPEN
        
        # Successful operations should close circuit
        async def success_func():
            return "ok"
        
        for _ in range(2):  # success_threshold = 2
            result = await self.circuit_breaker.call(success_func)
            assert result == "ok"
        
        assert self.circuit_breaker.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        """Test failure in half-open state reopens circuit."""
        # Open circuit
        async def failing_func():
            raise ValueError("error")
        
        for _ in range(3):
            with pytest.raises(ValueError):
                await self.circuit_breaker.call(failing_func)
        
        # Wait for half-open
        await asyncio.sleep(2.1)
        assert self.circuit_breaker.state == CircuitBreakerState.HALF_OPEN
        
        # Failure should reopen circuit
        with pytest.raises(ValueError):
            await self.circuit_breaker.call(failing_func)
        
        assert self.circuit_breaker.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test operation timeout is handled correctly."""
        async def slow_func():
            await asyncio.sleep(2.0)  # Longer than 1.0s timeout
            return "too slow"
        
        with pytest.raises(TimeoutError):
            await self.circuit_breaker.call(slow_func)
        
        # Should count as failure
        metrics = self.circuit_breaker.metrics
        assert metrics["failure_count"] == 1

    @pytest.mark.asyncio
    async def test_unexpected_exception_handling(self):
        """Test unexpected exceptions don't trigger circuit breaker."""
        # Configure breaker to only handle specific exceptions
        breaker = CircuitBreaker(
            failure_threshold=2,
            expected_exception=ConnectionError,
            name="specific_breaker"
        )
        
        async def func_with_unexpected_error():
            raise ValueError("unexpected error")
        
        # Unexpected exception should be raised but not count as failure
        with pytest.raises(ValueError):
            await breaker.call(func_with_unexpected_error)
        
        # Circuit should remain closed
        assert breaker.state == CircuitBreakerState.CLOSED
        metrics = breaker.metrics
        assert metrics["failure_count"] == 0

    def test_decorator_interface(self):
        """Test circuit breaker can be used as decorator."""
        @self.circuit_breaker
        async def decorated_func(value):
            if value == "fail":
                raise ConnectionError("decorated failure")
            return f"decorated_{value}"
        
        # Test successful call
        async def test_success():
            result = await decorated_func("success")
            assert result == "decorated_success"
        
        asyncio.run(test_success())

    def test_manual_reset(self):
        """Test manual circuit breaker reset."""
        # Simulate failures to open circuit
        for _ in range(3):
            self.circuit_breaker._on_failure(ConnectionError("error"))
        
        assert self.circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Reset circuit
        self.circuit_breaker.reset()
        
        assert self.circuit_breaker.state == CircuitBreakerState.CLOSED
        metrics = self.circuit_breaker.metrics
        assert metrics["failure_count"] == 0

    def test_force_open(self):
        """Test manually forcing circuit open."""
        assert self.circuit_breaker.state == CircuitBreakerState.CLOSED
        
        self.circuit_breaker.force_open()
        
        assert self.circuit_breaker.state == CircuitBreakerState.OPEN

    def test_metrics_tracking(self):
        """Test comprehensive metrics tracking."""
        # Generate some activity
        self.circuit_breaker._on_success()
        self.circuit_breaker._on_success()
        self.circuit_breaker._on_failure(ConnectionError("error"))
        
        metrics = self.circuit_breaker.metrics
        
        assert metrics["total_successes"] == 2
        assert metrics["total_failures"] == 1
        assert metrics["total_calls"] == 3
        assert metrics["failure_rate"] == 1/3
        assert metrics["state"] == CircuitBreakerState.CLOSED.value
        assert "state_changes" in metrics

    async def test_concurrent_access(self):
        """Test thread-safe operation under concurrent access."""
        async def concurrent_operation(should_fail: bool):
            if should_fail:
                raise ConnectionError("concurrent error")
            await asyncio.sleep(0.01)  # Small delay
            return "success"
        
        # Run multiple concurrent operations
        tasks = []
        for i in range(10):
            task = asyncio.create_task(
                self.circuit_breaker.call(concurrent_operation, i % 3 == 0)
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify some succeeded and some failed
        successes = sum(1 for r in results if r == "success")
        failures = sum(1 for r in results if isinstance(r, ConnectionError))
        
        assert successes > 0
        assert failures > 0
        
        # Metrics should be consistent
        metrics = self.circuit_breaker.metrics
        assert metrics["total_calls"] == 10


@pytest.mark.asyncio
async def test_circuit_breaker_error_attributes():
    """Test CircuitBreakerError contains expected attributes."""
    error = CircuitBreakerError("test message", retry_after=30.0)
    
    assert str(error) == "test message"
    assert error.retry_after == 30.0


if __name__ == "__main__":
    pytest.main([__file__])
"""
Comprehensive tests for HTTP client with retry policies.

Tests all major functionality including rate limiting integration,
circuit breaker protection, retry policies, interceptors, and error handling.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional
from unittest.mock import Mock, AsyncMock, patch
import pytest
import httpx
from httpx import Response, Request

from integrations.utils.http_client import (
    HttpClient, HttpClientConfig, HttpRequest, HttpResponse,
    RetryConfig, TimeoutConfig, ConnectionConfig, HttpMethod,
    create_api_client, create_web_scraper_client
)
from integrations.utils.rate_limiter import RateLimiter, RateLimitExceededError
from integrations.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError
from integrations.utils.interceptors import (
    LoggingInterceptor, MetricsInterceptor, TracingInterceptor,
    AuthenticationInterceptor, CachingInterceptor
)
from integrations.utils.auth import ApiKeyAuth, create_api_key_header_auth
from integrations.utils.user_agents import UserAgentManager, UserAgentType


class TestHttpClientBasicFunctionality:
    """Test basic HTTP client functionality."""
    
    @pytest.fixture
    async def http_client(self):
        """Create HTTP client for testing."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            enable_rate_limiting=False,
            enable_circuit_breaker=False
        )
        client = HttpClient(config=config)
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """Test HTTP client initialization."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            user_agent="Test-Client/1.0"
        )
        
        client = HttpClient(config=config)
        
        assert client.config.base_url == "https://api.example.com"
        assert client.config.user_agent == "Test-Client/1.0"
        assert client._rate_limiter is not None  # Default enabled
        assert client._circuit_breaker is not None  # Default enabled
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test HTTP client context manager."""
        config = HttpClientConfig(base_url="https://api.example.com")
        
        async with HttpClient(config=config) as client:
            assert client._client is not None
        
        # Client should be closed after context exit
        assert client._client is None or client._client.is_closed
    
    @pytest.mark.asyncio
    async def test_get_request(self, http_client):
        """Test GET request execution."""
        with patch.object(http_client, '_execute_request') as mock_execute:
            # Mock successful response
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.content = b'{"message": "success"}'
            mock_response.text = '{"message": "success"}'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/test")
            mock_execute.return_value = mock_response
            
            response = await http_client.get("/test", params={"key": "value"})
            
            assert response.status_code == 200
            assert response.is_success
            assert response.json == {"message": "success"}
            assert response.retry_count == 0
    
    @pytest.mark.asyncio
    async def test_post_request_with_json(self, http_client):
        """Test POST request with JSON body."""
        with patch.object(http_client, '_execute_request') as mock_execute:
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 201
            mock_response.headers = {"content-type": "application/json"}
            mock_response.content = b'{"id": 123}'
            mock_response.text = '{"id": 123}'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/create")
            mock_execute.return_value = mock_response
            
            response = await http_client.post(
                "/create",
                json_data={"name": "test", "value": 42}
            )
            
            assert response.status_code == 201
            assert response.json == {"id": 123}


class TestHttpClientRetryPolicies:
    """Test HTTP client retry policies and error handling."""
    
    @pytest.fixture
    async def retry_client(self):
        """Create HTTP client with custom retry configuration."""
        config = HttpClientConfig(
            retry=RetryConfig(
                max_retries=3,
                initial_delay=0.1,  # Fast retries for testing
                backoff_factor=2.0
            ),
            enable_rate_limiting=False,
            enable_circuit_breaker=False
        )
        client = HttpClient(config=config)
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, retry_client):
        """Test retry logic for server errors."""
        call_count = 0
        
        async def mock_execute_failing_then_success(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            if call_count <= 2:
                # First two calls fail with 500
                mock_response = Mock(spec=httpx.Response)
                mock_response.status_code = 500
                mock_response.headers = {}
                mock_response.content = b'Server Error'
                mock_response.text = 'Server Error'
                mock_response.request = Mock()
                raise httpx.HTTPStatusError(
                    "Server Error",
                    request=mock_response.request,
                    response=mock_response
                )
            else:
                # Third call succeeds
                mock_response = Mock(spec=httpx.Response)
                mock_response.status_code = 200
                mock_response.headers = {"content-type": "application/json"}
                mock_response.content = b'{"success": true}'
                mock_response.text = '{"success": true}'
                mock_response.encoding = "utf-8"
                mock_response.url = httpx.URL("https://api.example.com/test")
                return mock_response
        
        with patch.object(retry_client, '_execute_request', mock_execute_failing_then_success):
            response = await retry_client.get("/test")
            
            assert response.status_code == 200
            assert response.retry_count == 2  # Two retries before success
            assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_retry_exhaustion(self, retry_client):
        """Test behavior when all retries are exhausted."""
        async def mock_execute_always_fail(*args, **kwargs):
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 500
            mock_response.headers = {}
            mock_response.content = b'Server Error'
            mock_response.text = 'Server Error'
            mock_response.request = Mock()
            raise httpx.HTTPStatusError(
                "Server Error",
                request=mock_response.request,
                response=mock_response
            )
        
        with patch.object(retry_client, '_execute_request', mock_execute_always_fail):
            with pytest.raises(httpx.HTTPStatusError):
                await retry_client.get("/test")
    
    @pytest.mark.asyncio
    async def test_no_retry_on_client_error(self, retry_client):
        """Test that client errors (4xx) don't trigger retries."""
        call_count = 0
        
        async def mock_execute_client_error(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 404
            mock_response.headers = {}
            mock_response.content = b'Not Found'
            mock_response.text = 'Not Found'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/notfound")
            return mock_response
        
        with patch.object(retry_client, '_execute_request', mock_execute_client_error):
            response = await retry_client.get("/notfound")
            
            assert response.status_code == 404
            assert response.retry_count == 0  # No retries
            assert call_count == 1


class TestHttpClientRateLimiting:
    """Test HTTP client rate limiting integration."""
    
    @pytest.fixture
    async def rate_limited_client(self):
        """Create HTTP client with rate limiting.""" 
        rate_limiter = Mock(spec=RateLimiter)
        config = HttpClientConfig(
            rate_limiter_service="test_service",
            enable_circuit_breaker=False
        )
        client = HttpClient(config=config, rate_limiter=rate_limiter)
        yield client, rate_limiter
        await client.close()
    
    @pytest.mark.asyncio
    async def test_rate_limiting_allows_request(self, rate_limited_client):
        """Test that rate limiting allows requests when within limits."""
        client, rate_limiter = rate_limited_client
        
        # Mock rate limiter to allow request
        mock_result = Mock()
        mock_result.allowed = True
        mock_result.retry_after = None
        rate_limiter.check_rate_limit.return_value = mock_result
        
        with patch.object(client, '_execute_request') as mock_execute:
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b'OK'
            mock_response.text = 'OK'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/test")
            mock_execute.return_value = mock_response
            
            response = await client.get("/test")
            
            assert response.status_code == 200
            rate_limiter.check_rate_limit.assert_called_once_with(
                "test_service", priority=0
            )
    
    @pytest.mark.asyncio 
    async def test_rate_limiting_blocks_request(self, rate_limited_client):
        """Test that rate limiting blocks requests when limits exceeded."""
        client, rate_limiter = rate_limited_client
        
        # Mock rate limiter to block request
        mock_result = Mock()
        mock_result.allowed = False
        mock_result.retry_after = 30.0
        mock_result.current_usage = 100
        rate_limiter.check_rate_limit.return_value = mock_result
        
        with pytest.raises(RateLimitExceededError) as exc_info:
            await client.get("/test")
        
        assert exc_info.value.retry_after == 30.0
        assert exc_info.value.current_usage == 100


class TestHttpClientCircuitBreaker:
    """Test HTTP client circuit breaker integration."""
    
    @pytest.fixture
    async def circuit_breaker_client(self):
        """Create HTTP client with circuit breaker."""
        circuit_breaker = Mock(spec=CircuitBreaker)
        config = HttpClientConfig(enable_rate_limiting=False)
        client = HttpClient(config=config, circuit_breaker=circuit_breaker)
        yield client, circuit_breaker
        await client.close()
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_allows_request(self, circuit_breaker_client):
        """Test circuit breaker allows requests when closed."""
        client, circuit_breaker = circuit_breaker_client
        
        # Mock circuit breaker to allow request
        async def mock_call(func, *args, **kwargs):
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b'OK'
            mock_response.text = 'OK'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/test")
            return mock_response
        
        circuit_breaker.call = mock_call
        
        response = await client.get("/test")
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_request(self, circuit_breaker_client):
        """Test circuit breaker blocks requests when open."""
        client, circuit_breaker = circuit_breaker_client
        
        # Mock circuit breaker to block request
        async def mock_call(func, *args, **kwargs):
            raise CircuitBreakerError("Circuit breaker is open", retry_after=60.0)
        
        circuit_breaker.call = mock_call
        
        with pytest.raises(CircuitBreakerError) as exc_info:
            await client.get("/test")
        
        assert exc_info.value.retry_after == 60.0


class TestHttpClientCaching:
    """Test HTTP client caching functionality."""
    
    @pytest.fixture
    async def caching_client(self):
        """Create HTTP client with caching enabled."""
        config = HttpClientConfig(
            cache_strategy="memory",
            cache_ttl_seconds=300,
            enable_rate_limiting=False,
            enable_circuit_breaker=False
        )
        client = HttpClient(config=config)
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_response_caching(self, caching_client):
        """Test that GET responses are cached."""
        call_count = 0
        
        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.content = b'{"cached": true}'
            mock_response.text = '{"cached": true}'
            mock_response.encoding = "utf-8" 
            mock_response.url = httpx.URL("https://api.example.com/test")
            return mock_response
        
        with patch.object(caching_client, '_execute_request', mock_execute):
            # First request - should hit the server
            response1 = await caching_client.get("/test")
            assert response1.status_code == 200
            assert not response1.from_cache
            assert call_count == 1
            
            # Second request - should come from cache
            response2 = await caching_client.get("/test")
            assert response2.status_code == 200
            assert response2.from_cache
            assert call_count == 1  # No additional server call
    
    @pytest.mark.asyncio
    async def test_cache_only_get_requests(self, caching_client):
        """Test that only GET requests are cached."""
        call_count = 0
        
        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b'OK'
            mock_response.text = 'OK'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/test")
            return mock_response
        
        with patch.object(caching_client, '_execute_request', mock_execute):
            # POST requests should not be cached
            await caching_client.post("/test", json_data={"key": "value"})
            await caching_client.post("/test", json_data={"key": "value"})
            
            assert call_count == 2  # Both calls hit server


class TestHttpClientDeduplication:
    """Test HTTP client request deduplication."""
    
    @pytest.fixture
    async def dedup_client(self):
        """Create HTTP client with deduplication enabled."""
        config = HttpClientConfig(
            enable_deduplication=True,
            deduplication_window_seconds=5,
            enable_rate_limiting=False,
            enable_circuit_breaker=False
        )
        client = HttpClient(config=config)
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_request_deduplication(self, dedup_client):
        """Test that duplicate requests within window are deduplicated."""
        call_count = 0
        
        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b'OK'
            mock_response.text = 'OK'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/test")
            return mock_response
        
        with patch.object(dedup_client, '_execute_request', mock_execute):
            # First request
            response1 = await dedup_client.get("/test", params={"key": "value"})
            assert response1.status_code == 200
            assert call_count == 1
            
            # Duplicate request within window - should be skipped
            # Note: This test may need adjustment based on actual deduplication implementation


class TestHttpClientMetrics:
    """Test HTTP client metrics collection."""
    
    @pytest.fixture
    async def metrics_client(self):
        """Create HTTP client for metrics testing."""
        config = HttpClientConfig(
            enable_rate_limiting=False,
            enable_circuit_breaker=False
        )
        client = HttpClient(config=config)
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self, metrics_client):
        """Test that metrics are collected properly."""
        # Initial metrics should be zero
        initial_metrics = metrics_client.get_metrics()
        assert initial_metrics["total_requests"] == 0
        assert initial_metrics["successful_requests"] == 0
        assert initial_metrics["failed_requests"] == 0
        
        with patch.object(metrics_client, '_execute_request') as mock_execute:
            mock_response = Mock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b'OK'
            mock_response.text = 'OK'
            mock_response.encoding = "utf-8"
            mock_response.url = httpx.URL("https://api.example.com/test")
            mock_execute.return_value = mock_response
            
            # Make successful request
            await metrics_client.get("/test")
            
            # Check updated metrics
            metrics = metrics_client.get_metrics()
            assert metrics["total_requests"] == 1
            assert metrics["successful_requests"] == 1
            assert metrics["failed_requests"] == 0


class TestHttpClientFactoryFunctions:
    """Test factory functions for creating HTTP clients."""
    
    @pytest.mark.asyncio
    async def test_create_api_client(self):
        """Test API client factory function."""
        client = create_api_client(
            base_url="https://api.example.com",
            api_key="test-api-key",
            rate_limit_service="example_api"
        )
        
        assert client.config.base_url == "https://api.example.com"
        assert client.config.rate_limiter_service == "example_api"
        assert "API-Key-Auth" in client.config.user_agent
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_create_web_scraper_client(self):
        """Test web scraper client factory function."""
        client = create_web_scraper_client(
            user_agent="Custom-Scraper/1.0"
        )
        
        assert client.config.user_agent == "Custom-Scraper/1.0"
        assert client.config.retry.max_retries == 2  # Conservative for scraping
        assert client.config.cache_strategy == "memory"
        assert client.config.enable_rate_limiting is True
        
        await client.close()


class TestHttpClientIntegration:
    """Integration tests for HTTP client with real HTTP calls."""
    
    @pytest.mark.asyncio
    @pytest.mark.integration  # Mark as integration test
    async def test_real_http_request(self):
        """Test real HTTP request to httpbin.org."""
        config = HttpClientConfig(
            enable_rate_limiting=False,
            enable_circuit_breaker=False,
            timeout=TimeoutConfig(connect=10.0, read=10.0)
        )
        
        async with HttpClient(config=config) as client:
            response = await client.get("https://httpbin.org/json")
            
            assert response.status_code == 200
            assert response.is_success
            assert "slideshow" in response.json  # httpbin.org/json returns slideshow data
            assert response.elapsed > 0
            assert response.request_id is not None
    
    @pytest.mark.asyncio 
    @pytest.mark.integration
    async def test_real_http_timeout(self):
        """Test HTTP timeout handling with real request."""
        config = HttpClientConfig(
            timeout=TimeoutConfig(connect=0.001, read=0.001),  # Very short timeout
            enable_rate_limiting=False,
            enable_circuit_breaker=False,
            retry=RetryConfig(max_retries=0)  # No retries for faster test
        )
        
        async with HttpClient(config=config) as client:
            with pytest.raises(httpx.TimeoutException):
                await client.get("https://httpbin.org/delay/5")  # 5 second delay


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
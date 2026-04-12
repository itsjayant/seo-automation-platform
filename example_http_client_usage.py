"""
Example usage of the HTTP Client with retry policies and rate limiting.

Demonstrates various HTTP client configurations and integration patterns
for different use cases like API clients, web scraping, and OAuth authentication.
"""

import asyncio
import os
from typing import Dict, Any
from integrations.utils import (
    HttpClient, HttpClientConfig, RetryConfig, TimeoutConfig,
    create_api_client, create_web_scraper_client,
    RateLimiter, RateLimitConfig,
    LoggingInterceptor, MetricsInterceptor, TracingInterceptor,
    create_api_key_header_auth, create_bearer_token_auth,
    UserAgentManager, UserAgentType,
    OAuth2Client, create_google_search_console_oauth
)


async def example_basic_http_client():
    """Example: Basic HTTP client usage."""
    print("=== Basic HTTP Client Example ===")
    
    config = HttpClientConfig(
        base_url="https://httpbin.org",
        user_agent="SEO-Platform-Example/1.0",
        enable_rate_limiting=False,
        enable_circuit_breaker=False
    )
    
    async with HttpClient(config=config) as client:
        # Simple GET request
        response = await client.get("/json")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json}")
        print(f"Elapsed: {response.elapsed:.2f}s")
        
        # POST request with JSON data
        response = await client.post("/post", json_data={"test": "data"})
        print(f"POST Status: {response.status_code}")


async def example_http_client_with_retries():
    """Example: HTTP client with retry policies."""
    print("\n=== HTTP Client with Retries Example ===")
    
    config = HttpClientConfig(
        base_url="https://httpbin.org",
        retry=RetryConfig(
            max_retries=3,
            initial_delay=1.0,
            backoff_factor=2.0,
            backoff_jitter=True
        ),
        timeout=TimeoutConfig(
            connect=10.0,
            read=30.0
        ),
        enable_rate_limiting=False,
        enable_circuit_breaker=False
    )
    
    async with HttpClient(config=config) as client:
        try:
            # This will timeout and retry
            response = await client.get("/delay/2")  # 2 second delay
            print(f"Delayed response status: {response.status_code}")
            print(f"Retry count: {response.retry_count}")
        except Exception as e:
            print(f"Request failed after retries: {e}")


async def example_api_client_with_auth():
    """Example: API client with authentication."""
    print("\n=== API Client with Authentication Example ===")
    
    # Create client with API key authentication
    client = create_api_client(
        base_url="https://httpbin.org",
        api_key="demo-api-key-123",
        rate_limit_service="httpbin_api",
        user_agent="SEO-Platform-API-Client/1.0",
        enable_rate_limiting=False  # Disabled for demo
    )
    
    # Add authentication
    auth = create_api_key_header_auth("demo-api-key-123", "X-API-Key")
    
    async with client:
        # The authentication will be applied automatically
        response = await client.get("/headers")
        print(f"Headers response: {response.status_code}")
        
        # Check if our API key was included
        headers_data = response.json
        if "X-API-Key" in str(headers_data):
            print("API key authentication was applied")


async def example_web_scraper_client():
    """Example: Web scraper client with ethical settings."""
    print("\n=== Web Scraper Client Example ===")
    
    client = create_web_scraper_client(
        user_agent="SEO-Research-Bot/1.0 (+https://example.com/bot; respects robots.txt)",
        cache_ttl_seconds=600,  # 10 minute cache
        enable_rate_limiting=False  # Disabled for demo
    )
    
    async with client:
        # Scrape some public data
        response = await client.get("https://httpbin.org/user-agent")
        print(f"User-Agent response: {response.status_code}")
        print(f"User-Agent sent: {response.json.get('user-agent', 'Not found')}")
        
        # Second request should come from cache
        response2 = await client.get("https://httpbin.org/user-agent")
        print(f"Second request from cache: {response2.from_cache}")


async def example_rate_limited_client():
    """Example: HTTP client with rate limiting."""
    print("\n=== Rate Limited Client Example ===")
    
    # Create rate limiter with strict limits for demo
    rate_limiter = RateLimiter()
    
    config = HttpClientConfig(
        base_url="https://httpbin.org",
        rate_limiter_service="demo_api",
        enable_circuit_breaker=False
    )
    
    async with HttpClient(config=config, rate_limiter=rate_limiter) as client:
        try:
            # Make multiple requests to test rate limiting
            for i in range(3):
                response = await client.get(f"/get?request={i}")
                print(f"Request {i+1}: {response.status_code}")
                
        except Exception as e:
            print(f"Rate limit exceeded: {e}")


async def example_interceptors():
    """Example: HTTP client with interceptors."""
    print("\n=== HTTP Client with Interceptors Example ===")
    
    config = HttpClientConfig(
        base_url="https://httpbin.org",
        enable_rate_limiting=False,
        enable_circuit_breaker=False
    )
    
    client = HttpClient(config=config)
    
    # Add interceptors
    logging_interceptor = LoggingInterceptor(
        log_headers=True,
        log_body=False,  # Don't log body for privacy
        sanitize_auth=True
    )
    
    metrics_interceptor = MetricsInterceptor()
    
    # Note: In actual implementation, you'd add these to the client
    # This is a simplified example of how interceptors would work
    
    async with client:
        response = await client.get("/json")
        print(f"Response with logging: {response.status_code}")
        
        # Get metrics
        metrics = client.get_metrics()
        print(f"Total requests: {metrics['total_requests']}")
        print(f"Successful requests: {metrics['successful_requests']}")


async def example_user_agent_rotation():
    """Example: User-Agent rotation."""
    print("\n=== User-Agent Rotation Example ===")
    
    # Create User-Agent manager
    ua_manager = UserAgentManager(
        default_type=UserAgentType.WEB_SCRAPER,
        custom_contact_info="https://example.com/contact",
        service_name="SEO-Research"
    )
    
    # Add custom User-Agent
    ua_manager.add_user_agent(
        user_agent="SEO-Research-Bot/1.0 (+https://example.com/bot)",
        ua_type=UserAgentType.WEB_SCRAPER,
        weight=3.0,
        description="Primary research bot"
    )
    
    # Show different User-Agents
    print("User-Agent rotation:")
    for i in range(5):
        ua = ua_manager.get_user_agent(avoid_recent=True)
        print(f"  Request {i+1}: {ua[:60]}...")
    
    # Show usage statistics
    stats = ua_manager.get_usage_stats()
    print(f"Total requests: {stats['total_requests']}")
    print(f"Unique User-Agents used: {stats['unique_user_agents_used']}")


async def example_oauth_authentication():
    """Example: OAuth 2.0 authentication setup."""
    print("\n=== OAuth 2.0 Authentication Example ===")
    
    # Note: This requires actual Google OAuth credentials
    # This is just a setup example
    
    if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
        oauth_config = create_google_search_console_oauth(
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            redirect_uri="https://localhost:8080/callback"
        )
        
        oauth_client = OAuth2Client(oauth_config)
        
        # Generate authorization URL
        auth_url = oauth_client.get_authorization_url(state="demo-state")
        print(f"OAuth authorization URL generated: {auth_url[:100]}...")
        
        # In a real application, you'd redirect the user to auth_url
        # and handle the callback to exchange code for token
        
        await oauth_client.close()
    else:
        print("OAuth example requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables")


async def example_comprehensive_client():
    """Example: Comprehensive HTTP client with all features."""
    print("\n=== Comprehensive HTTP Client Example ===")
    
    # Create a fully configured client
    config = HttpClientConfig(
        base_url="https://httpbin.org",
        user_agent="SEO-Platform-Comprehensive/1.0",
        retry=RetryConfig(
            max_retries=3,
            initial_delay=1.0,
            backoff_factor=2.0
        ),
        timeout=TimeoutConfig(
            connect=10.0,
            read=30.0
        ),
        cache_strategy="memory",
        cache_ttl_seconds=300,
        enable_deduplication=True,
        deduplication_window_seconds=60,
        log_request_headers=True,
        log_response_headers=True,
        sanitize_auth_headers=True,
        enable_rate_limiting=False,  # Disabled for demo
        enable_circuit_breaker=False  # Disabled for demo
    )
    
    async with HttpClient(config=config) as client:
        # Make various requests
        print("Making requests with comprehensive client...")
        
        # GET with caching
        response1 = await client.get("/json")
        print(f"First request: {response1.status_code}, from_cache: {response1.from_cache}")
        
        # Same request should be cached
        response2 = await client.get("/json")
        print(f"Second request: {response2.status_code}, from_cache: {response2.from_cache}")
        
        # POST request (not cached)
        response3 = await client.post("/post", json_data={"message": "test"})
        print(f"POST request: {response3.status_code}")
        
        # Show client metrics
        metrics = client.get_metrics()
        print(f"\nClient Metrics:")
        print(f"  Total requests: {metrics['total_requests']}")
        print(f"  Successful requests: {metrics['successful_requests']}")
        print(f"  Cache hits: {metrics['cache_hits']}")
        print(f"  Cache misses: {metrics['cache_misses']}")


async def main():
    """Run all examples."""
    print("HTTP Client Examples\n")
    
    try:
        await example_basic_http_client()
        await example_http_client_with_retries()
        await example_api_client_with_auth()
        await example_web_scraper_client()
        await example_rate_limited_client()
        await example_interceptors()
        await example_user_agent_rotation()
        await example_oauth_authentication()
        await example_comprehensive_client()
        
        print("\n=== All examples completed successfully ===")
        
    except Exception as e:
        print(f"Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Set up basic logging
    import structlog
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="ISO"),
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Run examples
    asyncio.run(main())
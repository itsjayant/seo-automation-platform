"""Example Usage of Production-Grade Rate Limiter System

Demonstrates practical usage patterns for the rate limiter with 
circuit breaker pattern for external API integrations.
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime
import structlog

# Import the rate limiter components
from integrations.utils.rate_limiter import (
    RateLimiter, 
    RateLimitConfig, 
    RateLimitAlgorithm,
    RateLimitExceededError,
    check_api_rate_limit,
    with_rate_limit
)
from integrations.utils.circuit_breaker import CircuitBreakerError
from config import get_settings

# Set up logging
logger = structlog.get_logger(__name__)


class ExampleAPIClient:
    """Example client showing rate limiter integration patterns."""
    
    def __init__(self):
        """Initialize API client with rate limiter."""
        self.rate_limiter = RateLimiter()
        self.settings = get_settings()
        
        # Example custom rate limit configurations
        custom_configs = {
            "example_api": RateLimitConfig(
                requests=10,
                window=60,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
                key_suffix="example",
                burst_capacity=15,
                priority_reserve=0.2
            )
        }
        
        # Add custom config to limiter
        self.rate_limiter.configs.update(custom_configs)

    async def make_gsc_request(self, query: str, priority: bool = False) -> Dict[str, Any]:
        """Example Google Search Console API request with rate limiting."""
        
        async def _gsc_api_call():
            """Simulated GSC API call."""
            logger.info("gsc_api_call", query=query)
            
            # Simulate API processing time
            await asyncio.sleep(0.1)
            
            # Simulate occasional API errors for circuit breaker demo
            import random
            if random.random() < 0.05:  # 5% failure rate
                raise ConnectionError("GSC API temporarily unavailable")
            
            return {
                "query": query,
                "clicks": random.randint(10, 1000),
                "impressions": random.randint(100, 10000),
                "timestamp": datetime.utcnow().isoformat()
            }
        
        try:
            # Use acquire_with_retry for automatic rate limiting and retries
            result = await self.rate_limiter.acquire_with_retry(
                service="gsc_api",
                func=_gsc_api_call,
                priority=priority,
                timeout=30.0  # Max wait time for rate limit
            )
            
            logger.info("gsc_request_success", query=query, result=result)
            return result
            
        except RateLimitExceededError as e:
            logger.warning("gsc_rate_limit_exceeded", 
                         query=query, 
                         retry_after=e.retry_after)
            raise
            
        except CircuitBreakerError as e:
            logger.error("gsc_circuit_breaker_open", 
                        query=query, 
                        retry_after=e.retry_after)
            raise
            
        except Exception as e:
            logger.error("gsc_request_failed", query=query, error=str(e))
            raise

    async def make_serpapi_request(self, search_query: str) -> Dict[str, Any]:
        """Example SerpAPI request with manual rate limit checking."""
        
        # Check rate limit before making request
        try:
            result = await self.rate_limiter.check_rate_limit("serpapi")
            
            if not result.allowed:
                logger.warning("serpapi_rate_limit_check_failed",
                             current_usage=result.current_usage,
                             retry_after=result.retry_after)
                
                # Could wait or schedule for later
                await asyncio.sleep(result.retry_after)
                
                # Retry the check
                result = await self.rate_limiter.check_rate_limit("serpapi")
                
                if not result.allowed:
                    raise RateLimitExceededError(
                        "SerpAPI rate limit exceeded after retry",
                        retry_after=result.retry_after,
                        current_usage=result.current_usage,
                        limit=100,  # SerpAPI default limit
                        window=60
                    )
            
            # Make the actual API call
            logger.info("serpapi_request", 
                       search_query=search_query,
                       remaining_quota=result.remaining)
            
            # Simulate SerpAPI call
            await asyncio.sleep(0.2)
            
            return {
                "query": search_query,
                "organic_results": [
                    {"title": f"Result {i}", "url": f"https://example{i}.com"}
                    for i in range(10)
                ],
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error("serpapi_request_failed", 
                        search_query=search_query, 
                        error=str(e))
            raise

    async def batch_requests_with_rate_limiting(self, queries: List[str]) -> List[Dict[str, Any]]:
        """Example of handling batch requests with rate limiting."""
        
        results = []
        
        for i, query in enumerate(queries):
            try:
                # Add priority for first few requests
                priority = i < 2
                
                logger.info("batch_request_start",
                           query=query,
                           position=i,
                           priority=priority)
                
                result = await self.make_gsc_request(query, priority=priority)
                results.append(result)
                
                # Log progress
                if (i + 1) % 10 == 0:
                    logger.info("batch_progress", 
                               completed=i + 1, 
                               total=len(queries))
                
            except (RateLimitExceededError, CircuitBreakerError) as e:
                logger.warning("batch_request_skipped",
                              query=query,
                              reason=str(e))
                
                # Could add to retry queue instead of abandoning
                results.append({"error": str(e), "query": query})
                
        return results

    async def get_rate_limiter_status(self) -> Dict[str, Any]:
        """Get comprehensive rate limiter status."""
        
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": self.rate_limiter.get_metrics(),
            "circuit_breakers": self.rate_limiter.get_circuit_breaker_status(),
            "configurations": {}
        }
        
        # Add configuration info (without sensitive data)
        for service, config in self.rate_limiter.configs.items():
            status["configurations"][service] = {
                "requests_limit": config.requests,
                "window_seconds": config.window,
                "algorithm": config.algorithm.value,
                "burst_capacity": config.burst_capacity,
                "priority_reserve": config.priority_reserve
            }
        
        return status

    async def cleanup(self):
        """Clean up resources."""
        await self.rate_limiter.close()


# Convenience usage examples

async def example_simple_usage():
    """Example of simple rate limit checking."""
    
    print("=== Simple Rate Limit Usage ===")
    
    # Quick check if API call is allowed
    if await check_api_rate_limit("gsc_api"):
        print("✅ GSC API call allowed")
    else:
        print("❌ GSC API call would be rate limited")
    
    # Execute function with rate limiting
    async def my_api_call():
        await asyncio.sleep(0.1)
        return "API response"
    
    try:
        result = await with_rate_limit("gsc_api", my_api_call)
        print(f"✅ API call completed: {result}")
    except Exception as e:
        print(f"❌ API call failed: {e}")


async def example_comprehensive_usage():
    """Example showing comprehensive rate limiter usage."""
    
    print("\n=== Comprehensive Rate Limiter Usage ===")
    
    client = ExampleAPIClient()
    
    try:
        # Single request example
        print("\n1. Making single GSC request...")
        result = await client.make_gsc_request("example query")
        print(f"✅ GSC request result: {result}")
        
        # Batch processing example  
        print("\n2. Processing batch requests...")
        queries = [f"query {i}" for i in range(5)]
        batch_results = await client.batch_requests_with_rate_limiting(queries)
        print(f"✅ Processed {len(batch_results)} queries")
        
        # SerpAPI example
        print("\n3. Making SerpAPI request...")
        serp_result = await client.make_serpapi_request("python rate limiting")
        print(f"✅ SerpAPI result: {serp_result['query']}")
        
        # Status monitoring
        print("\n4. Checking rate limiter status...")
        status = await client.get_rate_limiter_status()
        print(f"✅ Rate limiter status:")
        
        # Print metrics for each service
        for service, metrics in status["metrics"].items():
            print(f"   {service}: {metrics.get('total_requests', 0)} total requests, "
                  f"{metrics.get('current_usage', 0)} current usage")
        
        # Print circuit breaker status
        for service, cb_status in status["circuit_breakers"].items():
            print(f"   {service} circuit breaker: {cb_status['state']}")
            
    except Exception as e:
        print(f"❌ Example failed: {e}")
        
    finally:
        await client.cleanup()


async def example_error_handling():
    """Example demonstrating error handling patterns."""
    
    print("\n=== Error Handling Examples ===")
    
    limiter = RateLimiter()
    
    try:
        # Example: Handling rate limit exceeded
        print("\n1. Testing rate limit exhaustion...")
        
        # Make requests until rate limited (using low-limit test config)
        request_count = 0
        while request_count < 10:  # Safety limit
            try:
                result = await limiter.check_rate_limit("gsc_api")
                if result.allowed:
                    request_count += 1
                    print(f"   Request {request_count} allowed, {result.remaining} remaining")
                else:
                    print(f"   ❌ Rate limit exceeded after {request_count} requests")
                    print(f"   Retry after: {result.retry_after} seconds")
                    break
            except Exception as e:
                print(f"   ❌ Rate limit check failed: {e}")
                break
        
        # Example: Circuit breaker testing
        print("\n2. Testing circuit breaker behavior...")
        
        # Force circuit breaker open (for demo)
        cb = limiter._circuit_breakers.get("gsc_api")
        if cb:
            print("   Forcing circuit breaker open for demo...")
            cb.force_open()
            
            try:
                await limiter.check_rate_limit("gsc_api")
                print("   ❌ Should not reach here")
            except CircuitBreakerError as e:
                print(f"   ✅ Circuit breaker blocked request: {e}")
                print(f"   Retry after: {e.retry_after} seconds")
            
            # Reset for cleanup
            cb.reset()
        
    finally:
        await limiter.close()


async def example_custom_configuration():
    """Example of custom rate limiter configuration."""
    
    print("\n=== Custom Configuration Example ===")
    
    # Custom configuration for specific API
    custom_configs = {
        "custom_api": RateLimitConfig(
            requests=5,             # Very low for demo
            window=30,              # 30-second window  
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            burst_capacity=8,       # Allow bursts up to 8
            priority_reserve=0.3,   # 30% extra for priority requests
            key_suffix="custom_demo"
        )
    }
    
    limiter = RateLimiter(configs=custom_configs)
    
    try:
        print("Custom API configuration:")
        print("- 5 requests per 30 seconds")
        print("- Token bucket algorithm")
        print("- Burst capacity: 8 requests")
        print("- Priority reserve: 30%")
        
        # Test normal requests
        print("\nTesting normal requests:")
        for i in range(7):
            result = await limiter.check_rate_limit("custom_api")
            status = "✅ allowed" if result.allowed else "❌ denied"
            print(f"  Request {i+1}: {status} (remaining: {result.remaining})")
            
        # Test priority request
        print("\nTesting priority request:")
        priority_result = await limiter.check_rate_limit("custom_api", priority=True)
        status = "✅ allowed" if priority_result.allowed else "❌ denied"
        print(f"  Priority request: {status} (remaining: {priority_result.remaining})")
        
    finally:
        await limiter.close()


async def main():
    """Run all examples."""
    
    print("🚀 Rate Limiter System Examples")
    print("=" * 50)
    
    try:
        await example_simple_usage()
        await example_comprehensive_usage()
        await example_error_handling()
        await example_custom_configuration()
        
        print("\n✅ All examples completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Examples failed: {e}")
        raise


if __name__ == "__main__":
    # Run the examples
    asyncio.run(main())
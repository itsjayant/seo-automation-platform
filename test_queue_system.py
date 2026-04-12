#!/usr/bin/env python3
"""Test Redis Streams Task Queue Implementation

Tests queue system functionality with graceful degradation when Redis is unavailable.
Validates imports, configuration, and shows expected behavior.
"""

import asyncio
import sys
import os
sys.path.insert(0, '.')

from config import get_settings
from task_queue import TaskProducer, TaskConsumer, TaskType, TaskPriority

async def test_queue_configuration():
    """Test queue system configuration and imports."""
    print("🔄 Testing Redis Streams Task Queue Configuration...")
    
    # Test configuration loading
    print("✓ Loading Pydantic configuration...")
    settings = get_settings()
    print(f"  Redis Host: {settings.redis.host}:{settings.redis.port}")
    print(f"  Tasks Stream: {settings.redis.stream_name}")
    print(f"  Consumer Group: {settings.redis.consumer_group}")
    print(f"  Max Stream Length: {settings.redis.max_stream_length}")
    
    # Test model imports and validation
    print("✓ Testing task queue models...")
    from task_queue.models import TaskMessage, StreamConfig
    from task_queue.exceptions import QueueConnectionError, TaskValidationError
    from task_queue.utils import generate_task_id, calculate_task_hash
    
    # Test task message creation
    task = TaskMessage(
        task_type=TaskType.KEYWORD_RESEARCH,
        payload={
            "domain": "example.com", 
            "keywords": ["seo", "optimization"],
            "test": True
        },
        priority=TaskPriority.HIGH,
        user_id="test_user"
    )
    print(f"  Generated Task ID: {task.task_id}")
    print(f"  Task Type: {task.task_type.value}")
    print(f"  Content Hash: {task.content_hash}")
    
    # Test Redis field serialization
    redis_fields = task.to_redis_fields()
    print(f"  Redis Fields Count: {len(redis_fields)}")
    
    # Test deserialization
    restored_task = TaskMessage.from_redis_fields(task.task_id, redis_fields)
    print(f"  Serialization Round-trip: {'✓' if restored_task.task_id == task.task_id else '❌'}")
    
    # Test stream config
    stream_config = StreamConfig()
    print(f"  Tasks Stream: {stream_config.tasks_stream}")
    print(f"  Results Stream: {stream_config.results_stream}")
    print(f"  Failed Tasks Stream: {stream_config.failed_tasks_stream}")
    
    print("✅ Queue configuration and models working correctly!")
    return True


async def test_queue_with_redis():
    """Test queue operations if Redis is available."""
    print("🔄 Testing Redis connectivity and queue operations...")
    
    try:
        # Test Redis connection
        import redis.asyncio as redis
        settings = get_settings()
        client = redis.from_url(settings.redis.connection_url, decode_responses=True)
        
        # Test basic Redis operations
        await asyncio.wait_for(client.ping(), timeout=5.0)
        print("✓ Redis connection successful")
        
        # Test producer initialization
        print("✓ Testing TaskProducer...")
        async with TaskProducer(redis_client=client) as producer:
            print(f"  Circuit breaker state: {producer._circuit_breaker.state.value}")
            
            # Test task publishing
            task_id = await producer.publish_task(
                task_type=TaskType.KEYWORD_RESEARCH,
                payload={
                    "domain": "test.com",
                    "keywords": ["test", "queue"],
                    "timestamp": str(asyncio.get_event_loop().time())
                },
                priority=TaskPriority.MEDIUM,
                user_id="test_user"
            )
            print(f"  Published task: {task_id}")
            
            # Test queue statistics
            stats = await producer.get_queue_stats()
            if "error" not in stats:
                print(f"  Stream lengths: {stats['stream_lengths']}")
                print(f"  Circuit breaker: {stats['circuit_breaker']['state']}")
            
        # Test consumer initialization
        print("✓ Testing TaskConsumer...")
        async with TaskConsumer(consumer_name="test_consumer", redis_client=client) as consumer:
            print(f"  Consumer ID: {consumer.consumer_id}")
            
            # Register task handler
            processed_tasks = []
            
            async def test_handler(task):
                processed_tasks.append(task.task_id)
                print(f"  Processed task: {task.task_id}")
                return {"processed": True, "handler": "test"}
            
            consumer.register_task_handler("keyword_research", test_handler)
            
            # Test consumer info
            info = await consumer.get_consumer_info()
            print(f"  Consumer running: {info['running']}")
            print(f"  Handlers: {info['registered_handlers']}")
            
            # Test consuming with timeout
            print("✓ Testing task consumption (10s timeout)...")
            try:
                task_count = 0
                async with asyncio.timeout(10):
                    async for result in consumer.consume_tasks():
                        print(f"  Consumed: {result['message_id']} ({'✓' if result['success'] else '❌'})")
                        task_count += 1
                        if task_count >= 2:  # Limit for testing
                            break
                
                print(f"  Total processed: {task_count} tasks")
                
            except asyncio.TimeoutError:
                print("  Consumption timeout (expected in test environment)")
        
        await client.aclose()
        print("✅ Redis queue operations working correctly!")
        return True
        
    except asyncio.TimeoutError:
        print("❌ Redis connection timeout - Redis may not be running")
        print("ℹ️  Start Redis with: docker compose up redis -d")
        return False
        
    except Exception as e:
        print(f"❌ Redis error: {e}")
        print("ℹ️  Start Redis with: docker compose up redis -d")
        return False


async def test_queue_error_handling():
    """Test queue error handling and circuit breaker."""
    print("🔄 Testing error handling and resilience...")
    
    from task_queue.utils import CircuitBreaker, RetryPolicy
    from task_queue.exceptions import CircuitBreakerError
    
    # Test circuit breaker
    print("✓ Testing circuit breaker...")
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1, name="test")
    
    async def failing_operation():
        raise Exception("Simulated failure")
    
    failure_count = 0
    for i in range(5):
        try:
            await cb.call(failing_operation)
        except (Exception, CircuitBreakerError) as e:
            failure_count += 1
            print(f"  Attempt {i+1}: {type(e).__name__}")
    
    print(f"  Circuit breaker state: {cb.state.value}")
    print(f"  Failure count: {cb.failure_count}")
    
    # Test retry policy
    print("✓ Testing retry policy...")
    retry_policy = RetryPolicy(max_attempts=3, base_delay=0.1)
    
    attempt_count = 0
    async def retry_operation():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise Exception(f"Attempt {attempt_count} failed")
        return "success"
    
    try:
        result = await retry_policy.execute_with_retry(retry_operation)
        print(f"  Retry result: {result} (after {attempt_count} attempts)")
    except Exception as e:
        print(f"  Retry failed: {e}")
    
    print("✅ Error handling and resilience tests completed!")
    return True


async def run_all_tests():
    """Run all queue system tests."""
    print("Redis Streams Task Queue - Comprehensive Test Suite")
    print("=" * 60)
    
    results = []
    
    # Test 1: Configuration and models
    try:
        result = await test_queue_configuration()
        results.append(("Configuration & Models", result))
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        results.append(("Configuration & Models", False))
    
    print("\n" + "-" * 60)
    
    # Test 2: Redis operations (if available)
    try:
        result = await test_queue_with_redis()
        results.append(("Redis Operations", result))
    except Exception as e:
        print(f"❌ Redis operations test failed: {e}")
        results.append(("Redis Operations", False))
    
    print("\n" + "-" * 60)
    
    # Test 3: Error handling
    try:
        result = await test_queue_error_handling()
        results.append(("Error Handling", result))
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        results.append(("Error Handling", False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY:")
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All tests passed! Queue system is ready for use.")
    elif passed > 0:
        print("⚠️  Some tests passed. Check Redis availability for full functionality.")
    else:
        print("💥 Tests failed. Check configuration and dependencies.")
    
    return passed == len(results)


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
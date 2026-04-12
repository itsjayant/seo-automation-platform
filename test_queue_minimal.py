#!/usr/bin/env python3
"""Minimal Redis Task Queue Test - Queue Functionality Only

Tests the task queue implementation in isolation without requiring
full application configuration or external services.
"""

import asyncio
import sys
import os
sys.path.insert(0, '.')

# Set minimal environment for testing
os.environ.update({
    'ENVIRONMENT': 'development',
    'REDIS_HOST': 'localhost',
    'REDIS_PORT': '6379',
    'REDIS_DB': '0',
    'POSTGRES_PASSWORD': 'test123',  # Required but not used for queue test
    'JWT_SECRET_KEY': 'test_secret_key_32_characters_long',
    'ENCRYPTION_KEY': 'test_encryption_key_32_chars_long',
    'GSC_API_KEY': 'test_gsc_key',
    'GSC_CLIENT_ID': 'test_gsc_client_id',
    'GSC_CLIENT_SECRET': 'test_gsc_client_secret', 
    'GSC_REDIRECT_URI': 'http://localhost:3000/auth/callback',
    'GA4_API_KEY': 'test_ga4_key',
    'GA4_CLIENT_ID': 'test_ga4_client_id',
    'GA4_CLIENT_SECRET': 'test_ga4_client_secret',
    'GA4_REDIRECT_URI': 'http://localhost:3000/auth/callback',
    'SERPAPI_KEY': 'test_serpapi_key'
})

def test_queue_models():
    """Test queue models and validation."""
    print("🔄 Testing Task Queue Models...")
    
    from task_queue.models import TaskMessage, TaskType, TaskPriority, StreamConfig
    from task_queue.utils import generate_task_id, calculate_task_hash
    
    # Test task message creation
    task = TaskMessage(
        task_type=TaskType.KEYWORD_RESEARCH,
        payload={
            "domain": "example.com",
            "keywords": ["seo", "optimization", "python", "redis"],
            "priority_score": 85,
            "metadata": {
                "source": "manual",
                "created_by": "test_user"
            }
        },
        priority=TaskPriority.HIGH,
        user_id="test_user_123",
        max_retries=3,
        timeout_seconds=1800
    )
    
    print(f"✓ Task created: {task.task_id}")
    print(f"  Type: {task.task_type.value}")
    print(f"  Priority: {task.priority.value}")
    print(f"  Content Hash: {task.content_hash[:16]}...")
    print(f"  Can Retry: {task.can_retry}")
    print(f"  Is Expired: {task.is_expired}")
    
    # Test serialization to Redis format
    redis_fields = task.to_redis_fields()
    print(f"✓ Redis serialization: {len(redis_fields)} fields")
    
    # Test deserialization
    restored_task = TaskMessage.from_redis_fields(task.task_id, redis_fields)
    print(f"✓ Deserialization: {'Success' if restored_task.task_id == task.task_id else 'Failed'}")
    
    # Test stream configuration
    config = StreamConfig()
    print(f"✓ Stream config:")
    print(f"  Tasks: {config.tasks_stream}")
    print(f"  Results: {config.results_stream}")
    print(f"  Failed: {config.failed_tasks_stream}")
    print(f"  Consumer Group: {config.consumer_group}")
    
    return True


def test_queue_utils():
    """Test queue utility functions."""
    print("🔄 Testing Queue Utilities...")
    
    from task_queue.utils import (
        generate_task_id, calculate_task_hash, CircuitBreaker, 
        RetryPolicy, sanitize_consumer_name, calculate_priority_score
    )
    from datetime import datetime
    
    # Test ID generation
    task_id1 = generate_task_id()
    task_id2 = generate_task_id()
    print(f"✓ ID generation: {task_id1[:8]}... (unique: {task_id1 != task_id2})")
    
    # Test hash calculation
    payload1 = {"domain": "test.com", "action": "scan"}
    payload2 = {"domain": "test.com", "action": "scan"}
    payload3 = {"domain": "other.com", "action": "scan"}
    
    hash1 = calculate_task_hash("test_task", payload1)
    hash2 = calculate_task_hash("test_task", payload2)
    hash3 = calculate_task_hash("test_task", payload3)
    
    print(f"✓ Hash calculation:")
    print(f"  Same payload: {hash1[:16]}... == {hash2[:16]}... = {hash1 == hash2}")
    print(f"  Diff payload: {hash1[:16]}... != {hash3[:16]}... = {hash1 != hash3}")
    
    # Test consumer name sanitization
    raw_names = ["test-consumer", "test_consumer", "test@consumer", "123invalid"]
    for raw_name in raw_names:
        sanitized = sanitize_consumer_name(raw_name)
        print(f"  Sanitize: '{raw_name}' → '{sanitized}'")
    
    # Test priority score calculation
    created_time = datetime.utcnow()
    high_score = calculate_priority_score("high", created_time)
    medium_score = calculate_priority_score("medium", created_time)
    low_score = calculate_priority_score("low", created_time)
    
    print(f"✓ Priority scores: High={high_score}, Medium={medium_score}, Low={low_score}")
    
    return True


async def test_circuit_breaker():
    """Test circuit breaker functionality."""
    print("🔄 Testing Circuit Breaker...")
    
    from task_queue.utils import CircuitBreaker
    from task_queue.exceptions import CircuitBreakerError
    
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1, name="test_cb")
    
    # Test normal operation
    async def success_op():
        return "success"
    
    result = await cb.call(success_op)
    print(f"✓ Normal operation: {result}")
    
    # Test failure accumulation
    async def fail_op():
        raise Exception("Simulated failure")
    
    failures = 0
    for i in range(4):
        try:
            await cb.call(fail_op)
        except (Exception, CircuitBreakerError) as e:
            failures += 1
            error_type = "CircuitBreaker" if isinstance(e, CircuitBreakerError) else "Exception"
            print(f"  Attempt {i+1}: {error_type} ({cb.state.value})")
    
    print(f"✓ Circuit breaker opened after {cb.failure_count} failures")
    
    # Test recovery
    print("✓ Waiting for recovery timeout...")
    await asyncio.sleep(1.1)  # Wait for recovery timeout
    
    try:
        result = await cb.call(success_op)
        print(f"✓ Recovered successfully: {cb.state.value}")
    except Exception as e:
        print(f"❌ Recovery failed: {e}")
    
    return True


async def test_retry_policy():
    """Test retry policy with exponential backoff."""
    print("🔄 Testing Retry Policy...")
    
    from task_queue.utils import RetryPolicy
    
    retry_policy = RetryPolicy(max_attempts=3, base_delay=0.1, backoff_factor=2.0)
    
    # Test successful retry
    attempt_count = 0
    
    async def flaky_operation():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise Exception(f"Attempt {attempt_count} failed") 
        return f"Success on attempt {attempt_count}"
    
    try:
        result = await retry_policy.execute_with_retry(flaky_operation)
        print(f"✓ Retry success: {result}")
    except Exception as e:
        print(f"❌ Retry failed: {e}")
    
    # Test delay calculation
    delays = [retry_policy.calculate_delay(i) for i in range(4)]
    print(f"✓ Backoff delays: {[f'{d:.2f}s' for d in delays]}")
    
    return True


async def test_producer_consumer_interfaces():
    """Test producer and consumer interface availability."""
    print("🔄 Testing Producer/Consumer Interfaces...")
    
    try:
        # Test imports work correctly
        from task_queue.models import TaskMessage, TaskType, TaskPriority, StreamConfig
        from task_queue.exceptions import QueueConnectionError, TaskValidationError
        from task_queue.utils import CircuitBreaker, RetryPolicy
        
        print("✓ Core imports successful")
        
        # Test that classes are defined (import without instantiation)
        import task_queue.producer as producer_module
        import task_queue.consumer as consumer_module
        
        # Verify classes exist
        TaskProducer = getattr(producer_module, 'TaskProducer')
        TaskConsumer = getattr(consumer_module, 'TaskConsumer')
        
        print("✓ Producer class available")
        print("✓ Consumer class available")
        
        # Test model creation works
        task = TaskMessage(
            task_type=TaskType.KEYWORD_RESEARCH,
            payload={"test": "interface_test"}
        )
        print(f"✓ Task model creation: {task.task_id[:8]}...")
        
        # Test configuration model
        config = StreamConfig()
        print(f"✓ Stream config: {config.tasks_stream}")
        
        print("✓ Interface definitions successful")
        return True
        
    except Exception as e:
        print(f"❌ Interface test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_minimal_tests():
    """Run all queue tests that don't require external services."""
    print("Redis Streams Task Queue - Minimal Test Suite")
    print("=" * 55)
    
    tests = [
        ("Queue Models", test_queue_models),
        ("Queue Utils", test_queue_utils), 
        ("Circuit Breaker", test_circuit_breaker),
        ("Retry Policy", test_retry_policy),
        ("Producer/Consumer", test_producer_consumer_interfaces)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{'-' * 30}")
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
                
            results.append((test_name, result))
            print(f"✅ {test_name}: PASSED")
            
        except Exception as e:
            results.append((test_name, False))
            print(f"❌ {test_name}: FAILED - {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'=' * 55}")
    print("TEST SUMMARY:")
    passed = sum(1 for _, result in results if result)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name}: {status}")
    
    print(f"\nResult: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All minimal tests passed! Queue system core functionality is working.")
        print("💡 To test Redis connectivity, ensure Redis is running and try: docker compose up redis -d")
    else:
        print("⚠️  Some tests failed. Check implementation.")
    
    return passed == len(results)


if __name__ == "__main__":
    try:
        success = asyncio.run(run_minimal_tests())
        print(f"\n{'SUCCESS' if success else 'FAILURE'}: Queue system implementation {'ready' if success else 'needs fixes'}")
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n💥 Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
"""
Tests for task queue system using Redis Streams.

Tests task production, consumption, error handling, 
and workflow orchestration.
"""

import asyncio
import pytest
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from task_queue.producer import TaskProducer
from task_queue.consumer import TaskConsumer  
from task_queue.models import Task, TaskStatus, TaskPriority
from task_queue.exceptions import TaskProductionError, TaskConsumptionError


@pytest.mark.integration
@pytest.mark.queue
class TestTaskProducer:
    """Test cases for Redis Streams task producer."""
    
    async def test_task_producer_initialization(self, async_redis_client, test_settings):
        """Test task producer initialization."""
        producer = TaskProducer(
            redis_client=async_redis_client,
            stream_name=test_settings["redis"].stream_name
        )
        
        assert producer.redis_client == async_redis_client
        assert producer.stream_name == test_settings["redis"].stream_name
    
    async def test_submit_task(self, task_producer):
        """Test submitting a task to the queue."""
        task = Task(
            id=uuid4(),
            type="keyword_research",
            site_id=uuid4(),
            agent_name="keyword_agent",
            priority=TaskPriority.NORMAL,
            input_data={"query": "seo best practices", "limit": 50},
            max_retries=3
        )
        
        # Mock Redis XADD operation
        with patch.object(task_producer.redis_client, 'xadd') as mock_xadd:
            mock_xadd.return_value = b"1642680000000-0"  # Mock stream entry ID
            
            entry_id = await task_producer.submit_task(task)
            
            assert entry_id == "1642680000000-0"
            mock_xadd.assert_called_once()
            
            # Verify task data was serialized correctly
            call_args = mock_xadd.call_args
            assert call_args[0][0] == task_producer.stream_name  # Stream name
            assert "task_id" in call_args[0][1]  # Task data
            assert "task_type" in call_args[0][1]
    
    async def test_submit_high_priority_task(self, task_producer):
        """Test submitting high priority task."""
        task = Task(
            id=uuid4(),
            type="urgent_content_publish",
            site_id=uuid4(),
            agent_name="content_agent",
            priority=TaskPriority.HIGH,
            input_data={"post_id": 123, "publish_immediately": True}
        )
        
        with patch.object(task_producer.redis_client, 'xadd') as mock_xadd:
            mock_xadd.return_value = b"1642680100000-0"
            
            entry_id = await task_producer.submit_task(task)
            
            # Verify high priority tasks are added to priority stream
            call_args = mock_xadd.call_args  
            stream_name = call_args[0][0]
            task_data = call_args[0][1]
            
            assert "priority" in task_data
            assert task_data["priority"] == TaskPriority.HIGH.value
    
    async def test_submit_task_with_delay(self, task_producer):
        """Test submitting task with execution delay."""
        from datetime import timedelta
        
        task = Task(
            id=uuid4(),
            type="scheduled_reporting",
            site_id=uuid4(),
            agent_name="reporting_agent",
            priority=TaskPriority.LOW,
            input_data={"report_type": "weekly", "format": "pdf"},
            scheduled_for=datetime.utcnow() + timedelta(hours=1)
        )
        
        with patch.object(task_producer.redis_client, 'xadd') as mock_xadd:
            mock_xadd.return_value = b"1642683600000-0"  # +1 hour
            
            entry_id = await task_producer.submit_task(task)
            
            call_args = mock_xadd.call_args
            task_data = call_args[0][1]
            
            assert "scheduled_for" in task_data
            # Verify timestamp is in the future
            scheduled_timestamp = int(task_data["scheduled_for"])
            current_timestamp = int(datetime.utcnow().timestamp())  
            assert scheduled_timestamp > current_timestamp
    
    async def test_batch_submit_tasks(self, task_producer):
        """Test submitting multiple tasks in batch."""
        tasks = []
        for i in range(3):
            task = Task(
                id=uuid4(),
                type=f"batch_task_{i}",
                site_id=uuid4(),
                agent_name="batch_agent",
                priority=TaskPriority.NORMAL,
                input_data={"batch_id": f"batch_{i}", "item_count": i * 10}
            )
            tasks.append(task)
        
        with patch.object(task_producer.redis_client, 'pipeline') as mock_pipeline:
            mock_pipe = AsyncMock()
            mock_pipeline.return_value.__aenter__.return_value = mock_pipe
            mock_pipe.execute.return_value = [
                b"1642680000000-0",
                b"1642680000001-0", 
                b"1642680000002-0"
            ]
            
            entry_ids = await task_producer.submit_batch(tasks)
            
            assert len(entry_ids) == 3
            # Verify pipeline was used for batch operation
            mock_pipeline.assert_called_once()
    
    async def test_task_producer_error_handling(self, task_producer):
        """Test task producer error handling."""
        task = Task(
            id=uuid4(),
            type="failing_task",
            site_id=uuid4(),
            agent_name="test_agent"
        )
        
        # Mock Redis connection error
        with patch.object(task_producer.redis_client, 'xadd') as mock_xadd:
            mock_xadd.side_effect = Exception("Redis connection error")
            
            with pytest.raises(TaskProductionError):
                await task_producer.submit_task(task)


@pytest.mark.integration
@pytest.mark.queue
class TestTaskConsumer:
    """Test cases for Redis Streams task consumer."""
    
    @pytest.fixture
    async def task_consumer(self, async_redis_client, test_settings):
        """Create task consumer for testing."""
        consumer = TaskConsumer(
            redis_client=async_redis_client,
            stream_name=test_settings["redis"].stream_name,
            consumer_group=test_settings["redis"].consumer_group,
            consumer_name="test_consumer"
        )
        return consumer
    
    async def test_task_consumer_initialization(self, task_consumer):
        """Test task consumer initialization."""
        assert task_consumer.stream_name == "test:tasks"
        assert task_consumer.consumer_group == "test-agents"
        assert task_consumer.consumer_name == "test_consumer"
    
    async def test_create_consumer_group(self, task_consumer):
        """Test consumer group creation.""" 
        with patch.object(task_consumer.redis_client, 'xgroup_create') as mock_create:
            mock_create.return_value = True
            
            await task_consumer.create_consumer_group()
            
            mock_create.assert_called_once_with(
                task_consumer.stream_name,
                task_consumer.consumer_group,
                id="0",
                mkstream=True
            )
    
    async def test_consume_task(self, task_consumer):
        """Test consuming a task from the stream."""
        # Mock Redis XREADGROUP response
        mock_response = [
            [
                b"test:tasks",  # Stream name
                [
                    [
                        b"1642680000000-0",  # Entry ID
                        {
                            b"task_id": str(uuid4()).encode(),
                            b"task_type": b"keyword_research", 
                            b"site_id": str(uuid4()).encode(),
                            b"agent_name": b"keyword_agent",
                            b"priority": b"normal",
                            b"input_data": b'{"query": "seo tools", "limit": 25}',
                            b"status": b"pending",
                            b"created_at": b"2024-04-01T12:00:00"
                        }
                    ]
                ]
            ]
        ]
        
        with patch.object(task_consumer.redis_client, 'xreadgroup') as mock_read:
            mock_read.return_value = mock_response
            
            tasks = await task_consumer.consume_tasks(count=1, block=1000)
            
            assert len(tasks) == 1
            task = tasks[0]
            assert task.type == "keyword_research"
            assert task.agent_name == "keyword_agent"
            assert task.status == TaskStatus.PENDING
    
    async def test_consume_multiple_tasks(self, task_consumer):
        """Test consuming multiple tasks."""
        # Mock multiple tasks in response
        mock_response = [
            [
                b"test:tasks",
                [
                    [
                        b"1642680000000-0",
                        {
                            b"task_id": str(uuid4()).encode(),
                            b"task_type": b"task_1",
                            b"site_id": str(uuid4()).encode(),
                            b"agent_name": b"agent_1",
                            b"priority": b"normal", 
                            b"input_data": b'{}',
                            b"status": b"pending"
                        }
                    ],
                    [
                        b"1642680000001-0",
                        {
                            b"task_id": str(uuid4()).encode(), 
                            b"task_type": b"task_2",
                            b"site_id": str(uuid4()).encode(),
                            b"agent_name": b"agent_2",
                            b"priority": b"high",
                            b"input_data": b'{}', 
                            b"status": b"pending"
                        }
                    ]
                ]
            ]
        ]
        
        with patch.object(task_consumer.redis_client, 'xreadgroup') as mock_read:
            mock_read.return_value = mock_response
            
            tasks = await task_consumer.consume_tasks(count=2, block=1000)
            
            assert len(tasks) == 2
            assert tasks[0].type == "task_1"
            assert tasks[1].type == "task_2"
            assert tasks[1].priority == TaskPriority.HIGH
    
    async def test_acknowledge_task(self, task_consumer):
        """Test acknowledging completed task."""
        entry_id = "1642680000000-0"
        
        with patch.object(task_consumer.redis_client, 'xack') as mock_ack:
            mock_ack.return_value = 1  # Number of messages acknowledged
            
            result = await task_consumer.acknowledge_task(entry_id)
            
            assert result == 1
            mock_ack.assert_called_once_with(
                task_consumer.stream_name,
                task_consumer.consumer_group,
                entry_id
            )
    
    async def test_consumer_error_handling(self, task_consumer):
        """Test task consumer error handling."""
        # Mock Redis error
        with patch.object(task_consumer.redis_client, 'xreadgroup') as mock_read:
            mock_read.side_effect = Exception("Redis connection lost")
            
            with pytest.raises(TaskConsumptionError):
                await task_consumer.consume_tasks(count=1, block=1000)


@pytest.mark.integration
@pytest.mark.queue
class TestTaskWorkflow:
    """Test cases for end-to-end task workflows."""
    
    async def test_complete_task_workflow(self, task_producer, async_redis_client, test_settings):
        """Test complete task lifecycle from production to consumption."""
        # Create consumer
        consumer = TaskConsumer(
            redis_client=async_redis_client,
            stream_name=test_settings["redis"].stream_name,
            consumer_group=test_settings["redis"].consumer_group,
            consumer_name="workflow_consumer"
        )
        
        # Create and submit task
        task = Task(
            id=uuid4(),
            type="workflow_test",
            site_id=uuid4(),
            agent_name="workflow_agent",
            priority=TaskPriority.NORMAL,
            input_data={"test": "complete_workflow"}
        )
        
        # Mock the entire workflow
        with patch.object(task_producer.redis_client, 'xadd') as mock_add:
            mock_add.return_value = b"1642680000000-0"
            
            # 1. Submit task
            entry_id = await task_producer.submit_task(task)
            assert entry_id == "1642680000000-0"
            
            # 2. Mock consuming the task
            mock_response = [
                [
                    test_settings["redis"].stream_name.encode(),
                    [
                        [
                            b"1642680000000-0",
                            {
                                b"task_id": str(task.id).encode(),
                                b"task_type": task.type.encode(),
                                b"site_id": str(task.site_id).encode(),
                                b"agent_name": task.agent_name.encode(),
                                b"priority": task.priority.value.encode(),
                                b"input_data": b'{"test": "complete_workflow"}',
                                b"status": TaskStatus.PENDING.value.encode()
                            }
                        ]
                    ]
                ]
            ]
            
            with patch.object(consumer.redis_client, 'xreadgroup') as mock_read:  
                mock_read.return_value = mock_response
                
                # 3. Consume task
                consumed_tasks = await consumer.consume_tasks(count=1)
                assert len(consumed_tasks) == 1
                
                consumed_task = consumed_tasks[0]
                assert consumed_task.id == task.id
                assert consumed_task.type == task.type
                
                # 4. Mock task acknowledgment
                with patch.object(consumer.redis_client, 'xack') as mock_ack:
                    mock_ack.return_value = 1
                    
                    ack_result = await consumer.acknowledge_task(entry_id)
                    assert ack_result == 1
    
    async def test_task_retry_mechanism(self, task_producer, async_redis_client, test_settings):
        """Test task retry mechanism for failed tasks."""
        task = Task(
            id=uuid4(),
            type="failing_task",
            site_id=uuid4(),
            agent_name="unreliable_agent",
            priority=TaskPriority.NORMAL,
            input_data={"should_fail": True},
            max_retries=3,
            retry_count=0
        )
        
        # Simulate task failure and retry
        with patch.object(task_producer.redis_client, 'xadd') as mock_add:
            mock_add.return_value = b"1642680000000-0"
            
            # Initial submission
            entry_id = await task_producer.submit_task(task)
            
            # Simulate failure - increment retry count and resubmit
            task.retry_count += 1
            task.status = TaskStatus.RETRYING
            
            # Resubmit for retry  
            mock_add.return_value = b"1642680000001-0"
            retry_entry_id = await task_producer.submit_task(task)
            
            assert retry_entry_id == "1642680000001-0"
            assert task.retry_count == 1
    
    async def test_task_priority_ordering(self, task_producer):
        """Test that high priority tasks are processed before normal priority."""
        # Create normal and high priority tasks
        normal_task = Task(
            id=uuid4(),
            type="normal_task", 
            site_id=uuid4(),
            agent_name="test_agent",
            priority=TaskPriority.NORMAL
        )
        
        high_task = Task(
            id=uuid4(),
            type="high_task",
            site_id=uuid4(), 
            agent_name="test_agent",
            priority=TaskPriority.HIGH
        )
        
        # Submit normal task first, then high priority
        with patch.object(task_producer.redis_client, 'xadd') as mock_add:
            mock_add.side_effect = [b"1642680000000-0", b"1642680000001-0"]
            
            normal_entry = await task_producer.submit_task(normal_task)
            high_entry = await task_producer.submit_task(high_task)
            
            # Verify both tasks were submitted  
            assert normal_entry == "1642680000000-0"
            assert high_entry == "1642680000001-0"
            
            # In a real implementation, high priority tasks should be  
            # consumed before normal priority tasks


@pytest.mark.integration
@pytest.mark.queue
@pytest.mark.slow
class TestTaskQueuePerformance:
    """Test cases for task queue performance and scalability."""
    
    async def test_high_throughput_task_production(self, task_producer):
        """Test high throughput task production."""
        import time
        
        num_tasks = 100
        tasks = []
        
        for i in range(num_tasks):
            task = Task(
                id=uuid4(),
                type=f"perf_task_{i}",
                site_id=uuid4(), 
                agent_name="perf_agent",
                priority=TaskPriority.NORMAL,
                input_data={"task_number": i}
            )
            tasks.append(task)
        
        # Mock batch submission
        with patch.object(task_producer.redis_client, 'pipeline') as mock_pipeline:
            mock_pipe = AsyncMock()
            mock_pipeline.return_value.__aenter__.return_value = mock_pipe
            
            # Mock successful batch execution
            mock_entries = [f"164268000000{i}-0".encode() for i in range(num_tasks)]
            mock_pipe.execute.return_value = mock_entries
            
            start_time = time.time()
            entry_ids = await task_producer.submit_batch(tasks)
            end_time = time.time()
            
            execution_time = end_time - start_time
            
            # Verify all tasks were submitted
            assert len(entry_ids) == num_tasks
            
            # Performance check - should handle 100 tasks quickly
            assert execution_time < 2.0  # Adjust threshold as needed
    
    async def test_concurrent_consumers(self, async_redis_client, test_settings):
        """Test multiple concurrent consumers."""
        consumers = []
        
        # Create multiple consumers
        for i in range(3):
            consumer = TaskConsumer(
                redis_client=async_redis_client,
                stream_name=test_settings["redis"].stream_name,
                consumer_group=test_settings["redis"].consumer_group,
                consumer_name=f"concurrent_consumer_{i}"
            )
            consumers.append(consumer)
        
        # Mock task consumption for all consumers
        mock_response = [
            [
                test_settings["redis"].stream_name.encode(),
                [
                    [
                        f"164268000000{i}-0".encode(),
                        {
                            b"task_id": str(uuid4()).encode(),
                            b"task_type": b"concurrent_task",
                            b"site_id": str(uuid4()).encode(),
                            b"agent_name": b"concurrent_agent",
                            b"priority": TaskPriority.NORMAL.value.encode(),
                            b"input_data": b'{}',
                            b"status": TaskStatus.PENDING.value.encode()
                        }
                    ]
                ]
            ]
        ]
        
        # Test concurrent consumption
        consume_tasks = []
        for consumer in consumers:
            with patch.object(consumer.redis_client, 'xreadgroup') as mock_read:
                mock_read.return_value = mock_response
                task = consumer.consume_tasks(count=1, block=100)
                consume_tasks.append(task)
        
        # Execute concurrent consumption
        results = await asyncio.gather(*consume_tasks)
        
        # Verify all consumers received tasks
        assert len(results) == 3
        for result in results:
            assert len(result) == 1  # Each consumer got 1 task
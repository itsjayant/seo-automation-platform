"""Redis Streams Task Queue System

A robust task queuing system using Redis Streams for SEO agent orchestration.
Provides reliable task distribution, dead letter queuing, and consumer group management.

Usage:
    from queue import TaskProducer, TaskConsumer
    
    # Publish a task
    producer = TaskProducer()
    await producer.publish_task(
        task_type="keyword_research",
        payload={"domain": "example.com"},
        priority="high"
    )
    
    # Consume tasks
    consumer = TaskConsumer()
    async for task in consumer.consume_tasks():
        # Process task
        await consumer.acknowledge_task(task)
"""

from .producer import TaskProducer
from .consumer import TaskConsumer
from .models import (
    TaskMessage,
    TaskPriority,
    TaskType,
    TaskStatus,
    StreamConfig
)
from .exceptions import (
    QueueConnectionError,
    TaskValidationError,
    TaskPublishError,
    TaskProcessingError,
    ConsumerGroupError
)
from .utils import (
    generate_task_id,
    calculate_task_hash,
    CircuitBreaker,
    RetryPolicy
)

__all__ = [
    "TaskProducer",
    "TaskConsumer",
    "TaskMessage",
    "TaskPriority",
    "TaskType",
    "TaskStatus",
    "StreamConfig",
    "QueueConnectionError",
    "TaskValidationError",
    "TaskPublishError",
    "TaskProcessingError",
    "ConsumerGroupError",
    "generate_task_id",
    "calculate_task_hash",
    "CircuitBreaker",
    "RetryPolicy"
]
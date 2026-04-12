"""Task Queue Data Models

Pydantic models for task messages, stream configuration, and queue metadata.
Provides type-safe validation for Redis Streams task queue operations.
"""

from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator
import hashlib
import json


class TaskPriority(str, Enum):
    """Task priority levels for queue ordering."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskType(str, Enum):
    """Supported task types for SEO agent orchestration."""
    KEYWORD_RESEARCH = "keyword_research"
    CONTENT_ANALYSIS = "content_analysis"
    TECHNICAL_AUDIT = "technical_audit"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    CONTENT_GENERATION = "content_generation"
    LINK_ANALYSIS = "link_analysis"
    PERFORMANCE_ANALYSIS = "performance_analysis"


class TaskStatus(str, Enum):
    """Task processing status states."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"


class TaskMessage(BaseModel):
    """Task message structure for Redis Streams.
    
    Represents a task that can be queued, processed, and tracked
    through the SEO automation system.
    """
    
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    task_type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    payload: Dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = Field(0, ge=0, le=10)
    max_retries: int = Field(3, ge=0, le=10)
    timeout_seconds: int = Field(1800, gt=0, le=7200)  # 30 min default, 2hr max
    
    # Optional metadata
    user_id: Optional[str] = None
    site_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    
    # Processing metadata  
    assigned_to: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, v):
        """Validate payload doesn't exceed Redis Streams limits."""
        payload_json = json.dumps(v, default=str)
        if len(payload_json) > 1024 * 1024:  # 1MB limit
            raise ValueError("Task payload exceeds 1MB size limit")
        return v
    
    @field_validator("max_retries")
    @classmethod
    def validate_retry_limits(cls, v, info):
        """Ensure retry_count doesn't exceed max_retries."""
        if info.data and "retry_count" in info.data:
            if info.data["retry_count"] > v:
                raise ValueError("retry_count cannot exceed max_retries")
        return v
    
    @property
    def content_hash(self) -> str:
        """Generate content hash for deduplication."""
        content = {
            "task_type": self.task_type,
            "payload": self.payload
        }
        content_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(content_str.encode()).hexdigest()
    
    @property
    def is_expired(self) -> bool:
        """Check if task has exceeded timeout."""
        if not self.started_at:
            return False
        elapsed = (datetime.utcnow() - self.started_at).total_seconds()
        return elapsed > self.timeout_seconds
    
    @property
    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.retry_count < self.max_retries
    
    def to_redis_fields(self) -> Dict[str, str]:
        """Convert to Redis Stream field format.
        
        Redis Streams store all values as strings, so we need to
        serialize complex fields appropriately.
        """
        fields = {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "priority": self.priority.value,
            "payload": json.dumps(self.payload, default=str),
            "created_at": self.created_at.isoformat(),
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
            "timeout_seconds": str(self.timeout_seconds),
            "content_hash": self.content_hash
        }
        
        # Add optional fields if present
        optional_fields = [
            "user_id", "site_id", "parent_task_id", "assigned_to", "error_message"
        ]
        for field in optional_fields:
            value = getattr(self, field)
            if value is not None:
                fields[field] = str(value)
        
        # Handle datetime fields
        if self.started_at:
            fields["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            fields["completed_at"] = self.completed_at.isoformat()
        
        # Handle list fields
        if self.dependencies:
            fields["dependencies"] = json.dumps(self.dependencies)
        
        return fields
    
    @classmethod
    def from_redis_fields(cls, task_id: str, fields: Dict[str, str]) -> "TaskMessage":
        """Create TaskMessage from Redis Stream fields.
        
        Deserializes string fields back to appropriate Python types.
        """
        # Parse required fields
        data = {
            "task_id": task_id,
            "task_type": TaskType(fields["task_type"]),
            "priority": TaskPriority(fields["priority"]), 
            "payload": json.loads(fields["payload"]),
            "created_at": datetime.fromisoformat(fields["created_at"]),
            "retry_count": int(fields["retry_count"]),
            "max_retries": int(fields["max_retries"]),
            "timeout_seconds": int(fields["timeout_seconds"])
        }
        
        # Parse optional fields
        optional_string_fields = ["user_id", "site_id", "parent_task_id", "assigned_to", "error_message"]
        for field in optional_string_fields:
            if field in fields:
                data[field] = fields[field]
        
        # Parse datetime fields
        if "started_at" in fields:
            data["started_at"] = datetime.fromisoformat(fields["started_at"])
        if "completed_at" in fields:
            data["completed_at"] = datetime.fromisoformat(fields["completed_at"])
        
        # Parse list fields
        if "dependencies" in fields:
            data["dependencies"] = json.loads(fields["dependencies"])
        
        return cls(**data)


class StreamConfig(BaseModel):
    """Redis Streams configuration for task queues.
    
    Defines stream names, consumer groups, and operational parameters
    for the task queue system.
    """
    
    # Stream names
    tasks_stream: str = "seo:tasks"
    results_stream: str = "seo:results" 
    failed_tasks_stream: str = "seo:failed-tasks"
    
    # Consumer configuration
    consumer_group: str = "seo-agents"
    consumer_name_prefix: str = "agent"
    
    # Stream retention and limits
    max_stream_length: int = 10000
    message_ttl_seconds: int = 86400 * 7  # 7 days
    
    # Consumer timeouts
    block_timeout_ms: int = 30000  # 30 seconds
    claim_timeout_ms: int = 300000  # 5 minutes
    
    # Batch processing
    batch_size: int = 10
    max_batch_wait_ms: int = 5000
    
    # Dead letter configuration
    dead_letter_threshold: int = 3
    dead_letter_retention_days: int = 30


class TaskResult(BaseModel):
    """Task execution result for the results stream."""
    
    task_id: str
    status: TaskStatus
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    processing_time_seconds: Optional[float] = None
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    agent_id: Optional[str] = None
    
    def to_redis_fields(self) -> Dict[str, str]:
        """Convert to Redis Stream field format."""
        fields = {
            "task_id": self.task_id,
            "status": self.status.value,
            "completed_at": self.completed_at.isoformat()
        }
        
        if self.result_data is not None:
            fields["result_data"] = json.dumps(self.result_data, default=str)
        if self.error_message is not None:
            fields["error_message"] = self.error_message
        if self.processing_time_seconds is not None:
            fields["processing_time_seconds"] = str(self.processing_time_seconds)
        if self.agent_id is not None:
            fields["agent_id"] = self.agent_id
            
        return fields


class ConsumerHealth(BaseModel):
    """Consumer health status for monitoring."""
    
    consumer_id: str
    consumer_group: str
    is_active: bool = True
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)
    tasks_processed: int = 0
    tasks_failed: int = 0
    uptime_seconds: float = 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate task success rate."""
        total_tasks = self.tasks_processed + self.tasks_failed
        if total_tasks == 0:
            return 1.0
        return self.tasks_processed / total_tasks
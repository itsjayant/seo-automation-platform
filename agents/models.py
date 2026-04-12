"""Agent data models and result structures.

Provides standardized data models for agent execution context,
results, and metadata to ensure consistency across the agent ecosystem.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class AgentState(str, Enum):
    """Agent lifecycle states for state management."""
    INITIALIZING = "initializing"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CLEANUP = "cleanup"


class AgentExecutionContext(BaseModel):
    """Context information for agent execution.
    
    Contains metadata and configuration needed during agent execution,
    including correlation IDs, site context, and execution parameters.
    """
    
    # Execution identifiers
    execution_id: UUID = Field(default_factory=uuid4, description="Unique execution identifier")
    task_id: Optional[str] = Field(None, description="Task queue task identifier")
    correlation_id: Optional[str] = Field(None, description="Cross-service correlation ID")
    
    # Business context
    site_id: Optional[UUID] = Field(None, description="Site being processed")
    user_id: Optional[str] = Field(None, description="User who initiated the task")
    
    # Execution metadata
    started_at: datetime = Field(default_factory=datetime.utcnow, description="Execution start time")
    timeout_seconds: Optional[float] = Field(None, description="Maximum execution time")
    retry_count: int = Field(0, description="Number of retry attempts")
    max_retries: int = Field(3, description="Maximum retry attempts")
    
    # Agent configuration
    agent_config: Dict[str, Any] = Field(default_factory=dict, description="Agent-specific configuration")
    task_data: Dict[str, Any] = Field(default_factory=dict, description="Task input data")
    
    # Tracing context
    trace_id: Optional[str] = Field(None, description="OpenTelemetry trace ID")
    span_id: Optional[str] = Field(None, description="OpenTelemetry span ID")


class AgentMetrics(BaseModel):
    """Performance and execution metrics for agent operations."""
    
    execution_time_ms: Optional[int] = Field(None, description="Total execution time")
    initialization_time_ms: Optional[int] = Field(None, description="Initialization time")
    cleanup_time_ms: Optional[int] = Field(None, description="Cleanup time")
    
    # Resource utilization
    memory_peak_mb: Optional[float] = Field(None, description="Peak memory usage")
    cpu_time_ms: Optional[int] = Field(None, description="CPU time consumed")
    
    # External API calls
    api_calls_made: int = Field(0, description="Number of external API calls")
    api_calls_failed: int = Field(0, description="Number of failed API calls")
    
    # Database operations
    db_queries_executed: int = Field(0, description="Number of database queries")
    db_rows_affected: int = Field(0, description="Number of database rows affected")
    
    # Custom metrics
    custom_metrics: Dict[str, float] = Field(default_factory=dict, description="Agent-specific metrics")


class AgentResult(BaseModel):
    """Standard result format for agent execution.
    
    Provides a consistent structure for agent outputs, including
    success status, data, errors, and performance metrics.
    """
    
    # Execution status
    success: bool = Field(description="Whether the execution succeeded")
    state: AgentState = Field(description="Final agent state")
    
    # Result data
    data: Dict[str, Any] = Field(default_factory=dict, description="Agent output data")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata")
    
    # Error information
    error_message: Optional[str] = Field(None, description="Error message if failed")
    error_type: Optional[str] = Field(None, description="Error type classification")
    error_details: Optional[Dict[str, Any]] = Field(None, description="Detailed error information")
    
    # Execution context
    execution_id: UUID = Field(description="Execution identifier")
    started_at: datetime = Field(description="Execution start time")
    completed_at: datetime = Field(default_factory=datetime.utcnow, description="Execution completion time")
    
    # Performance metrics
    metrics: AgentMetrics = Field(default_factory=AgentMetrics, description="Execution metrics")
    
    # Approval workflow
    requires_approval: bool = Field(False, description="Whether result requires human approval")
    approval_context: Optional[Dict[str, Any]] = Field(None, description="Context for approval workflow")
    
    # Audit trail
    actions_taken: List[str] = Field(default_factory=list, description="List of actions performed")
    entities_modified: List[Dict[str, Any]] = Field(default_factory=list, description="Entities that were modified")
    
    @property
    def execution_duration_ms(self) -> int:
        """Calculate execution duration in milliseconds."""
        delta = self.completed_at - self.started_at
        return int(delta.total_seconds() * 1000)
    
    def add_action(self, action: str) -> None:
        """Add an action to the actions taken list."""
        self.actions_taken.append(action)
    
    def add_modified_entity(self, entity_type: str, entity_id: str, changes: Dict[str, Any]) -> None:
        """Add a modified entity to tracking."""
        self.entities_modified.append({
            "type": entity_type,
            "id": entity_id,
            "changes": changes,
            "timestamp": datetime.utcnow().isoformat()
        })
"""
BaseAgent Abstract Interface with OpenTelemetry Hooks

This module provides the foundational BaseAgent class that all SEO automation
agents inherit from. It ensures consistent behavior, observability, and 
integration patterns across the entire agent ecosystem.

Key Features:
- Abstract lifecycle methods: initialize(), execute(), cleanup()
- OpenTelemetry tracing spans for all operations
- Structured logging using structlog
- Error handling with proper exception propagation  
- Integration with audit log table for action tracking
- Agent lifecycle state management
- Database connection management
- Configuration injection via Pydantic settings
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type
from uuid import UUID, uuid4
from datetime import datetime
from contextlib import asynccontextmanager

import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

from config import get_settings
from db import get_database_manager, AuditLog, ActionType, EntityType, ApprovalStatus
from .models import (
    AgentState, AgentExecutionContext, AgentResult, AgentMetrics
)
from .exceptions import (
    AgentException, AgentInitializationError, AgentExecutionError, 
    AgentConfigurationError, AgentResourceError
)
from .decorators import (
    with_telemetry, with_resource_monitoring, agent_lifecycle_method
)
from .utils import (
    get_agent_logger, ResourceMonitor, create_telemetry_span, set_span_error,
    timeout_context, validate_agent_config
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class BaseAgentConfig(BaseModel):
    """Base configuration schema for all agents."""
    
    # Execution settings
    timeout_seconds: Optional[float] = None
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    
    # Resource limits
    max_memory_mb: Optional[float] = None
    max_execution_time_ms: Optional[int] = None
    
    # Audit settings
    enable_audit_logging: bool = True
    require_approval_for_actions: bool = False
    
    # Telemetry settings
    enable_tracing: bool = True
    trace_sample_rate: float = 1.0


class BaseAgent(ABC):
    """
    Abstract base class for all SEO automation agents.
    
    Provides consistent lifecycle management, observability, error handling,
    and integration patterns. All concrete agents must inherit from this class
    and implement the abstract methods.
    
    Lifecycle:
        1. INITIALIZING -> initialize() -> READY
        2. READY -> execute() -> EXECUTING -> COMPLETED/FAILED  
        3. Any state -> cleanup() -> cleanup complete
    
    Features:
        - OpenTelemetry tracing for all operations
        - Structured logging with agent context
        - Audit log integration for action tracking
        - Database connection management
        - Resource monitoring and limits
        - Error handling and recovery
        - Configuration validation
    """
    
    def __init__(
        self, 
        config: Optional[BaseAgentConfig] = None,
        execution_context: Optional[AgentExecutionContext] = None
    ):
        """Initialize the base agent.
        
        Args:
            config: Agent configuration (uses defaults if None)
            execution_context: Execution context for this agent run
        """
        self.config = config or BaseAgentConfig()
        self.execution_context = execution_context or AgentExecutionContext()
        
        # State management
        self._state = AgentState.INITIALIZING
        self._initialization_error: Optional[Exception] = None
        
        # Resources
        self._db_manager = None
        self._resource_monitor = ResourceMonitor()
        
        # Telemetry
        self._logger = get_agent_logger(
            self.__class__.__name__,
            {
                "execution_id": str(self.execution_context.execution_id),
                "task_id": self.execution_context.task_id,
                "site_id": str(self.execution_context.site_id) if self.execution_context.site_id else None
            }
        )
        
        # Execution tracking
        self._started_at: Optional[datetime] = None
        self._completed_at: Optional[datetime] = None
        self._metrics = AgentMetrics()
        
        self._logger.info(
            "Agent created", 
            state=self._state.value,
            config=self.config.model_dump()
        )
    
    @property
    def state(self) -> AgentState:
        """Current agent state."""
        return self._state
    
    @property 
    def agent_type(self) -> str:
        """Agent type identifier."""
        return self.__class__.__name__
    
    @property
    def logger(self) -> structlog.BoundLogger:
        """Get the agent's structured logger."""
        return self._logger
    
    @property
    def metrics(self) -> AgentMetrics:
        """Get current execution metrics."""
        return self._metrics
    
    def _transition_state(self, new_state: AgentState) -> None:
        """Transition to a new agent state with logging.
        
        Args:
            new_state: Target state to transition to
        """
        old_state = self._state
        self._state = new_state
        
        self._logger.info(
            "Agent state transition",
            from_state=old_state.value,
            to_state=new_state.value
        )
        
        # Update execution context
        if new_state == AgentState.EXECUTING and self._started_at is None:
            self._started_at = datetime.utcnow()
        elif new_state in (AgentState.COMPLETED, AgentState.FAILED):
            self._completed_at = datetime.utcnow()
    
    @with_telemetry("agent.initialize")
    @agent_lifecycle_method("INITIALIZING -> READY") 
    async def _internal_initialize(self) -> None:
        """Internal wrapper for agent initialization with telemetry."""
        try:
            # Initialize database connection
            self._db_manager = get_database_manager()
            await self._db_manager.initialize_async_pool()
            
            # Validate configuration
            self._validate_config()
            
            # Start resource monitoring
            self._resource_monitor.start_monitoring()
            
            # Call agent-specific initialization
            await self.initialize()
            
            # Transition to ready state
            self._transition_state(AgentState.READY)
            
            self._logger.info("Agent initialization completed successfully")
            
        except Exception as e:
            self._initialization_error = e
            self._transition_state(AgentState.FAILED)
            
            self._logger.error(
                "Agent initialization failed",
                error_type=e.__class__.__name__,
                error_message=str(e)
            )
            
            if isinstance(e, AgentException):
                raise
            else:
                raise AgentInitializationError(
                    f"Failed to initialize agent: {str(e)}",
                    context={"agent_type": self.agent_type},
                    cause=e
                )
    
    @with_telemetry("agent.execute")
    @with_resource_monitoring()
    @agent_lifecycle_method("READY -> EXECUTING -> COMPLETED/FAILED")
    async def _internal_execute(self, task_data: Dict[str, Any]) -> AgentResult:
        """Internal wrapper for agent execution with telemetry and monitoring."""
        if self._state != AgentState.READY:
            raise AgentExecutionError(
                f"Agent not ready for execution (current state: {self._state})",
                context={"current_state": self._state.value}
            )
        
        # Transition to executing state
        self._transition_state(AgentState.EXECUTING)
        
        # Create audit log entry for execution start
        audit_entry = await self._create_audit_log_entry(
            action_type=self.audit_action_type,
            description=f"Starting {self.agent_type} execution",
            request_data=task_data
        )
        
        execution_span = create_telemetry_span(
            f"agent.{self.agent_type.lower()}.execute",
            {
                "agent.type": self.agent_type,
                "execution.id": str(self.execution_context.execution_id),
                "task.id": self.execution_context.task_id or "unknown"
            }
        )
        
        try:
            with execution_span:
                # Execute with timeout if configured
                if self.config.timeout_seconds is not None:
                    result = await asyncio.wait_for(
                        self.execute(task_data), 
                        timeout=self.config.timeout_seconds
                    )
                else:
                    result = await self.execute(task_data)
                
                # Update metrics from resource monitor
                resource_metrics = self._resource_monitor.get_metrics()
                self._metrics.memory_peak_mb = resource_metrics.get("memory_peak_mb")
                self._metrics.cpu_time_ms = resource_metrics.get("cpu_time_ms")
                
                # Set completion time and calculate duration
                self._completed_at = datetime.utcnow()
                if self._started_at:
                    delta = self._completed_at - self._started_at
                    self._metrics.execution_time_ms = int(delta.total_seconds() * 1000)
                    
                # Set result metrics
                result.metrics = self._metrics
                
                # Mark execution as successful
                execution_span.set_attribute("agent.success", True)
                execution_span.set_status(Status(StatusCode.OK))
                
                # Update audit log entry
                await self._update_audit_log_entry(
                    audit_entry.id,
                    success=True,
                    response_data=result.model_dump(),
                    execution_time_ms=self._metrics.execution_time_ms
                )
                
                self._transition_state(AgentState.COMPLETED)
                
                self._logger.info(
                    "Agent execution completed successfully",
                    execution_time_ms=self._metrics.execution_time_ms,
                    actions_taken=len(result.actions_taken),
                    entities_modified=len(result.entities_modified)
                )
                
                return result
        
        except asyncio.TimeoutError:
            # Handle timeout error specifically
            timeout_error = AgentTimeoutError(
                f"Agent execution exceeded timeout of {self.config.timeout_seconds} seconds",
                timeout_seconds=self.config.timeout_seconds or 0.0
            )
            
            # Set span error
            set_span_error(execution_span, timeout_error)
            
            # Update audit log entry
            await self._update_audit_log_entry(
                audit_entry.id,
                success=False,
                error_message=str(timeout_error)
            )
            
            self._transition_state(AgentState.FAILED)
            
            self._logger.error(
                "Agent execution timed out",
                error_type=timeout_error.__class__.__name__,
                error_message=str(timeout_error),
                timeout_seconds=self.config.timeout_seconds
            )
            
            raise timeout_error
                
        except Exception as e:
            # Set span error
            set_span_error(execution_span, e)
            
            # Update audit log entry
            await self._update_audit_log_entry(
                audit_entry.id,
                success=False,
                error_message=str(e)
            )
            
            self._transition_state(AgentState.FAILED)
            
            self._logger.error(
                "Agent execution failed",
                error_type=e.__class__.__name__,
                error_message=str(e),
                execution_time_ms=self._metrics.execution_time_ms
            )
            
            # Create error result
            error_result = AgentResult(
                success=False,
                state=self._state,
                error_message=str(e),
                error_type=e.__class__.__name__,
                execution_id=self.execution_context.execution_id,
                started_at=self._started_at or datetime.utcnow(),
                metrics=self._metrics
            )
            
            if isinstance(e, AgentException):
                error_result.error_details = e.to_dict()
                raise
            else:
                raise AgentExecutionError(
                    f"Agent execution failed: {str(e)}",
                    context={"agent_type": self.agent_type},
                    cause=e
                )
    
    @with_telemetry("agent.cleanup")
    @agent_lifecycle_method("cleanup")
    async def _internal_cleanup(self) -> None:
        """Internal wrapper for agent cleanup with telemetry."""
        try:
            # Call agent-specific cleanup
            await self.cleanup()
            
            # Close database connections
            if self._db_manager and hasattr(self._db_manager, '_async_pool') and self._db_manager._async_pool:
                try:
                    await self._db_manager._async_pool.close()
                except Exception as e:
                    self._logger.warning("Failed to close database pool", error=str(e))
            
            self._logger.info("Agent cleanup completed successfully")
            
        except Exception as e:
            self._logger.error(
                "Agent cleanup failed",
                error_type=e.__class__.__name__,
                error_message=str(e)
            )
            # Don't re-raise cleanup errors to avoid masking original errors
    
    async def _create_audit_log_entry(
        self,
        action_type: ActionType,
        description: str,
        entity_type: Optional[EntityType] = None,
        entity_id: Optional[UUID] = None,
        request_data: Optional[Dict[str, Any]] = None,
        requires_approval: bool = False
    ) -> AuditLog:
        """Create an audit log entry for agent actions.
        
        Args:
            action_type: Type of action being performed
            description: Human-readable description
            entity_type: Type of entity being affected
            entity_id: ID of entity being affected
            request_data: Original request data
            requires_approval: Whether action requires approval
            
        Returns:
            Created audit log entry
        """
        if not self.config.enable_audit_logging:
            # Return a dummy audit log if disabled
            return AuditLog(
                id=uuid4(),
                action_type=action_type,
                entity_type=entity_type or EntityType.SITE,
                description=description
            )
        
        async with self._db_manager.async_connection() as conn:
            audit_entry = AuditLog(
                action_type=action_type,
                entity_type=entity_type or EntityType.SITE,
                entity_id=entity_id or self.execution_context.site_id,
                description=description,
                request_data=request_data,
                requires_approval=requires_approval or self.config.require_approval_for_actions,
                approval_status=ApprovalStatus.PENDING if requires_approval else None,
                user_context={
                    "agent_type": self.agent_type,
                    "execution_id": str(self.execution_context.execution_id),
                    "task_id": self.execution_context.task_id
                }
            )
            
            # Insert into database
            query = """
                INSERT INTO audit_log (
                    id, action_type, entity_type, entity_id, description,
                    request_data, requires_approval, approval_status, user_context
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """
            
            await conn.execute(
                query,
                audit_entry.id,
                audit_entry.action_type.value,
                audit_entry.entity_type.value,
                audit_entry.entity_id,
                audit_entry.description,
                audit_entry.request_data,
                audit_entry.requires_approval,
                audit_entry.approval_status.value if audit_entry.approval_status else None,
                audit_entry.user_context
            )
            
            return audit_entry
    
    async def _update_audit_log_entry(
        self,
        audit_id: UUID,
        success: bool,
        response_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """Update an existing audit log entry with results.
        
        Args:
            audit_id: ID of audit log entry to update
            success: Whether the operation succeeded
            response_data: Response data from the operation
            error_message: Error message if operation failed
            execution_time_ms: Execution time in milliseconds
        """
        if not self.config.enable_audit_logging:
            return
        
        async with self._db_manager.async_connection() as conn:
            query = """
                UPDATE audit_log 
                SET success = $2, response_data = $3, error_message = $4, 
                    execution_time_ms = $5, updated_at = NOW()
                WHERE id = $1
            """
            
            await conn.execute(
                query,
                audit_id,
                success,
                response_data,
                error_message,
                execution_time_ms
            )
    
    def _validate_config(self) -> None:
        """Validate agent configuration."""
        # Validate timeout settings
        if (self.config.timeout_seconds is not None and 
            self.config.timeout_seconds <= 0):
            raise AgentConfigurationError(
                "timeout_seconds must be positive",
                context={"timeout_seconds": self.config.timeout_seconds}
            )
        
        # Validate retry settings
        if self.config.max_retries < 0:
            raise AgentConfigurationError(
                "max_retries must be non-negative", 
                context={"max_retries": self.config.max_retries}
            )
        
        if self.config.retry_delay_seconds < 0:
            raise AgentConfigurationError(
                "retry_delay_seconds must be non-negative",
                context={"retry_delay_seconds": self.config.retry_delay_seconds}
            )
    
    # Abstract methods and properties that concrete agents must implement
    
    @property
    @abstractmethod
    def audit_action_type(self) -> ActionType:
        """Return the appropriate ActionType for this agent's audit logging."""
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize agent resources and validate configuration.
        
        This method is called once before execute() and should:
        - Validate agent-specific configuration
        - Initialize external API clients
        - Set up any required resources
        - Prepare for task execution
        
        Raises:
            AgentInitializationError: If initialization fails
        """
        pass
    
    @abstractmethod
    async def execute(self, task_data: Dict[str, Any]) -> AgentResult:
        """Execute the main agent logic.
        
        This is where the agent performs its core functionality:
        - Process the input task data
        - Interact with external APIs 
        - Analyze and transform data
        - Generate results and recommendations
        - Track all actions for audit logging
        
        Args:
            task_data: Input data for the agent execution
            
        Returns:
            AgentResult with execution results and metadata
            
        Raises:
            AgentExecutionError: If execution fails
        """
        pass
    
    @abstractmethod  
    async def cleanup(self) -> None:
        """Cleanup agent resources and persist final state.
        
        This method is called after execute() (whether successful or failed):
        - Close external API connections
        - Clean up temporary files or resources
        - Persist any final state
        - Perform graceful shutdown
        
        Should not raise exceptions - log errors instead.
        """
        pass
    
    # Public interface methods
    
    async def run(self, task_data: Dict[str, Any]) -> AgentResult:
        """Run the complete agent lifecycle.
        
        Orchestrates initialization, execution, and cleanup phases
        with proper error handling and resource management.
        
        Args:
            task_data: Input data for agent execution
            
        Returns:
            AgentResult with execution results
        """
        try:
            # Initialize if not already done
            if self._state == AgentState.INITIALIZING:
                await self._internal_initialize()
            
            # Execute main logic
            result = await self._internal_execute(task_data)
            
            return result
            
        finally:
            # Always attempt cleanup
            await self._internal_cleanup()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform agent health check.
        
        Returns:
            Health check results with status and diagnostics
        """
        health_status = {
            "agent_type": self.agent_type,
            "state": self._state.value,
            "healthy": True,
            "checks": {}
        }
        
        # Check database connection
        try:
            if self._db_manager:
                async with self._db_manager.async_connection() as conn:
                    await conn.fetchval("SELECT 1")
                health_status["checks"]["database"] = "ok"
            else:
                health_status["checks"]["database"] = "not_initialized"
        except Exception as e:
            health_status["checks"]["database"] = f"error: {str(e)}"
            health_status["healthy"] = False
        
        # Check initialization status
        if self._initialization_error:
            health_status["checks"]["initialization"] = f"error: {str(self._initialization_error)}"
            health_status["healthy"] = False
        else:
            health_status["checks"]["initialization"] = "ok"
        
        return health_status
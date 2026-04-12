"""
Tests for BaseAgent Interface and Implementations

This module provides comprehensive tests for the BaseAgent abstract class
and its key functionality including lifecycle management, telemetry,
error handling, and audit logging.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch

from agents.base import BaseAgent, BaseAgentConfig
from agents.models import AgentState, AgentExecutionContext, AgentResult, AgentMetrics
from agents.exceptions import (
    AgentException, AgentInitializationError, AgentExecutionError,
    AgentConfigurationError, AgentTimeoutError
)
from db.models import ActionType, EntityType


class MockAgent(BaseAgent):
    """Mock agent implementation for testing."""
    
    def __init__(self, 
                 config=None, 
                 execution_context=None,
                 should_fail_init=False,
                 should_fail_execute=False,
                 execution_delay=0.0):
        self.should_fail_init = should_fail_init
        self.should_fail_execute = should_fail_execute
        self.execution_delay = execution_delay
        self.init_called = False
        self.execute_called = False
        self.cleanup_called = False
        super().__init__(config, execution_context)
    
    async def initialize(self) -> None:
        """Mock initialization."""
        self.init_called = True
        if self.should_fail_init:
            raise AgentInitializationError("Mock initialization failure")
    
    async def execute(self, task_data: Dict[str, Any]) -> AgentResult:
        """Mock execution."""
        self.execute_called = True
        
        if self.execution_delay > 0:
            await asyncio.sleep(self.execution_delay)
        
        if self.should_fail_execute:
            raise AgentExecutionError("Mock execution failure")
        
        result = AgentResult(
            success=True,
            state=AgentState.COMPLETED,
            execution_id=self.execution_context.execution_id,
            started_at=datetime.utcnow(),
            data={"result": "success", "processed": task_data}
        )
        
        result.add_action("processed_task_data")
        result.add_modified_entity("test_entity", "123", {"status": "updated"})
        
        return result
    
    async def cleanup(self) -> None:
        """Mock cleanup."""
        self.cleanup_called = True


class MockDatabaseManager:
    """Mock database manager for testing."""
    
    def __init__(self):
        self._async_pool = Mock()
        self.audit_log_entries = []
    
    async def initialize_async_pool(self):
        pass
    
    def async_connection(self):
        return MockAsyncConnection(self)


class MockAsyncConnection:
    """Mock async database connection."""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    async def execute(self, query, *args):
        # Mock audit log insertion
        if "INSERT INTO audit_log" in query:
            self.db_manager.audit_log_entries.append(args)
        # Mock audit log update
        elif "UPDATE audit_log" in query:
            pass  # No-op for testing
    
    async def fetchval(self, query):
        if query == "SELECT 1":
            return 1
        return None


@pytest.fixture
def mock_db_manager():
    """Fixture providing mock database manager."""
    return MockDatabaseManager()


@pytest.fixture  
def mock_agent_config():
    """Fixture providing test agent configuration."""
    return BaseAgentConfig(
        timeout_seconds=30.0,
        max_retries=2,
        enable_audit_logging=True
    )


@pytest.fixture
def mock_execution_context():
    """Fixture providing test execution context."""
    return AgentExecutionContext(
        execution_id=uuid4(),
        task_id="test-task-123",
        site_id=uuid4(),
        user_id="test-user"
    )


@pytest.mark.asyncio
class TestBaseAgent:
    """Test suite for BaseAgent functionality."""
    
    async def test_agent_creation(self, mock_agent_config, mock_execution_context):
        """Test agent creation and initial state."""
        agent = MockAgent(mock_agent_config, mock_execution_context)
        
        assert agent.state == AgentState.INITIALIZING
        assert agent.agent_type == "MockAgent"
        assert agent.config == mock_agent_config
        assert agent.execution_context == mock_execution_context
        assert not agent.init_called
        assert not agent.execute_called
        assert not agent.cleanup_called
    
    @patch('agents.base.get_database_manager')
    async def test_successful_initialization(self, mock_get_db, mock_db_manager):
        """Test successful agent initialization."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent()
        await agent._internal_initialize()
        
        assert agent.state == AgentState.READY
        assert agent.init_called
        assert agent._initialization_error is None
    
    @patch('agents.base.get_database_manager')
    async def test_initialization_failure(self, mock_get_db, mock_db_manager):
        """Test agent initialization failure."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent(should_fail_init=True)
        
        with pytest.raises(AgentInitializationError):
            await agent._internal_initialize()
        
        assert agent.state == AgentState.FAILED
        assert agent.init_called
        assert agent._initialization_error is not None
    
    @patch('agents.base.get_database_manager')
    async def test_successful_execution(self, mock_get_db, mock_db_manager):
        """Test successful agent execution."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent()
        await agent._internal_initialize()
        
        task_data = {"input": "test data"}
        result = await agent._internal_execute(task_data)
        
        assert agent.state == AgentState.COMPLETED
        assert agent.execute_called
        assert result.success
        assert result.data["processed"] == task_data
        assert "processed_task_data" in result.actions_taken
        assert len(result.entities_modified) == 1
    
    @patch('agents.base.get_database_manager')
    async def test_execution_failure(self, mock_get_db, mock_db_manager):
        """Test agent execution failure."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent(should_fail_execute=True)
        await agent._internal_initialize()
        
        task_data = {"input": "test data"}
        
        with pytest.raises(AgentExecutionError):
            await agent._internal_execute(task_data)
        
        assert agent.state == AgentState.FAILED
        assert agent.execute_called
    
    async def test_execution_without_initialization(self):
        """Test execution fails if agent not initialized."""
        agent = MockAgent()
        
        task_data = {"input": "test data"}
        
        with pytest.raises(AgentExecutionError) as exc_info:
            await agent._internal_execute(task_data)
        
        assert "not ready for execution" in str(exc_info.value)
        assert agent.state == AgentState.INITIALIZING
    
    @patch('agents.base.get_database_manager')
    async def test_cleanup_called(self, mock_get_db, mock_db_manager):
        """Test cleanup is called after execution."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent()
        task_data = {"input": "test data"}
        
        result = await agent.run(task_data)
        
        assert agent.cleanup_called
        assert result.success
    
    @patch('agents.base.get_database_manager')
    async def test_cleanup_called_on_failure(self, mock_get_db, mock_db_manager):
        """Test cleanup is called even when execution fails."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent(should_fail_execute=True)
        task_data = {"input": "test data"}
        
        with pytest.raises(AgentExecutionError):
            await agent.run(task_data)
        
        assert agent.cleanup_called
    
    async def test_timeout_configuration_validation(self):
        """Test timeout configuration validation."""
        with pytest.raises(AgentConfigurationError):
            config = BaseAgentConfig(timeout_seconds=-1.0)
            agent = MockAgent(config)
            agent._validate_config()
    
    async def test_retry_configuration_validation(self):
        """Test retry configuration validation.""" 
        with pytest.raises(AgentConfigurationError):
            config = BaseAgentConfig(max_retries=-1)
            agent = MockAgent(config)
            agent._validate_config()
        
        with pytest.raises(AgentConfigurationError):
            config = BaseAgentConfig(retry_delay_seconds=-1.0)
            agent = MockAgent(config)
            agent._validate_config()
    
    @patch('agents.base.get_database_manager')
    async def test_timeout_handling(self, mock_get_db, mock_db_manager):
        """Test agent execution timeout handling."""
        mock_get_db.return_value = mock_db_manager
        
        # Configure short timeout and slow execution
        config = BaseAgentConfig(timeout_seconds=0.1)
        agent = MockAgent(config, execution_delay=0.2)
        
        await agent._internal_initialize()
        task_data = {"input": "test data"}
        
        with pytest.raises(AgentTimeoutError):
            await agent._internal_execute(task_data)
    
    @patch('agents.base.get_database_manager')
    async def test_audit_logging(self, mock_get_db, mock_db_manager):
        """Test audit logging integration."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent()
        await agent._internal_initialize()
        
        task_data = {"input": "test data"}
        await agent._internal_execute(task_data)
        
        # Should have created one audit log entry
        assert len(mock_db_manager.audit_log_entries) >= 1
    
    @patch('agents.base.get_database_manager')
    async def test_audit_logging_disabled(self, mock_get_db, mock_db_manager):
        """Test audit logging can be disabled."""
        mock_get_db.return_value = mock_db_manager
        
        config = BaseAgentConfig(enable_audit_logging=False)
        agent = MockAgent(config)
        await agent._internal_initialize()
        
        task_data = {"input": "test data"}
        await agent._internal_execute(task_data)
        
        # Should not have created any audit log entries
        assert len(mock_db_manager.audit_log_entries) == 0
    
    @patch('agents.base.get_database_manager')
    async def test_health_check_healthy(self, mock_get_db, mock_db_manager):
        """Test health check when agent is healthy."""
        mock_get_db.return_value = mock_db_manager
        
        agent = MockAgent()
        await agent._internal_initialize()
        
        health = await agent.health_check()
        
        assert health["healthy"] is True
        assert health["agent_type"] == "MockAgent"
        assert health["state"] == AgentState.READY.value
        assert health["checks"]["database"] == "ok"
        assert health["checks"]["initialization"] == "ok"
    
    async def test_health_check_unhealthy(self):
        """Test health check when agent is unhealthy."""
        agent = MockAgent(should_fail_init=True)
        
        # Try to initialize (will fail)
        try:
            with patch('agents.base.get_database_manager') as mock_get_db:
                mock_get_db.return_value = MockDatabaseManager()
                await agent._internal_initialize()
        except AgentInitializationError:
            pass
        
        health = await agent.health_check()
        
        assert health["healthy"] is False
        assert "error" in health["checks"]["initialization"]
    
    async def test_state_transitions(self):
        """Test agent state transitions during lifecycle."""
        agent = MockAgent()
        
        # Initial state
        assert agent.state == AgentState.INITIALIZING
        
        with patch('agents.base.get_database_manager') as mock_get_db:
            mock_get_db.return_value = MockDatabaseManager()
            
            # After initialization
            await agent._internal_initialize()
            assert agent.state == AgentState.READY
            
            # During execution
            task_data = {"input": "test"}
            result = await agent._internal_execute(task_data)
            
            # After successful execution
            assert agent.state == AgentState.COMPLETED
            assert result.state == AgentState.COMPLETED
    
    async def test_metrics_collection(self):
        """Test that execution metrics are collected."""
        with patch('agents.base.get_database_manager') as mock_get_db:
            mock_get_db.return_value = MockDatabaseManager()
            
            agent = MockAgent()
            task_data = {"input": "test"}
            
            result = await agent.run(task_data)
            
            assert isinstance(result.metrics, AgentMetrics)
            assert result.metrics.execution_time_ms is not None
            assert result.execution_duration_ms > 0


@pytest.mark.asyncio
class TestAgentModels:
    """Test agent data models and utilities."""
    
    def test_agent_result_creation(self):
        """Test AgentResult model creation and properties."""
        execution_id = uuid4()
        started_at = datetime.utcnow()
        
        result = AgentResult(
            success=True,
            state=AgentState.COMPLETED,
            execution_id=execution_id,
            started_at=started_at,
            data={"key": "value"}
        )
        
        assert result.success
        assert result.state == AgentState.COMPLETED
        assert result.execution_id == execution_id
        assert result.data == {"key": "value"}
        assert result.execution_duration_ms >= 0
    
    def test_agent_result_actions_tracking(self):
        """Test tracking of actions and modified entities."""
        result = AgentResult(
            success=True,
            state=AgentState.COMPLETED,
            execution_id=uuid4(),
            started_at=datetime.utcnow()
        )
        
        result.add_action("action1")
        result.add_action("action2")
        result.add_modified_entity("entity_type", "entity_id", {"field": "new_value"})
        
        assert len(result.actions_taken) == 2
        assert "action1" in result.actions_taken
        assert "action2" in result.actions_taken
        assert len(result.entities_modified) == 1
        assert result.entities_modified[0]["type"] == "entity_type"
        assert result.entities_modified[0]["id"] == "entity_id"
    
    def test_execution_context_defaults(self):
        """Test AgentExecutionContext default values."""
        context = AgentExecutionContext()
        
        assert context.execution_id is not None
        assert context.retry_count == 0
        assert context.max_retries == 3
        assert isinstance(context.agent_config, dict)
        assert isinstance(context.task_data, dict)
    
    def test_base_agent_config_defaults(self):
        """Test BaseAgentConfig default values."""
        config = BaseAgentConfig()
        
        assert config.timeout_seconds is None
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 1.0
        assert config.enable_audit_logging is True
        assert config.require_approval_for_actions is False
        assert config.enable_tracing is True
#!/usr/bin/env python
"""
Simple integration test for the Agent Registration and Discovery System
to verify everything works together.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from agents import (
    BaseAgent, register_agent, get_agent_registry,
    AgentCapability, validate_agent
)


# Test agent implementation
@register_agent(
    name="simple_test_agent",
    version="1.0.0",
    description="Simple test agent for integration validation",
    capabilities=[AgentCapability.KEYWORD_DISCOVERY],
    dependencies=[{"dependency_type": "api", "name": "test_api", "required": True}],
    category="test"
)
class SimpleTestAgent(BaseAgent):
    """Simple test agent for integration validation."""
    
    async def initialize(self):
        """Initialize the test agent."""
        pass
    
    async def execute(self, task_data):
        """Execute test agent logic."""
        from .models import AgentResult
        return AgentResult(
            success=True,
            state=self.state,
            data={"result": "test_completed"},
            execution_id=self.execution_context.execution_id,
            started_at=self.execution_context.started_at
        )
    
    async def cleanup(self):
        """Clean up test agent resources."""
        pass


async def test_integration():
    """Test full integration of agent registry system."""
    print("🚀 Starting Integration Test...\n")
    
    # Get registry
    registry = get_agent_registry()
    
    # Test 1: Registry Stats
    print("📊 1. Registry Stats:")
    stats = registry.get_registry_stats()
    print(f"   Total agents: {stats['total_agents']}")
    print(f"   Available agents: {stats['available_agents']}")
    print(f"   Agent types: {stats['agent_types']}")
    
    # Test 2: Agent Metadata
    print("\n📋 2. Agent Metadata:")
    metadata = registry.get_agent_metadata("simple_test_agent")
    if metadata:
        print(f"   Name: {metadata.name}")
        print(f"   Version: {metadata.version}")
        print(f"   Capabilities: {[cap.value if hasattr(cap, 'value') else str(cap) for cap in metadata.capabilities]}")
        print(f"   Dependencies: {[dep.name for dep in metadata.dependencies]}")
    
    # Test 3: Agent Discovery
    print("\n🔍 3. Agent Discovery:")
    keyword_agents = registry.get_agents_by_capability(AgentCapability.KEYWORD_DISCOVERY)
    print(f"   Keyword discovery agents: {list(keyword_agents.keys())}")
    
    available_agents = registry.get_available_agents()
    print(f"   Available agents: {list(available_agents.keys())}")
    
    # Test 4: Agent Validation
    print("\n✅ 4. Agent Validation:")
    validation_result = await validate_agent(SimpleTestAgent, check_dependencies=False)
    print(f"   Is valid: {validation_result.is_valid}")
    if validation_result.errors:
        print(f"   Errors: {validation_result.errors}")
    if validation_result.warnings:
        print(f"   Warnings: {validation_result.warnings}")
    
    # Test 5: Agent Instantiation & Execution
    print("\n🏃 5. Agent Instantiation & Execution:")
    agent_class = registry.get_agent_class("simple_test_agent")
    if agent_class:
        try:
            # Instantiate agent
            agent = agent_class()
            print(f"   ✅ Agent instantiated: {agent.agent_type}")
            
            # Initialize agent
            await agent._internal_initialize()
            print(f"   ✅ Agent initialized. State: {agent.state.value}")
            
            # Execute agent
            result = await agent._internal_execute({"test": "data"})
            print(f"   ✅ Agent executed successfully: {result.success}")
            print(f"   ✅ Result data: {result.data}")
            
            # Cleanup
            await agent._internal_cleanup()
            print(f"   ✅ Agent cleanup completed")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        print("   ❌ Could not get agent class")
        return False
    
    # Test 6: Health Check
    print("\n🏥 6. Health Check:")
    try:
        health_status = await registry.check_agent_health("simple_test_agent")
        print(f"   Agent healthy: {health_status.is_healthy}")
        if health_status.error_message:
            print(f"   Error: {health_status.error_message}")
        print(f"   Last check: {health_status.last_check}")
    except Exception as e:
        print(f"   ❌ Health check error: {e}")
    
    print("\n🎉 Integration test completed successfully!")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_integration())
    sys.exit(0 if success else 1)
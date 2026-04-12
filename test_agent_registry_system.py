#!/usr/bin/env python
"""
Test script for the Agent Registration and Discovery System.

Tests the basic functionality of agent registration, discovery,
metadata validation, and registry management.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from agents import (
    BaseAgent, register_agent, get_agent_registry,
    AgentCapability, AgentDependency, validate_agent,
    get_agent_discovery_system, discover_agents
)


# Test agent implementations

@register_agent(
    name="test_keyword_agent",
    version="1.0.0",
    description="Test keyword research agent",
    capabilities=[AgentCapability.KEYWORD_DISCOVERY, AgentCapability.SERP_ANALYSIS],
    dependencies=[
        {"dependency_type": "api", "name": "gsc_api", "required": True},
        {"dependency_type": "api", "name": "serpapi", "required": True}
    ],
    category="research"
)
class TestKeywordAgent(BaseAgent):
    """Test keyword research agent for validation."""
    
    async def initialize(self):
        """Initialize the test agent."""
        pass
    
    async def execute(self, task_data):
        """Execute test agent logic."""
        from .models import AgentResult
        return AgentResult(
            success=True,
            state=self.state,
            data={"test": "keyword_research_completed"},
            execution_id=self.execution_context.execution_id,
            started_at=self.execution_context.started_at
        )
    
    async def cleanup(self):
        """Clean up test agent resources."""
        pass


@register_agent(
    name="test_content_agent", 
    version="1.0.0",
    description="Test content analysis agent",
    capabilities=[AgentCapability.CONTENT_AUDIT, AgentCapability.SEMANTIC_ANALYSIS],
    dependencies=[
        {"dependency_type": "database", "name": "postgres", "required": True}
    ],
    category="analysis"
)
class TestContentAgent(BaseAgent):
    """Test content analysis agent for validation."""
    
    async def initialize(self):
        """Initialize the test agent.""" 
        pass
    
    async def execute(self, task_data):
        """Execute test agent logic."""
        from .models import AgentResult
        return AgentResult(
            success=True,
            state=self.state, 
            data={"test": "content_analysis_completed"},
            execution_id=self.execution_context.execution_id,
            started_at=self.execution_context.started_at
        )
    
    async def cleanup(self):
        """Clean up test agent resources."""
        pass


async def test_agent_registration():
    """Test agent registration functionality."""
    print("🧪 Testing Agent Registration...")
    
    registry = get_agent_registry()
    
    # Check registered agents
    stats = registry.get_registry_stats()
    print(f"✅ Registry stats: {stats}")
    
    # Test getting agents by capability
    keyword_agents = registry.get_agents_by_capability(AgentCapability.KEYWORD_DISCOVERY)
    print(f"✅ Keyword discovery agents: {list(keyword_agents.keys())}")
    
    content_agents = registry.get_agents_by_capability(AgentCapability.CONTENT_AUDIT)
    print(f"✅ Content audit agents: {list(content_agents.keys())}")
    
    # Test getting agent metadata
    test_agent_meta = registry.get_agent_metadata("test_keyword_agent")
    if test_agent_meta:
        print(f"✅ Agent metadata: {test_agent_meta.name} v{test_agent_meta.version}")
        capabilities_str = []
        for cap in test_agent_meta.capabilities:
            if hasattr(cap, 'value'):
                capabilities_str.append(cap.value)
            else:
                capabilities_str.append(str(cap))
        print(f"   Capabilities: {capabilities_str}")
        print(f"   Dependencies: {[dep.name for dep in test_agent_meta.dependencies]}")
    
    return True


async def test_agent_validation():
    """Test agent validation functionality."""
    print("\n🧪 Testing Agent Validation...")
    
    # Validate test agents
    validation_result = await validate_agent(
        TestKeywordAgent,
        check_dependencies=False  # Skip dependency checks for testing
    )
    
    print(f"✅ TestKeywordAgent validation: {validation_result.is_valid}")
    if validation_result.errors:
        print(f"   Errors: {validation_result.errors}")
    if validation_result.warnings:
        print(f"   Warnings: {validation_result.warnings}")
    
    # Test content agent validation
    content_validation = await validate_agent(
        TestContentAgent,
        check_dependencies=False
    )
    
    print(f"✅ TestContentAgent validation: {content_validation.is_valid}")
    if content_validation.errors:
        print(f"   Errors: {content_validation.errors}")
    if content_validation.warnings:
        print(f"   Warnings: {content_validation.warnings}")
    
    return validation_result.is_valid and content_validation.is_valid


async def test_agent_health():
    """Test agent health checking."""
    print("\n🧪 Testing Agent Health...")
    
    registry = get_agent_registry()
    
    # Check health of registered agents
    health_results = await registry.check_all_agent_health()
    
    for agent_name, health in health_results.items():
        status = "✅" if health.is_healthy else "❌"
        print(f"{status} {agent_name}: {health.is_healthy}")
        if health.error_message:
            print(f"   Error: {health.error_message}")
    
    return all(h.is_healthy for h in health_results.values())


async def test_agent_discovery():
    """Test agent discovery functionality."""
    print("\n🧪 Testing Agent Discovery...")
    
    # Test discovery system
    discovery_system = get_agent_discovery_system()
    
    # Get discovery stats
    stats = discovery_system.get_discovery_stats()
    print(f"✅ Discovery stats: {stats}")
    
    # Test agent discovery (from current module)
    discovered = await discover_agents(force_rescan=True)
    print(f"✅ Discovered agents: {discovered}")
    
    return True


async def test_registry_filtering():
    """Test registry filtering and discovery capabilities."""
    print("\n🧪 Testing Registry Filtering...")
    
    registry = get_agent_registry()
    
    # First check what agents are available
    all_agents = registry.get_available_agents()
    print(f"✅ All available agents: {list(all_agents.keys())}")
    
    # Test discovery filters
    from agents.metadata import AgentDiscoveryFilter
    
    # Find all research category agents
    research_filter = AgentDiscoveryFilter(category="research", available_only=True)
    research_agents = registry.discover_agents(research_filter)
    print(f"✅ Research agents: {list(research_agents.keys())}")
    
    # Find agents with keyword capabilities
    keyword_filter = AgentDiscoveryFilter(
        capabilities=[AgentCapability.KEYWORD_DISCOVERY],
        available_only=True
    )
    keyword_agents = registry.discover_agents(keyword_filter)
    print(f"✅ Keyword capability agents: {list(keyword_agents.keys())}")
    
    # Find agents with API dependencies
    api_filter = AgentDiscoveryFilter(has_dependencies=["gsc_api"], available_only=True)
    api_agents = registry.discover_agents(api_filter)
    print(f"✅ GSC API dependent agents: {list(api_agents.keys())}")
    
    # Test basic capability filtering
    keyword_agents_basic = registry.get_agents_by_capability(AgentCapability.KEYWORD_DISCOVERY)
    print(f"✅ Basic keyword agents: {list(keyword_agents_basic.keys())}")
    
    return True


async def test_agent_instantiation():
    """Test agent instantiation and basic operation."""
    print("\n🧪 Testing Agent Instantiation...")
    
    registry = get_agent_registry()
    
    # Debug what's in the registry
    print(f"🔍 Agents in registry: {list(registry._agents.keys())}")
    print(f"🔍 Agent classes in registry: {list(registry._agent_classes.keys())}")
    
    # Get agent class and instantiate
    agent_class = registry.get_agent_class("test_keyword_agent")
    print(f"🔍 Retrieved agent class: {agent_class}")
    
    if agent_class:
        try:
            agent = agent_class()
            print(f"✅ Instantiated agent: {agent.agent_type}")
            print(f"   State: {agent.state.value}")
            
            # Initialize agent
            await agent._internal_initialize()
            print(f"   State after init: {agent.state.value}")
            
            return agent.state.value == "ready"
        except Exception as e:
            print(f"❌ Error instantiating agent: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        print(f"❌ Could not get agent class for test_keyword_agent")
        return False


async def main():
    """Run all tests."""
    print("🚀 Starting Agent Registration and Discovery System Tests\n")
    
    tests = [
        ("Agent Registration", test_agent_registration),
        ("Agent Validation", test_agent_validation),
        ("Agent Health", test_agent_health),
        ("Agent Discovery", test_agent_discovery),
        ("Registry Filtering", test_registry_filtering),
        ("Agent Instantiation", test_agent_instantiation)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            if result:
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"💥 {test_name}: ERROR - {str(e)}")
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Agent Registry system is working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Please check the implementation.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
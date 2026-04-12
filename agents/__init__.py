"""
SEO Agent Framework

This package provides the agent registration and discovery system for the 
SEO automation platform's agent ecosystem.

All SEO agents inherit from BaseAgent and are registered through the
agent registry for dynamic discovery and orchestration.

Core Components:
    - BaseAgent: Abstract base class for all agents
    - AgentRegistry: Centralized agent registration and management
    - AgentDiscoverySystem: Dynamic agent discovery and hot-reloading
    - AgentValidator: Comprehensive agent validation
    - Agent registration decorators and utilities

Usage:
    # Register an agent
    @register_agent(
        name="keyword_research_agent",
        version="1.0.0", 
        capabilities=["keyword_discovery", "serp_analysis"],
        dependencies=["gsc_api", "serpapi"]
    )
    class KeywordResearchAgent(BaseAgent):
        async def execute(self, task_data):
            pass
    
    # Discover agents
    registry = get_agent_registry()
    agents = registry.get_agents_by_capability("keyword_discovery")
    
    # Validate agent
    result = await validate_agent(KeywordResearchAgent)
"""

# Core agent framework
from .base import BaseAgent, AgentState
from .models import AgentResult, AgentExecutionContext
from .exceptions import (
    AgentException,
    AgentInitializationError,
    AgentExecutionError,
    AgentTimeoutError,
    AgentConfigurationError,
    AgentResourceError,
    AgentValidationError,
    AgentRegistrationError,
    AgentNotFoundError,
    AgentDependencyError,
    AgentDiscoveryError,
    AgentLoadingError,
    AgentImplementationError
)

# Agent metadata and registry
from .metadata import (
    AgentMetadata,
    AgentCapability,
    AgentDependency,
    AgentInputSpec,
    AgentOutputSpec,
    AgentRegistrationResult,
    AgentDiscoveryFilter,
    AgentHealthStatus
)

# Agent registry system
from .registry import (
    AgentRegistry,
    get_agent_registry,
    register_agent
)

# Agent discovery system
from .discovery import (
    AgentDiscoverySystem,
    AgentDiscoveryConfig,
    get_agent_discovery_system,
    discover_agents,
    reload_changed_agents
)

# Agent validation
from .validators import (
    AgentValidator,
    ValidationResult,
    get_agent_validator,
    validate_agent
)

__all__ = [
    # Core framework
    "BaseAgent",
    "AgentState",
    "AgentResult", 
    "AgentExecutionContext",
    
    # Exceptions
    "AgentException",
    "AgentInitializationError",
    "AgentExecutionError",
    "AgentTimeoutError",
    "AgentConfigurationError",
    "AgentResourceError",
    "AgentValidationError",
    "AgentRegistrationError", 
    "AgentNotFoundError",
    "AgentDependencyError",
    "AgentDiscoveryError",
    "AgentLoadingError",
    "AgentImplementationError",
    
    # Metadata models
    "AgentMetadata",
    "AgentCapability",
    "AgentDependency",
    "AgentInputSpec",
    "AgentOutputSpec",
    "AgentRegistrationResult",
    "AgentDiscoveryFilter", 
    "AgentHealthStatus",
    
    # Registry system
    "AgentRegistry",
    "get_agent_registry",
    "register_agent",
    
    # Discovery system
    "AgentDiscoverySystem",
    "AgentDiscoveryConfig", 
    "get_agent_discovery_system",
    "discover_agents",
    "reload_changed_agents",
    
    # Validation system
    "AgentValidator",
    "ValidationResult",
    "get_agent_validator",
    "validate_agent"
]
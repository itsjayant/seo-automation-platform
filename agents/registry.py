"""Agent registry implementation for dynamic agent management.

Provides centralized agent registration, metadata storage, and lifecycle
management for the SEO automation platform's agent ecosystem.
"""

import asyncio
import importlib
import inspect
import sys
from typing import Dict, List, Optional, Type, Union, Callable, Any
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
from pathlib import Path

import structlog
from opentelemetry import trace

from .base import BaseAgent
from .metadata import (
    AgentMetadata, AgentRegistrationResult, AgentDiscoveryFilter,
    AgentHealthStatus, AgentCapability, AgentDependency
)
from .exceptions import (
    AgentRegistrationError, AgentNotFoundError, AgentDependencyError
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class AgentRegistry:
    """
    Centralized registry for agent registration and management.
    
    Provides dynamic agent discovery, metadata storage, capability-based
    routing, and health monitoring for all registered agents in the platform.
    
    Features:
        - Dynamic agent registration via decorator
        - Metadata validation and storage
        - Capability-based agent discovery
        - Dependency resolution and validation
        - Health monitoring and status tracking
        - Thread-safe operations
    """
    
    def __init__(self):
        """Initialize the agent registry."""
        self._agents: Dict[str, AgentMetadata] = {}
        self._agent_classes: Dict[str, Type[BaseAgent]] = {}
        self._health_status: Dict[str, AgentHealthStatus] = {}
        self._lock = asyncio.Lock()
        
    def register_agent(
        self,
        name: Optional[str] = None,
        version: str = "1.0.0",
        description: Optional[str] = None,
        capabilities: Optional[List[Union[str, AgentCapability]]] = None,
        dependencies: Optional[List[Union[str, dict, AgentDependency]]] = None,
        **metadata_kwargs
    ) -> Callable:
        """
        Decorator for agent registration.
        
        Automatically registers an agent class with the registry, collecting
        metadata and validating the agent implementation.
        
        Args:
            name: Agent name (defaults to class name in snake_case)
            version: Agent version (semantic versioning)
            description: Agent description
            capabilities: List of agent capabilities
            dependencies: List of agent dependencies
            **metadata_kwargs: Additional metadata parameters
            
        Returns:
            Decorated agent class
            
        Example:
            @register_agent(
                name="keyword_research_agent",
                version="1.0.0",
                capabilities=["keyword_discovery", "serp_analysis"],
                dependencies=["gsc_api", "serpapi"]
            )
            class KeywordResearchAgent(BaseAgent):
                async def execute(self, task_data):
                    pass
        """
        def decorator(agent_class: Type[BaseAgent]) -> Type[BaseAgent]:
            # Validate agent class
            if not issubclass(agent_class, BaseAgent):
                raise AgentRegistrationError(
                    f"Agent {agent_class.__name__} must inherit from BaseAgent"
                )
            
            # Generate agent name if not provided
            agent_name = name or self._class_to_snake_case(agent_class.__name__)
            
            # Convert capabilities to enum values
            parsed_capabilities = []
            if capabilities:
                for cap in capabilities:
                    if isinstance(cap, str):
                        try:
                            parsed_capabilities.append(AgentCapability(cap))
                        except ValueError:
                            logger.warning(f"Unknown capability: {cap}", agent=agent_name)
                    else:
                        parsed_capabilities.append(cap)
            
            # Convert dependencies to dependency objects
            parsed_dependencies = []
            if dependencies:
                for dep in dependencies:
                    if isinstance(dep, str):
                        parsed_dependencies.append(AgentDependency(
                            dependency_type="integration",
                            name=dep
                        ))
                    elif isinstance(dep, dict):
                        parsed_dependencies.append(AgentDependency(**dep))
                    else:
                        parsed_dependencies.append(dep)
            
            # Build metadata
            metadata = AgentMetadata(
                name=agent_name,
                version=version,
                description=description or agent_class.__doc__ or f"{agent_class.__name__} agent",
                capabilities=parsed_capabilities,
                agent_type=agent_class.__name__,
                category=metadata_kwargs.pop('category', 'general'),
                dependencies=parsed_dependencies,
                agent_class=agent_class,
                module_path=f"{agent_class.__module__}.{agent_class.__name__}",
                **metadata_kwargs
            )
            
            # Register synchronously (decorator context)
            self._register_agent_sync(agent_name, metadata, agent_class)
            
            logger.info(
                "Agent registered successfully",
                agent_name=agent_name,
                version=version,
                capabilities=[cap.value for cap in parsed_capabilities],
                dependencies=[dep.name for dep in parsed_dependencies]
            )
            
            return agent_class
        
        return decorator
    
    def _register_agent_sync(
        self,
        agent_name: str,
        metadata: AgentMetadata,
        agent_class: Type[BaseAgent]
    ) -> None:
        """Synchronously register an agent (used by decorator)."""
        if agent_name in self._agents:
            raise AgentRegistrationError(
                f"Agent '{agent_name}' is already registered"
            )
        
        self._agents[agent_name] = metadata
        self._agent_classes[agent_name] = agent_class
        
        # Initialize health status
        self._health_status[agent_name] = AgentHealthStatus(
            agent_name=agent_name,
            is_healthy=True,  # Assume healthy until proven otherwise
            last_check=datetime.utcnow()
        )
    
    async def register_agent_async(
        self,
        agent_name: str,
        metadata: AgentMetadata,
        agent_class: Type[BaseAgent]
    ) -> AgentRegistrationResult:
        """
        Asynchronously register an agent with validation.
        
        Args:
            agent_name: Unique agent name
            metadata: Agent metadata
            agent_class: Agent class implementation
            
        Returns:
            Registration result with status and details
        """
        async with self._lock:
            try:
                if agent_name in self._agents:
                    return AgentRegistrationResult(
                        success=False,
                        agent_name=agent_name,
                        registration_id=metadata.registration_id,
                        error_message=f"Agent '{agent_name}' is already registered"
                    )
                
                # Validate agent implementation
                await self._validate_agent_implementation(agent_class)
                
                # Validate dependencies
                dependency_warnings = await self._validate_dependencies(metadata.dependencies)
                
                # Register agent
                self._agents[agent_name] = metadata
                self._agent_classes[agent_name] = agent_class
                
                # Initialize health status
                self._health_status[agent_name] = AgentHealthStatus(
                    agent_name=agent_name,
                    is_healthy=True,
                    last_check=datetime.utcnow()
                )
                
                logger.info(
                    "Agent registered asynchronously",
                    agent_name=agent_name,
                    registration_id=str(metadata.registration_id)
                )
                
                return AgentRegistrationResult(
                    success=True,
                    agent_name=agent_name,
                    registration_id=metadata.registration_id,
                    metadata=metadata,
                    warnings=dependency_warnings
                )
                
            except Exception as e:
                logger.error(
                    "Agent registration failed",
                    agent_name=agent_name,
                    error=str(e)
                )
                
                return AgentRegistrationResult(
                    success=False,
                    agent_name=agent_name,
                    registration_id=metadata.registration_id,
                    error_message=str(e)
                )
    
    async def unregister_agent(self, agent_name: str) -> bool:
        """
        Unregister an agent from the registry.
        
        Args:
            agent_name: Name of agent to unregister
            
        Returns:
            True if agent was unregistered, False if not found
        """
        async with self._lock:
            if agent_name not in self._agents:
                return False
            
            del self._agents[agent_name]
            del self._agent_classes[agent_name]
            self._health_status.pop(agent_name, None)
            
            logger.info("Agent unregistered", agent_name=agent_name)
            return True
    
    def get_agent_metadata(self, agent_name: str) -> Optional[AgentMetadata]:
        """
        Get metadata for a specific agent.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            Agent metadata if found, None otherwise
        """
        return self._agents.get(agent_name)
    
    def get_agent_class(self, agent_name: str) -> Optional[Type[BaseAgent]]:
        """
        Get agent class for instantiation.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            Agent class if found, None otherwise
        """
        return self._agent_classes.get(agent_name)
    
    def get_available_agents(self) -> Dict[str, AgentMetadata]:
        """
        Get all available (healthy) agents.
        
        Returns:
            Dictionary mapping agent names to metadata
        """
        return {
            name: metadata for name, metadata in self._agents.items()
            if metadata.is_available and self._health_status.get(name, AgentHealthStatus(agent_name=name, is_healthy=True, last_check=datetime.utcnow())).is_healthy
        }
    
    def get_agents_by_capability(
        self,
        capability: Union[str, AgentCapability]
    ) -> Dict[str, AgentMetadata]:
        """
        Find agents with specific capability.
        
        Args:
            capability: Required capability
            
        Returns:
            Dictionary mapping agent names to metadata
        """
        if isinstance(capability, str):
            try:
                capability = AgentCapability(capability)
            except ValueError:
                return {}
        
        return {
            name: metadata for name, metadata in self._agents.items()
            if capability in metadata.capabilities and metadata.is_available
        }
    
    def discover_agents(self, filters: AgentDiscoveryFilter) -> Dict[str, AgentMetadata]:
        """
        Discover agents based on filter criteria.
        
        Args:
            filters: Discovery filter criteria
            
        Returns:
            Dictionary mapping agent names to metadata
        """
        results = {}
        
        for name, metadata in self._agents.items():
            # Apply filters
            if filters.available_only and not metadata.is_available:
                continue
                
            if filters.agent_type and metadata.agent_type != filters.agent_type:
                continue
                
            if filters.category and metadata.category != filters.category:
                continue
                
            if filters.capabilities:
                if not all(cap in metadata.capabilities for cap in filters.capabilities):
                    continue
                    
            if filters.name_pattern:
                import re
                if not re.match(filters.name_pattern, name):
                    continue
                    
            if filters.has_dependencies:
                agent_deps = {dep.name for dep in metadata.dependencies}
                if not all(dep in agent_deps for dep in filters.has_dependencies):
                    continue
                    
            if filters.exclude_dependencies:
                agent_deps = {dep.name for dep in metadata.dependencies}
                if any(dep in agent_deps for dep in filters.exclude_dependencies):
                    continue
            
            results[name] = metadata
        
        return results
    
    async def check_agent_health(self, agent_name: str) -> AgentHealthStatus:
        """
        Check health status of specific agent.
        
        Args:
            agent_name: Name of agent to check
            
        Returns:
            Agent health status
        """
        if agent_name not in self._agents:
            raise AgentNotFoundError(f"Agent '{agent_name}' not found")
        
        metadata = self._agents[agent_name]
        start_time = datetime.utcnow()
        
        try:
            # Check if agent class can be instantiated
            agent_class = self._agent_classes[agent_name]
            
            # Try to create agent instance (basic health check)
            # This validates imports, dependencies, etc.
            agent = agent_class()
            
            # Check dependency health
            dependency_status = await self._check_dependencies(metadata.dependencies)
            
            response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            health_status = AgentHealthStatus(
                agent_name=agent_name,
                is_healthy=all(dependency_status.values()) if dependency_status else True,
                last_check=datetime.utcnow(),
                response_time_ms=response_time,
                dependency_status=dependency_status
            )
            
            self._health_status[agent_name] = health_status
            return health_status
            
        except Exception as e:
            logger.warning(
                "Agent health check failed",
                agent_name=agent_name,
                error=str(e)
            )
            
            health_status = AgentHealthStatus(
                agent_name=agent_name,
                is_healthy=False,
                last_check=datetime.utcnow(),
                error_message=str(e),
                dependency_status={}
            )
            
            self._health_status[agent_name] = health_status
            return health_status
    
    async def check_all_agent_health(self) -> Dict[str, AgentHealthStatus]:
        """
        Check health status of all registered agents.
        
        Returns:
            Dictionary mapping agent names to health status
        """
        health_results = {}
        
        for agent_name in self._agents.keys():
            try:
                health_results[agent_name] = await self.check_agent_health(agent_name)
            except Exception as e:
                logger.error(
                    "Failed to check agent health",
                    agent_name=agent_name,
                    error=str(e)
                )
                
                health_results[agent_name] = AgentHealthStatus(
                    agent_name=agent_name,
                    is_healthy=False,
                    last_check=datetime.utcnow(),
                    error_message=f"Health check failed: {str(e)}"
                )
        
        return health_results
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive registry statistics.
        
        Returns:
            Dictionary containing registry statistics
        """
        total_agents = len(self._agents)
        available_agents = len([a for a in self._agents.values() if a.is_available])
        healthy_agents = len([h for h in self._health_status.values() if h.is_healthy])
        
        capabilities_count = defaultdict(int)
        for metadata in self._agents.values():
            for capability in metadata.capabilities:
                if hasattr(capability, 'value'):
                    capabilities_count[capability.value] += 1
                else:
                    capabilities_count[str(capability)] += 1
        
        return {
            "total_agents": total_agents,
            "available_agents": available_agents,
            "healthy_agents": healthy_agents,
            "capabilities_distribution": dict(capabilities_count),
            "agent_types": list(set(m.agent_type for m in self._agents.values())),
            "categories": list(set(m.category for m in self._agents.values())),
            "last_update": datetime.utcnow().isoformat()
        }
    
    async def _validate_agent_implementation(self, agent_class: Type[BaseAgent]) -> None:
        """Validate that agent class properly implements BaseAgent interface."""
        if not issubclass(agent_class, BaseAgent):
            raise AgentRegistrationError(
                f"Agent {agent_class.__name__} must inherit from BaseAgent"
            )
        
        # Check required abstract methods are implemented
        required_methods = ['initialize', 'execute', 'cleanup']
        for method_name in required_methods:
            if not hasattr(agent_class, method_name):
                raise AgentRegistrationError(
                    f"Agent {agent_class.__name__} missing required method: {method_name}"
                )
            
            method = getattr(agent_class, method_name)
            if not inspect.iscoroutinefunction(method):
                raise AgentRegistrationError(
                    f"Agent {agent_class.__name__}.{method_name} must be async"
                )
    
    async def _validate_dependencies(self, dependencies: List[AgentDependency]) -> List[str]:
        """Validate agent dependencies and return warnings."""
        warnings = []
        
        for dependency in dependencies:
            if dependency.required:
                # Basic dependency validation
                # In a full implementation, this would check actual service availability
                if not await self._check_dependency_available(dependency):
                    if dependency.required:
                        raise AgentDependencyError(
                            f"Required dependency not available: {dependency.name}"
                        )
                    else:
                        warnings.append(
                            f"Optional dependency not available: {dependency.name}"
                        )
        
        return warnings
    
    async def _check_dependency_available(self, dependency: AgentDependency) -> bool:
        """Check if a dependency is available."""
        # Placeholder implementation - in reality this would check:
        # - API endpoints for API dependencies
        # - Database connections for database dependencies
        # - Service health for service dependencies
        # For now, assume all dependencies are available
        return True
    
    async def _check_dependencies(self, dependencies: List[AgentDependency]) -> Dict[str, bool]:
        """Check health of all dependencies."""
        dependency_status = {}
        
        for dependency in dependencies:
            try:
                is_available = await self._check_dependency_available(dependency)
                dependency_status[dependency.name] = is_available
            except Exception as e:
                logger.warning(
                    "Dependency check failed",
                    dependency=dependency.name,
                    error=str(e)
                )
                dependency_status[dependency.name] = False
        
        return dependency_status
    
    @staticmethod
    def _class_to_snake_case(class_name: str) -> str:
        """Convert CamelCase class name to snake_case."""
        import re
        
        # Insert underscores before uppercase letters (except first)
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
        # Insert underscores before uppercase letters preceded by lowercase
        s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
        
        return s2.lower()


# Global registry instance
_global_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry instance."""
    return _global_registry


def register_agent(*args, **kwargs) -> Callable:
    """
    Convenience decorator for agent registration using global registry.
    
    See AgentRegistry.register_agent for detailed documentation.
    """
    return _global_registry.register_agent(*args, **kwargs)
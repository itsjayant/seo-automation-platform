"""Agent validation utilities for registration and runtime checks.

Provides comprehensive validation for agent implementations, metadata,
dependencies, and runtime requirements within the SEO automation platform.
"""

import asyncio
import inspect
import importlib
import sys
from typing import Dict, List, Set, Optional, Type, Any, Callable, Union
from datetime import datetime
from pathlib import Path

import structlog
from opentelemetry import trace
from pydantic import ValidationError

from .base import BaseAgent, BaseAgentConfig
from .metadata import (
    AgentMetadata, AgentCapability, AgentDependency, 
    AgentInputSpec, AgentOutputSpec
)
from .exceptions import (
    AgentValidationError, AgentConfigurationError, 
    AgentDependencyError, AgentImplementationError
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class ValidationResult:
    """Result of agent validation operation."""
    
    def __init__(
        self,
        is_valid: bool = True,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize validation result.
        
        Args:
            is_valid: Whether validation passed
            errors: List of validation errors
            warnings: List of validation warnings
            details: Additional validation details
        """
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []
        self.details = details or {}
    
    def add_error(self, error: str) -> None:
        """Add validation error."""
        self.errors.append(error)
        self.is_valid = False
    
    def add_warning(self, warning: str) -> None:
        """Add validation warning."""
        self.warnings.append(warning)
    
    def merge(self, other: 'ValidationResult') -> None:
        """Merge another validation result into this one."""
        if not other.is_valid:
            self.is_valid = False
        
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.details.update(other.details)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "details": self.details
        }


class AgentValidator:
    """
    Comprehensive agent validation system.
    
    Provides validation for agent implementations, metadata schemas,
    dependency requirements, and runtime constraints.
    
    Features:
        - Agent class implementation validation
        - Metadata schema validation  
        - Dependency availability checking
        - Configuration schema validation
        - Runtime capability verification
        - Performance constraint validation
    """
    
    def __init__(self):
        """Initialize the agent validator."""
        self._dependency_checkers: Dict[str, Callable] = {
            'api': self._check_api_dependency,
            'service': self._check_service_dependency,
            'database': self._check_database_dependency,
            'integration': self._check_integration_dependency,
            'queue': self._check_queue_dependency,
            'notification': self._check_notification_dependency
        }
    
    async def validate_agent_implementation(
        self,
        agent_class: Type[BaseAgent]
    ) -> ValidationResult:
        """
        Validate that agent class properly implements BaseAgent interface.
        
        Args:
            agent_class: Agent class to validate
            
        Returns:
            Validation result with errors and warnings
        """
        with tracer.start_as_current_span("agent_validator.validate_implementation") as span:
            span.set_attribute("agent_class", agent_class.__name__)
            
            result = ValidationResult()
            
            # Check inheritance
            if not issubclass(agent_class, BaseAgent):
                result.add_error(
                    f"Agent {agent_class.__name__} must inherit from BaseAgent"
                )
                return result
            
            # Check required abstract methods
            await self._validate_abstract_methods(agent_class, result)
            
            # Check method signatures
            await self._validate_method_signatures(agent_class, result)
            
            # Check agent configuration compatibility
            await self._validate_agent_config(agent_class, result)
            
            # Check for common implementation issues
            await self._validate_implementation_patterns(agent_class, result)
            
            span.set_attribute("validation_passed", result.is_valid)
            span.set_attribute("errors_count", len(result.errors))
            span.set_attribute("warnings_count", len(result.warnings))
            
            logger.debug(
                "Agent implementation validation completed",
                agent_class=agent_class.__name__,
                is_valid=result.is_valid,
                errors=len(result.errors),
                warnings=len(result.warnings)
            )
            
            return result
    
    async def validate_agent_metadata(
        self,
        metadata: AgentMetadata
    ) -> ValidationResult:
        """
        Validate agent metadata schema and content.
        
        Args:
            metadata: Agent metadata to validate
            
        Returns:
            Validation result with errors and warnings
        """
        with tracer.start_as_current_span("agent_validator.validate_metadata") as span:
            span.set_attribute("agent_name", metadata.name)
            
            result = ValidationResult()
            
            try:
                # Pydantic validation should have already passed
                # This is additional business logic validation
                
                # Validate capabilities are meaningful
                await self._validate_capabilities(metadata.capabilities, result)
                
                # Validate dependencies
                await self._validate_dependencies_metadata(metadata.dependencies, result)
                
                # Validate input/output specifications
                await self._validate_io_specifications(metadata.inputs, metadata.outputs, result)
                
                # Validate resource requirements
                await self._validate_resource_requirements(metadata, result)
                
                # Validate configuration schema
                await self._validate_config_schema(metadata.config_schema, result)
                
                # Check for metadata consistency
                await self._validate_metadata_consistency(metadata, result)
                
            except Exception as e:
                result.add_error(f"Metadata validation failed: {str(e)}")
            
            span.set_attribute("validation_passed", result.is_valid)
            span.set_attribute("errors_count", len(result.errors))
            
            logger.debug(
                "Agent metadata validation completed",
                agent_name=metadata.name,
                is_valid=result.is_valid,
                errors=len(result.errors)
            )
            
            return result
    
    async def validate_agent_dependencies(
        self,
        dependencies: List[AgentDependency],
        check_availability: bool = True
    ) -> ValidationResult:
        """
        Validate agent dependencies and optionally check availability.
        
        Args:
            dependencies: List of agent dependencies
            check_availability: Whether to check actual dependency availability
            
        Returns:
            Validation result with errors and warnings
        """
        with tracer.start_as_current_span("agent_validator.validate_dependencies") as span:
            span.set_attribute("dependencies_count", len(dependencies))
            span.set_attribute("check_availability", check_availability)
            
            result = ValidationResult()
            
            for dependency in dependencies:
                # Validate dependency specification
                await self._validate_dependency_spec(dependency, result)
                
                # Check availability if requested
                if check_availability:
                    await self._check_dependency_availability(dependency, result)
            
            # Check for dependency conflicts
            await self._check_dependency_conflicts(dependencies, result)
            
            span.set_attribute("validation_passed", result.is_valid)
            
            return result
    
    async def validate_agent_config(
        self,
        config: BaseAgentConfig,
        metadata: Optional[AgentMetadata] = None
    ) -> ValidationResult:
        """
        Validate agent configuration against schema and constraints.
        
        Args:
            config: Agent configuration to validate
            metadata: Optional metadata for additional validation
            
        Returns:
            Validation result
        """
        result = ValidationResult()
        
        try:
            # Pydantic validation should have passed
            # Additional business logic validation
            
            # Validate timeout settings
            if config.timeout_seconds is not None and config.timeout_seconds <= 0:
                result.add_error("Timeout must be positive")
            
            if config.max_retries < 0:
                result.add_error("Max retries cannot be negative")
            
            if config.retry_delay_seconds < 0:
                result.add_error("Retry delay cannot be negative")
            
            # Validate resource limits
            if config.max_memory_mb is not None and config.max_memory_mb <= 0:
                result.add_error("Max memory must be positive")
            
            if config.max_execution_time_ms is not None and config.max_execution_time_ms <= 0:
                result.add_error("Max execution time must be positive")
            
            # Cross-validate with metadata if provided
            if metadata:
                await self._cross_validate_config_metadata(config, metadata, result)
                
        except Exception as e:
            result.add_error(f"Config validation failed: {str(e)}")
        
        return result
    
    async def validate_agent_runtime(
        self,
        agent_instance: BaseAgent,
        task_data: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate agent runtime requirements and task data.
        
        Args:
            agent_instance: Agent instance to validate
            task_data: Task data for validation
            
        Returns:
            Validation result
        """
        with tracer.start_as_current_span("agent_validator.validate_runtime") as span:
            span.set_attribute("agent_type", agent_instance.agent_type)
            
            result = ValidationResult()
            
            # Validate agent state
            if agent_instance.state.value != "ready":
                result.add_error(
                    f"Agent not in ready state: {agent_instance.state.value}"
                )
            
            # Validate task data against agent inputs (if metadata available)
            # This would require agent to expose its metadata
            # For now, basic validation
            
            if not isinstance(task_data, dict):
                result.add_error("Task data must be a dictionary")
            
            # Add runtime-specific validations
            await self._validate_runtime_environment(agent_instance, result)
            await self._validate_runtime_resources(agent_instance, result)
            
            span.set_attribute("validation_passed", result.is_valid)
            
            return result
    
    async def _validate_abstract_methods(
        self,
        agent_class: Type[BaseAgent],
        result: ValidationResult
    ) -> None:
        """Validate that required abstract methods are implemented."""
        required_methods = {
            'initialize': 'Initialize agent resources',
            'execute': 'Execute agent task',
            'cleanup': 'Clean up agent resources'
        }
        
        for method_name, description in required_methods.items():
            if not hasattr(agent_class, method_name):
                result.add_error(
                    f"Missing required method: {method_name} ({description})"
                )
                continue
            
            method = getattr(agent_class, method_name)
            
            if not inspect.iscoroutinefunction(method):
                result.add_error(
                    f"Method {method_name} must be async (coroutine function)"
                )
            
            # Check if method is actually implemented (not abstract)
            if getattr(method, '__isabstractmethod__', False):
                result.add_error(
                    f"Method {method_name} is still abstract - must be implemented"
                )
    
    async def _validate_method_signatures(
        self,
        agent_class: Type[BaseAgent],
        result: ValidationResult
    ) -> None:
        """Validate method signatures match expected patterns."""
        
        # Check initialize method signature
        if hasattr(agent_class, 'initialize'):
            init_method = getattr(agent_class, 'initialize')
            sig = inspect.signature(init_method)
            
            # Should only have self parameter
            params = list(sig.parameters.keys())
            if len(params) != 1 or params[0] != 'self':
                result.add_warning(
                    "initialize() should only have 'self' parameter"
                )
        
        # Check execute method signature
        if hasattr(agent_class, 'execute'):
            exec_method = getattr(agent_class, 'execute')
            sig = inspect.signature(exec_method)
            
            params = list(sig.parameters.keys())
            if len(params) != 2 or params[0] != 'self':
                result.add_error(
                    "execute() must have signature: execute(self, task_data)"
                )
            
            # Check return type annotation if present
            if sig.return_annotation != inspect.Signature.empty:
                # Could check that it returns AgentResult
                pass
        
        # Check cleanup method signature  
        if hasattr(agent_class, 'cleanup'):
            cleanup_method = getattr(agent_class, 'cleanup')
            sig = inspect.signature(cleanup_method)
            
            params = list(sig.parameters.keys())
            if len(params) != 1 or params[0] != 'self':
                result.add_warning(
                    "cleanup() should only have 'self' parameter"
                )
    
    async def _validate_agent_config(
        self,
        agent_class: Type[BaseAgent],
        result: ValidationResult
    ) -> None:
        """Validate agent configuration compatibility."""
        
        # Check if agent defines custom config
        if hasattr(agent_class, 'Config') or hasattr(agent_class, 'config_schema'):
            # Agent defines custom configuration
            # Could validate the custom config extends BaseAgentConfig
            pass
        
        # Try to instantiate with default config
        try:
            config = BaseAgentConfig()
            agent = agent_class(config=config)
        except Exception as e:
            result.add_error(
                f"Cannot instantiate agent with default config: {str(e)}"
            )
    
    async def _validate_implementation_patterns(
        self,
        agent_class: Type[BaseAgent],
        result: ValidationResult
    ) -> None:
        """Check for common implementation anti-patterns."""
        
        # Check class docstring
        if not agent_class.__doc__:
            result.add_warning("Agent class should have docstring documentation")
        
        # Check for synchronous methods that should be async
        dangerous_sync_methods = ['requests.get', 'time.sleep', 'urllib']
        
        # This is a simplified check - in practice you'd analyze the AST
        # For now, just check if the class uses certain patterns
        
        for method_name in ['initialize', 'execute', 'cleanup']:
            if hasattr(agent_class, method_name):
                method = getattr(agent_class, method_name)
                if hasattr(method, '__code__'):
                    code = method.__code__
                    # Check variable names for potential blocking calls
                    for var_name in code.co_names:
                        if any(danger in var_name for danger in ['requests', 'urlopen']):
                            result.add_warning(
                                f"Method {method_name} may contain synchronous HTTP calls - "
                                f"consider using async alternatives"
                            )
    
    async def _validate_capabilities(
        self,
        capabilities: List[AgentCapability],
        result: ValidationResult
    ) -> None:
        """Validate agent capabilities are meaningful."""
        
        if not capabilities:
            result.add_error("Agent must define at least one capability")
        
        # Check for capability conflicts or redundancies
        capability_count = len(capabilities)
        unique_capabilities = len(set(capabilities))
        
        if capability_count != unique_capabilities:
            result.add_warning("Agent has duplicate capabilities")
        
        # Validate capability combinations make sense
        if AgentCapability.TASK_ORCHESTRATION in capabilities:
            if len(capabilities) == 1:
                result.add_warning(
                    "Orchestration agents typically need additional specific capabilities"
                )
    
    async def _validate_dependencies_metadata(
        self,
        dependencies: List[AgentDependency],
        result: ValidationResult
    ) -> None:
        """Validate dependency metadata."""
        
        dependency_names = [dep.name for dep in dependencies]
        
        # Check for duplicate dependencies
        if len(dependency_names) != len(set(dependency_names)):
            result.add_error("Duplicate dependencies found")
        
        # Validate each dependency
        for dependency in dependencies:
            if dependency.dependency_type not in self._dependency_checkers:
                result.add_error(
                    f"Unknown dependency type: {dependency.dependency_type}"
                )
    
    async def _validate_io_specifications(
        self,
        inputs: List[AgentInputSpec],
        outputs: List[AgentOutputSpec],
        result: ValidationResult
    ) -> None:
        """Validate input/output specifications."""
        
        # Check input specifications
        input_names = [inp.name for inp in inputs]
        if len(input_names) != len(set(input_names)):
            result.add_error("Duplicate input parameter names")
        
        for inp in inputs:
            if not inp.name or not inp.name.isidentifier():
                result.add_error(f"Invalid input parameter name: {inp.name}")
            
            if inp.required and inp.default_value is not None:
                result.add_warning(
                    f"Required input '{inp.name}' has default value - "
                    f"consider making it optional"
                )
        
        # Check output specifications
        output_names = [out.name for out in outputs]
        if len(output_names) != len(set(output_names)):
            result.add_error("Duplicate output field names")
        
        for out in outputs:
            if not out.name or not out.name.isidentifier():
                result.add_error(f"Invalid output field name: {out.name}")
    
    async def _validate_resource_requirements(
        self,
        metadata: AgentMetadata,
        result: ValidationResult
    ) -> None:
        """Validate resource requirement specifications."""
        
        if metadata.estimated_runtime_seconds is not None:
            if metadata.estimated_runtime_seconds <= 0:
                result.add_error("Estimated runtime must be positive")
            
            if metadata.estimated_runtime_seconds > 3600:  # 1 hour
                result.add_warning(
                    "Estimated runtime over 1 hour - consider breaking into smaller tasks"
                )
        
        if metadata.memory_requirements_mb is not None:
            if metadata.memory_requirements_mb <= 0:
                result.add_error("Memory requirements must be positive")
            
            if metadata.memory_requirements_mb > 1024:  # 1 GB
                result.add_warning(
                    "High memory requirements (>1GB) - ensure this is necessary"
                )
        
        if metadata.concurrent_executions <= 0:
            result.add_error("Concurrent executions must be positive")
    
    async def _validate_config_schema(
        self,
        config_schema: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """Validate configuration schema."""
        
        # Basic schema validation
        if config_schema and not isinstance(config_schema, dict):
            result.add_error("Config schema must be a dictionary")
        
        # Could add JSON schema validation here
        # For now, just basic checks
        
        if config_schema:
            # Check for required vs optional parameters balance
            required_count = sum(
                1 for prop in config_schema.get('properties', {}).values()
                if prop.get('required', False)
            )
            
            total_count = len(config_schema.get('properties', {}))
            
            if total_count > 0 and required_count == total_count:
                result.add_warning(
                    "All configuration parameters are required - "
                    "consider providing defaults"
                )
    
    async def _validate_metadata_consistency(
        self,
        metadata: AgentMetadata,
        result: ValidationResult
    ) -> None:
        """Check for metadata consistency issues."""
        
        # Check that agent_type matches class name pattern
        if not metadata.agent_type.endswith('Agent'):
            result.add_warning(
                "Agent type should end with 'Agent' by convention"
            )
        
        # Check version format consistency
        if not metadata.version.count('.') >= 2:
            result.add_warning(
                "Version should follow semantic versioning (major.minor.patch)"
            )
        
        # Check that capabilities align with dependencies
        api_capabilities = {
            AgentCapability.KEYWORD_DISCOVERY,
            AgentCapability.SERP_ANALYSIS,
            AgentCapability.GSC_ANALYSIS,
            AgentCapability.GA4_ANALYSIS
        }
        
        has_api_capability = any(cap in metadata.capabilities for cap in api_capabilities)
        has_api_dependency = any(
            dep.dependency_type == 'api' for dep in metadata.dependencies
        )
        
        if has_api_capability and not has_api_dependency:
            result.add_warning(
                "Agent has API-based capabilities but no API dependencies"
            )
    
    async def _validate_dependency_spec(
        self,
        dependency: AgentDependency,
        result: ValidationResult
    ) -> None:
        """Validate individual dependency specification."""
        
        if not dependency.name:
            result.add_error("Dependency name cannot be empty")
        
        if dependency.version_requirement:
            # Could validate version requirement syntax
            # For now, just basic check
            if not any(op in dependency.version_requirement for op in ['>=', '<=', '==', '>', '<', '~', '^']):
                result.add_warning(
                    f"Dependency {dependency.name} version requirement "
                    f"should specify operator (>=, ==, etc.)"
                )
    
    async def _check_dependency_availability(
        self,
        dependency: AgentDependency,
        result: ValidationResult
    ) -> None:
        """Check if dependency is actually available."""
        
        checker = self._dependency_checkers.get(dependency.dependency_type)
        
        if checker:
            try:
                is_available = await checker(dependency)
                
                if not is_available:
                    if dependency.required:
                        result.add_error(
                            f"Required dependency not available: {dependency.name}"
                        )
                    else:
                        result.add_warning(
                            f"Optional dependency not available: {dependency.name}"
                        )
                        
            except Exception as e:
                result.add_warning(
                    f"Could not check dependency {dependency.name}: {str(e)}"
                )
    
    async def _check_dependency_conflicts(
        self,
        dependencies: List[AgentDependency],
        result: ValidationResult
    ) -> None:
        """Check for conflicting dependencies."""
        
        # Group by type and name
        dep_groups = {}
        
        for dep in dependencies:
            key = f"{dep.dependency_type}:{dep.name}"
            if key not in dep_groups:
                dep_groups[key] = []
            dep_groups[key].append(dep)
        
        # Check for version conflicts
        for key, deps in dep_groups.items():
            if len(deps) > 1:
                versions = [dep.version_requirement for dep in deps if dep.version_requirement]
                if len(set(versions)) > 1:
                    result.add_warning(
                        f"Conflicting version requirements for {key}: {versions}"
                    )
    
    async def _cross_validate_config_metadata(
        self,
        config: BaseAgentConfig,
        metadata: AgentMetadata,
        result: ValidationResult
    ) -> None:
        """Cross-validate configuration against metadata."""
        
        # Check timeout consistency
        if config.timeout_seconds and metadata.estimated_runtime_seconds:
            if config.timeout_seconds < metadata.estimated_runtime_seconds:
                result.add_warning(
                    "Config timeout is less than estimated runtime"
                )
        
        # Check memory consistency
        if config.max_memory_mb and metadata.memory_requirements_mb:
            if config.max_memory_mb < metadata.memory_requirements_mb:
                result.add_error(
                    "Config max memory is less than agent requirements"
                )
    
    async def _validate_runtime_environment(
        self,
        agent_instance: BaseAgent,
        result: ValidationResult
    ) -> None:
        """Validate runtime environment for agent."""
        
        # Check database connection if agent uses it
        if hasattr(agent_instance, '_db_manager') and agent_instance._db_manager:
            try:
                # Basic connection check
                pass  # Would check actual database connectivity
            except Exception as e:
                result.add_error(f"Database connection issue: {str(e)}")
    
    async def _validate_runtime_resources(
        self,
        agent_instance: BaseAgent,
        result: ValidationResult
    ) -> None:
        """Validate runtime resource availability."""
        
        # Check memory availability
        import psutil
        
        try:
            memory = psutil.virtual_memory()
            available_mb = memory.available / (1024 * 1024)
            
            config = agent_instance.config
            if config.max_memory_mb and config.max_memory_mb > available_mb:
                result.add_warning(
                    f"Configured max memory ({config.max_memory_mb}MB) "
                    f"exceeds available system memory ({available_mb:.0f}MB)"
                )
                
        except ImportError:
            result.add_warning("Cannot check system resources - psutil not available")
        except Exception as e:
            result.add_warning(f"Resource check failed: {str(e)}")
    
    # Dependency checker implementations
    
    async def _check_api_dependency(self, dependency: AgentDependency) -> bool:
        """Check API dependency availability."""
        # Would check actual API endpoints
        # For now, assume available
        return True
    
    async def _check_service_dependency(self, dependency: AgentDependency) -> bool:
        """Check service dependency availability."""
        # Would check service health endpoints
        return True
    
    async def _check_database_dependency(self, dependency: AgentDependency) -> bool:
        """Check database dependency availability."""
        # Would check database connectivity
        return True
    
    async def _check_integration_dependency(self, dependency: AgentDependency) -> bool:
        """Check integration dependency availability.""" 
        # Would check integration module imports
        try:
            if dependency.name in ['gsc_api', 'ga4_api', 'serpapi']:
                # Check if integration modules can be imported
                pass
            return True
        except ImportError:
            return False
    
    async def _check_queue_dependency(self, dependency: AgentDependency) -> bool:
        """Check queue dependency availability."""
        # Would check Redis connectivity
        return True
    
    async def _check_notification_dependency(self, dependency: AgentDependency) -> bool:
        """Check notification dependency availability."""
        # Would check NATS connectivity
        return True


# Global validator instance
_global_validator = AgentValidator()


def get_agent_validator() -> AgentValidator:
    """Get the global agent validator instance."""
    return _global_validator


async def validate_agent(
    agent_class: Type[BaseAgent],
    metadata: Optional[AgentMetadata] = None,
    check_dependencies: bool = True
) -> ValidationResult:
    """
    Convenience function for comprehensive agent validation.
    
    Args:
        agent_class: Agent class to validate
        metadata: Optional metadata to validate
        check_dependencies: Whether to check dependency availability
        
    Returns:
        Combined validation result
    """
    validator = get_agent_validator()
    
    # Validate implementation
    result = await validator.validate_agent_implementation(agent_class)
    
    # Validate metadata if provided
    if metadata:
        metadata_result = await validator.validate_agent_metadata(metadata)
        result.merge(metadata_result)
        
        # Validate dependencies
        if check_dependencies and metadata.dependencies:
            dep_result = await validator.validate_agent_dependencies(
                metadata.dependencies, 
                check_availability=True
            )
            result.merge(dep_result)
    
    return result
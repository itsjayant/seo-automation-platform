"""Agent-specific exceptions for error handling and classification.

Provides a hierarchy of exceptions for different types of agent failures,
enabling proper error handling and recovery mechanisms.
"""

from typing import Optional, Dict, Any


class AgentException(Exception):
    """Base exception for all agent-related errors.
    
    All agent exceptions inherit from this base class to enable
    consistent error handling and logging across the agent ecosystem.
    """
    
    def __init__(
        self, 
        message: str, 
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.cause = cause
        
    def __str__(self) -> str:
        if self.context:
            return f"{self.message} (context: {self.context})"
        return self.message
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
            "cause": str(self.cause) if self.cause else None
        }


class AgentInitializationError(AgentException):
    """Raised when an agent fails to initialize properly.
    
    This typically indicates configuration issues, missing dependencies,
    or unavailable external resources required by the agent.
    """
    pass


class AgentExecutionError(AgentException):
    """Raised when an agent fails during execution.
    
    This covers runtime errors during the main agent logic,
    excluding initialization and cleanup phases.
    """
    pass


class AgentTimeoutError(AgentException):
    """Raised when an agent operation exceeds time limits.
    
    Used for operations that have explicit timeout constraints
    to prevent hanging or resource exhaustion.
    """
    
    def __init__(
        self, 
        message: str,
        timeout_seconds: float,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message, context, cause)
        self.timeout_seconds = timeout_seconds


class AgentConfigurationError(AgentException):
    """Raised when an agent has invalid or missing configuration.
    
    This indicates problems with agent settings, environment variables,
    or other configuration values required for proper operation.
    """
    pass


class AgentResourceError(AgentException):
    """Raised when an agent cannot acquire required resources.
    
    This covers database connections, API clients, temporary files,
    or other system resources that the agent needs to function.
    """
    pass


class AgentValidationError(AgentException):
    """Raised when agent input or output validation fails.
    
    Used for data validation errors, schema mismatches,
    or other input/output related problems.
    """
    pass


class AgentRegistrationError(AgentException):
    """Raised when an agent cannot be registered with the registry.
    
    This indicates problems with agent metadata, implementation issues,
    or conflicts with existing registered agents.
    """
    pass


class AgentNotFoundError(AgentException):
    """Raised when a requested agent cannot be found in the registry.
    
    This typically occurs when trying to access an agent that was
    not registered or has been removed from the registry.
    """
    pass


class AgentDependencyError(AgentException):
    """Raised when agent dependencies cannot be satisfied.
    
    This indicates missing or unavailable dependencies required
    by an agent for proper operation.
    """
    pass


class AgentDiscoveryError(AgentException):
    """Raised when the agent discovery system encounters errors.
    
    This covers module scanning failures, import errors during discovery,
    or other issues with the dynamic agent loading process.
    """
    pass


class AgentLoadingError(AgentException):
    """Raised when an agent module cannot be loaded or imported.
    
    This typically indicates Python import errors, missing modules,
    or syntax errors in agent implementation files.
    """
    pass


class AgentImplementationError(AgentException):
    """Raised when an agent implementation doesn't meet requirements.
    
    This covers missing methods, incorrect signatures, or other
    implementation issues that prevent proper agent operation.
    """
    pass
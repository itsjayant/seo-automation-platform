"""Agent metadata models for registration and discovery.

Provides standardized metadata schemas for agent registration,
capability definitions, and dependency management within the
agent registry system.
"""

from typing import Dict, Any, List, Optional, Type
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, validator
from uuid import UUID, uuid4


class AgentCapability(str, Enum):
    """Standard agent capabilities for task routing."""
    
    # Keyword research capabilities
    KEYWORD_DISCOVERY = "keyword_discovery"
    KEYWORD_CLUSTERING = "keyword_clustering"
    SERP_ANALYSIS = "serp_analysis"
    INTENT_CLASSIFICATION = "intent_classification"
    COMPETITION_ANALYSIS = "competition_analysis"
    
    # Content analysis capabilities
    CONTENT_AUDIT = "content_audit"
    CONTENT_OPTIMIZATION = "content_optimization"
    CONTENT_GAP_ANALYSIS = "content_gap_analysis"
    SEMANTIC_ANALYSIS = "semantic_analysis"
    TECHNICAL_ANALYSIS = "technical_analysis"
    
    # Performance analysis capabilities
    GSC_ANALYSIS = "gsc_analysis"
    GA4_ANALYSIS = "ga4_analysis"
    PERFORMANCE_MONITORING = "performance_monitoring"
    RANKING_TRACKING = "ranking_tracking"
    
    # Content generation capabilities (Future phases)
    CONTENT_GENERATION = "content_generation"
    META_OPTIMIZATION = "meta_optimization"
    SCHEMA_GENERATION = "schema_generation"
    
    # Link building capabilities (Future phases) 
    LINK_ANALYSIS = "link_analysis"
    LINK_OPPORTUNITY = "link_opportunity"
    
    # Automation capabilities
    TASK_ORCHESTRATION = "task_orchestration"
    WORKFLOW_MANAGEMENT = "workflow_management"
    REPORTING = "reporting"


class AgentDependency(BaseModel):
    """Agent dependency specification."""
    
    dependency_type: str = Field(description="Type of dependency (api, service, database)")
    name: str = Field(description="Dependency name")
    version_requirement: Optional[str] = Field(None, description="Version requirement spec")
    required: bool = Field(True, description="Whether dependency is required")
    description: Optional[str] = Field(None, description="Dependency description")
    
    @validator('dependency_type')
    def validate_dependency_type(cls, v):
        allowed_types = {'api', 'service', 'database', 'integration', 'queue', 'notification'}
        if v not in allowed_types:
            raise ValueError(f"Dependency type must be one of: {allowed_types}")
        return v


class AgentInputSpec(BaseModel):
    """Agent input specification."""
    
    name: str = Field(description="Input parameter name")
    type: str = Field(description="Input parameter type") 
    required: bool = Field(True, description="Whether input is required")
    description: Optional[str] = Field(None, description="Input description")
    default_value: Optional[Any] = Field(None, description="Default value if not required")
    validation_rules: Dict[str, Any] = Field(default_factory=dict, description="Validation constraints")


class AgentOutputSpec(BaseModel):
    """Agent output specification."""
    
    name: str = Field(description="Output field name")
    type: str = Field(description="Output field type")
    description: Optional[str] = Field(None, description="Output description")
    format: Optional[str] = Field(None, description="Output format specification")


class AgentMetadata(BaseModel):
    """Comprehensive agent metadata for registration and discovery."""
    
    # Basic identification
    name: str = Field(description="Unique agent name (snake_case)")
    version: str = Field(description="Agent version (semver)")
    display_name: Optional[str] = Field(None, description="Human-readable agent name")
    description: str = Field(description="Agent description")
    
    # Agent classification
    capabilities: List[AgentCapability] = Field(description="Agent capabilities")
    agent_type: str = Field(description="Agent type classifier")
    category: str = Field(description="Agent category for organization")
    
    # Dependencies and requirements
    dependencies: List[AgentDependency] = Field(default_factory=list, description="Agent dependencies")
    
    # Input/Output specifications
    inputs: List[AgentInputSpec] = Field(default_factory=list, description="Required inputs")
    outputs: List[AgentOutputSpec] = Field(default_factory=list, description="Expected outputs")
    
    # Execution characteristics
    estimated_runtime_seconds: Optional[float] = Field(None, description="Estimated execution time")
    memory_requirements_mb: Optional[float] = Field(None, description="Estimated memory usage")
    concurrent_executions: int = Field(1, description="Max concurrent executions allowed")
    
    # Configuration
    config_schema: Dict[str, Any] = Field(default_factory=dict, description="Configuration schema")
    default_config: Dict[str, Any] = Field(default_factory=dict, description="Default configuration")
    
    # Registration metadata
    registration_id: UUID = Field(default_factory=uuid4, description="Registration identifier")
    registered_at: datetime = Field(default_factory=datetime.utcnow, description="Registration timestamp")
    last_health_check: Optional[datetime] = Field(None, description="Last health check time")
    
    # Agent class reference
    agent_class: Optional[Any] = Field(None, description="Agent class reference")
    module_path: Optional[str] = Field(None, description="Module import path")
    
    # Status and availability
    is_available: bool = Field(True, description="Whether agent is available")
    health_status: str = Field("unknown", description="Agent health status")
    error_message: Optional[str] = Field(None, description="Error if unavailable")
    
    @validator('name')
    def validate_name(cls, v):
        """Validate agent name follows conventions."""
        if not v.replace('_', '').isalnum():
            raise ValueError("Agent name must be alphanumeric with underscores")
        if not v.islower():
            raise ValueError("Agent name must be lowercase")
        return v
    
    @validator('version')
    def validate_version(cls, v):
        """Validate version follows semantic versioning."""
        import re
        semver_pattern = r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)))?(?:\+([0-9a-zA-Z-]+))?$'
        if not re.match(semver_pattern, v):
            raise ValueError("Version must follow semantic versioning (e.g., 1.0.0)")
        return v
    
    @validator('capabilities')
    def validate_capabilities(cls, v):
        """Ensure at least one capability is defined."""
        if len(v) == 0:
            raise ValueError("Agent must have at least one capability")
        return v
    
    def has_capability(self, capability: AgentCapability) -> bool:
        """Check if agent has specified capability."""
        return capability in self.capabilities
    
    def has_dependency(self, dependency_name: str) -> bool:
        """Check if agent has specified dependency."""
        return any(dep.name == dependency_name for dep in self.dependencies)
    
    def get_required_dependencies(self) -> List[AgentDependency]:
        """Get list of required dependencies."""
        return [dep for dep in self.dependencies if dep.required]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary representation."""
        data = self.model_dump()
        
        # Convert enums to string values
        data['capabilities'] = [cap.value for cap in self.capabilities]
        
        # Remove class reference for serialization
        data.pop('agent_class', None)
        
        return data
    
    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True
        use_enum_values = True


class AgentRegistrationResult(BaseModel):
    """Result of agent registration operation."""
    
    success: bool = Field(description="Whether registration succeeded")
    agent_name: str = Field(description="Name of agent being registered")
    registration_id: UUID = Field(description="Registration identifier")
    metadata: Optional[AgentMetadata] = Field(None, description="Registered metadata")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    warnings: List[str] = Field(default_factory=list, description="Registration warnings")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Registration timestamp")


class AgentDiscoveryFilter(BaseModel):
    """Filter criteria for agent discovery."""
    
    capabilities: Optional[List[AgentCapability]] = Field(None, description="Required capabilities")
    agent_type: Optional[str] = Field(None, description="Agent type filter")
    category: Optional[str] = Field(None, description="Category filter")
    available_only: bool = Field(True, description="Only return available agents")
    name_pattern: Optional[str] = Field(None, description="Name pattern match")
    has_dependencies: Optional[List[str]] = Field(None, description="Must have dependencies")
    exclude_dependencies: Optional[List[str]] = Field(None, description="Must not have dependencies")


class AgentHealthStatus(BaseModel):
    """Agent health status information."""
    
    agent_name: str = Field(description="Agent name")
    is_healthy: bool = Field(description="Overall health status")
    last_check: datetime = Field(description="Last health check time")
    response_time_ms: Optional[float] = Field(None, description="Health check response time")
    error_message: Optional[str] = Field(None, description="Error if unhealthy")
    dependency_status: Dict[str, bool] = Field(default_factory=dict, description="Dependency health")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional health details")


# Rebuild models after all definitions are complete
def _rebuild_models():
    """Rebuild Pydantic models to resolve forward references."""
    try:
        AgentMetadata.model_rebuild()
    except Exception:
        # If rebuild fails, it's likely due to missing BaseAgent
        # This will be resolved when the module is properly imported
        pass


# Call rebuild on import
_rebuild_models()
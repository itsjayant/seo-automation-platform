"""
Pydantic models for approval workflow messages.

This module defines the structured data models used for approval requests
and responses in the NATS messaging system. All models include validation
and serialization for reliable message passing.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, ConfigDict


class ApprovalType(str, Enum):
    """Types of approval requests in the workflow."""
    CONTENT = "content"              # Content creation/modification approvals
    TECHNICAL = "technical"          # Technical changes (redirects, schema, etc.)
    PUBLISH = "publish"              # Content publishing approvals


class ApprovalPriority(str, Enum):
    """Priority levels for approval requests."""
    LOW = "low"                      # Low priority, can wait
    MEDIUM = "medium"                # Normal business priority  
    HIGH = "high"                    # High priority, needs quick response
    CRITICAL = "critical"            # Critical, immediate attention required


class ApprovalOutcome(str, Enum):
    """Possible outcomes of an approval request."""
    PENDING = "pending"              # Still waiting for response
    APPROVED = "approved"            # Approved by human reviewer
    REJECTED = "rejected"            # Rejected by human reviewer  
    TIMEOUT = "timeout"              # Timed out waiting for response
    CANCELLED = "cancelled"          # Cancelled before completion


class EntityReference(BaseModel):
    """Reference to an entity that requires approval."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    site_id: int = Field(..., description="ID of the site affected")
    entity_type: str = Field(..., description="Type of entity (post, page, redirect, etc.)")
    entity_id: Optional[Union[int, str, UUID]] = Field(None, description="ID of the specific entity")
    
    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        """Validate entity type format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Entity type cannot be empty")
        return v.strip().lower()


class ApprovalRequest(BaseModel):
    """
    Structured approval request message.
    
    This model defines the complete structure for approval requests sent
    through NATS. It includes all necessary context for human reviewers
    to make informed decisions.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Unique identifiers
    approval_id: UUID = Field(default_factory=uuid4, description="Unique approval request ID")
    correlation_id: Optional[str] = Field(None, description="Optional correlation ID for tracking")
    
    # Approval classification
    approval_type: ApprovalType = Field(..., description="Type of approval required")
    priority: ApprovalPriority = Field(ApprovalPriority.MEDIUM, description="Priority level")
    
    # Action details
    action: str = Field(..., description="Specific action requiring approval")
    description: str = Field(..., description="Human-readable description of the action")
    entity: EntityReference = Field(..., description="Entity affected by the action")
    
    # Context and metadata
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional context details")
    changes: Optional[Dict[str, Any]] = Field(None, description="Proposed changes to be made")
    risks: List[str] = Field(default_factory=list, description="Identified risks of the action")
    
    # Workflow metadata
    requested_by: str = Field(..., description="Agent or system requesting approval")
    requested_at: datetime = Field(default_factory=datetime.utcnow, description="Request timestamp")
    timeout_seconds: int = Field(300, ge=30, le=3600, description="Approval timeout in seconds")
    
    # Reply configuration
    reply_subject: Optional[str] = Field(None, description="Subject for approval response")
    
    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        """Validate action format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Action cannot be empty")
        return v.strip()
    
    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """Validate description format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Description cannot be empty")
        if len(v.strip()) < 10:
            raise ValueError("Description must be at least 10 characters")
        return v.strip()
    
    @field_validator("requested_by")
    @classmethod
    def validate_requested_by(cls, v: str) -> str:
        """Validate requester format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Requested_by cannot be empty")
        return v.strip()


class ApprovalResponse(BaseModel):
    """
    Structured approval response message.
    
    This model defines the response structure when humans approve
    or reject approval requests through the web dashboard or API.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Request reference
    approval_id: UUID = Field(..., description="Original approval request ID")
    correlation_id: Optional[str] = Field(None, description="Correlation ID from original request")
    
    # Decision details
    outcome: ApprovalOutcome = Field(..., description="Approval decision outcome")
    reason: Optional[str] = Field(None, description="Reason for the decision")
    conditions: List[str] = Field(default_factory=list, description="Conditions attached to approval")
    
    # Reviewer information
    reviewed_by: str = Field(..., description="User who made the decision")
    reviewed_at: datetime = Field(default_factory=datetime.utcnow, description="Decision timestamp")
    
    # Additional metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional response metadata")
    
    @field_validator("reviewed_by")
    @classmethod
    def validate_reviewed_by(cls, v: str) -> str:
        """Validate reviewer format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Reviewed_by cannot be empty")
        return v.strip()
    
    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: Optional[str]) -> Optional[str]:
        """Validate reason format if provided."""
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
            if len(v) < 5:
                raise ValueError("Reason must be at least 5 characters if provided")
        return v


class ApprovalAuditEntry(BaseModel):
    """
    Audit trail entry for approval workflow events.
    
    This model captures comprehensive audit information for
    approval workflow events including timeouts and errors.
    """
    model_config = ConfigDict(extra="allow")
    
    # Core identifiers
    approval_id: UUID = Field(..., description="Approval request ID")
    event_type: str = Field(..., description="Type of audit event")
    
    # Event details
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    actor: Optional[str] = Field(None, description="Who/what triggered the event")
    details: Dict[str, Any] = Field(default_factory=dict, description="Event-specific details")
    
    # Context preservation
    original_request: Optional[ApprovalRequest] = Field(None, description="Original request data")
    response_data: Optional[ApprovalResponse] = Field(None, description="Response data if applicable")
    
    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """Validate event type format."""
        valid_types = [
            "request_created", "request_published", "response_received",
            "timeout_occurred", "error_encountered", "request_cancelled"
        ]
        if v not in valid_types:
            raise ValueError(f"Event type must be one of: {', '.join(valid_types)}")
        return v
"""
NATS-specific exceptions for the approval workflow system.

This module defines custom exceptions for NATS messaging operations,
approval workflow errors, and connection management issues.
"""

from typing import Optional, Dict, Any


class NATSConnectionError(Exception):
    """NATS connection or client configuration error."""
    
    def __init__(
        self, 
        message: str, 
        connection_url: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.connection_url = connection_url
        self.details = details or {}
    
    def __str__(self) -> str:
        if self.connection_url:
            return f"{super().__str__()} (URL: {self.connection_url})"
        return super().__str__()


class ApprovalTimeoutError(Exception):
    """Approval request timed out waiting for human response."""
    
    def __init__(
        self, 
        approval_id: str, 
        timeout_seconds: int,
        message: Optional[str] = None
    ):
        self.approval_id = approval_id
        self.timeout_seconds = timeout_seconds
        default_message = f"Approval request {approval_id} timed out after {timeout_seconds} seconds"
        super().__init__(message or default_message)


class ApprovalRejectedError(Exception):
    """Approval request was explicitly rejected by human reviewer."""
    
    def __init__(
        self, 
        approval_id: str, 
        rejected_by: str,
        reason: Optional[str] = None
    ):
        self.approval_id = approval_id
        self.rejected_by = rejected_by
        self.reason = reason
        message = f"Approval request {approval_id} rejected by {rejected_by}"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class InvalidApprovalPayloadError(Exception):
    """Approval message payload validation failed."""
    
    def __init__(
        self, 
        message: str, 
        payload: Optional[Dict[str, Any]] = None,
        validation_errors: Optional[list] = None
    ):
        super().__init__(message)
        self.payload = payload
        self.validation_errors = validation_errors or []


class JetStreamConfigError(Exception):
    """JetStream stream configuration or management error."""
    
    def __init__(
        self, 
        message: str, 
        stream_name: Optional[str] = None,
        config_details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.stream_name = stream_name
        self.config_details = config_details or {}


class ApprovalReplyError(Exception):
    """Error occurred while processing approval reply."""
    
    def __init__(
        self, 
        message: str, 
        subject: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(message)
        self.subject = subject
        self.original_error = original_error


class StreamNotFoundError(Exception):
    """Required JetStream stream does not exist."""
    
    def __init__(self, stream_name: str):
        self.stream_name = stream_name
        super().__init__(f"JetStream stream '{stream_name}' not found")


class SubjectPermissionError(Exception):
    """Insufficient permissions for NATS subject operation."""
    
    def __init__(self, subject: str, operation: str):
        self.subject = subject
        self.operation = operation
        super().__init__(f"Permission denied for {operation} on subject '{subject}'")
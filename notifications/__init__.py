"""
NATS Approval Workflow Infrastructure

This package provides the core approval workflow infrastructure using NATS messaging.
It implements a request-reply pattern for human approval gates with JetStream persistence.

Key Components:
    - ApprovalPublisher: Publishes approval requests to NATS subjects
    - ApprovalSubscriber: Handles approval responses and outcomes
    - Approval models: Pydantic models for approval message structure
    - NATS utilities: Connection management and stream configuration

Usage:
    from notifications import ApprovalPublisher, ApprovalSubscriber
    from notifications.models import ApprovalRequest, ApprovalResponse
    
    # Publishing approval requests
    publisher = ApprovalPublisher()
    await publisher.request_approval(...)
    
    # Handling approval responses
    subscriber = ApprovalSubscriber()
    await subscriber.start_listening()

Safety Note:
    This is a critical safety mechanism. All automated actions that could modify
    websites must go through this approval gate with human oversight.
"""

from .exceptions import (
    NATSConnectionError,
    ApprovalTimeoutError,
    ApprovalRejectedError,
    InvalidApprovalPayloadError,
)
from .models import (
    ApprovalType,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalOutcome,
)
from .publisher import ApprovalPublisher
from .subscriber import ApprovalSubscriber
from .utils import NATSConnection, create_jetstream_streams

__all__ = [
    # Exceptions
    "NATSConnectionError",
    "ApprovalTimeoutError",
    "ApprovalRejectedError",
    "InvalidApprovalPayloadError",
    # Models
    "ApprovalType",
    "ApprovalPriority",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalOutcome",
    # Core classes
    "ApprovalPublisher",
    "ApprovalSubscriber",
    # Utilities
    "NATSConnection",
    "create_jetstream_streams",
]
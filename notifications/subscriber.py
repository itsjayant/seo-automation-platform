"""
NATS approval subscriber for handling approval responses.

This module provides the ApprovalSubscriber class for subscribing to approval
response subjects and processing approval outcomes from human reviewers.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import structlog
from nats.aio.msg import Msg
from sqlalchemy.orm import Session

from config import get_settings
from db.connection import get_sync_session
from db.models import AuditLog, ApprovalStatus
from .exceptions import (
    InvalidApprovalPayloadError,
    NATSConnectionError,
    StreamNotFoundError,
)
from .models import (
    ApprovalResponse,
    ApprovalOutcome,
    ApprovalAuditEntry,
)
from .utils import (
    get_nats_connection,
    create_approval_consumer,
)

logger = structlog.get_logger(__name__)


class ApprovalSubscriber:
    """
    Subscriber for NATS approval workflow responses.
    
    This class handles subscribing to approval response subjects, processing
    approval outcomes, and triggering appropriate callback functions for
    approved, rejected, or timed-out approval requests.
    """
    
    def __init__(self, connection_name: str = "approval-subscriber"):
        self.settings = get_settings()
        self.connection_name = connection_name
        self._running = False
        self._subscriptions: List[Any] = []
        self._approval_handlers: Dict[ApprovalOutcome, List[Callable]] = {
            ApprovalOutcome.APPROVED: [],
            ApprovalOutcome.REJECTED: [],
            ApprovalOutcome.TIMEOUT: [],
        }
    
    def register_handler(
        self,
        outcome: ApprovalOutcome,
        handler: Callable[[ApprovalResponse], None]
    ) -> None:
        """
        Register a handler for specific approval outcomes.
        
        Args:
            outcome: The approval outcome to handle
            handler: Async function to call when outcome occurs
        """
        if outcome not in self._approval_handlers:
            self._approval_handlers[outcome] = []
        
        self._approval_handlers[outcome].append(handler)
        logger.info(
            "Registered approval handler",
            outcome=outcome.value,
            handler=handler.__name__
        )
    
    async def start_listening(self) -> None:
        """
        Start listening for approval responses.
        
        This method establishes NATS connections and subscribes to all
        approval response subjects. It runs indefinitely until stopped.
        
        Raises:
            NATSConnectionError: If connection or subscription fails
        """
        if self._running:
            logger.warning("Approval subscriber is already running")
            return
        
        self._running = True
        
        try:
            async with get_nats_connection(self.connection_name) as conn:
                client = await conn.connect()
                jetstream = conn.jetstream
                
                if not jetstream:
                    raise NATSConnectionError("JetStream not available")
                
                # Subscribe to approval response subjects
                await self._setup_subscriptions(jetstream)
                
                logger.info("Approval subscriber started successfully")
                
                # Keep running until stopped
                while self._running:
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.error(
                "Approval subscriber failed",
                error=str(e)
            )
            raise NATSConnectionError(f"Failed to start approval subscriber: {e}")
        finally:
            await self._cleanup_subscriptions()
            logger.info("Approval subscriber stopped")
    
    async def stop_listening(self) -> None:
        """Stop listening for approval responses."""
        self._running = False
        await self._cleanup_subscriptions()
    
    async def _setup_subscriptions(self, jetstream) -> None:
        """Setup JetStream subscriptions for approval responses."""
        try:
            # Create consumer for approval responses
            consumer_name = await create_approval_consumer(
                js=jetstream,
                stream_name=self.settings.nats.stream_approval,
                consumer_name=f"approval-responses-{self.connection_name}",
                filter_subject=f"{self.settings.nats.approval_subjects_prefix}.responses.*",
                durable=True
            )
            
            # Subscribe to the consumer
            subscription = await jetstream.pull_subscribe(
                subject=f"{self.settings.nats.approval_subjects_prefix}.responses.*",
                durable=consumer_name,
            )
            
            self._subscriptions.append(subscription)
            
            # Start processing messages
            asyncio.create_task(self._process_messages(subscription))
            
            logger.info(
                "Setup approval response subscription",
                consumer=consumer_name,
                subject=f"{self.settings.nats.approval_subjects_prefix}.responses.*"
            )
            
        except Exception as e:
            logger.error(
                "Failed to setup approval subscriptions",
                error=str(e)
            )
            raise
    
    async def _process_messages(self, subscription) -> None:
        """Process incoming approval response messages."""
        logger.info("Started processing approval response messages")
        
        while self._running:
            try:
                # Fetch messages from the subscription
                messages = await subscription.fetch(
                    batch=10,
                    timeout=5.0
                )
                
                for msg in messages:
                    await self._handle_approval_response(msg)
                    
            except asyncio.TimeoutError:
                # Normal timeout, continue processing
                continue
            except Exception as e:
                logger.error(
                    "Error processing approval messages",
                    error=str(e)
                )
                await asyncio.sleep(1)  # Brief pause before retrying
    
    async def _handle_approval_response(self, msg: Msg) -> None:
        """Handle a single approval response message."""
        try:
            # Parse message payload
            try:
                payload = json.loads(msg.data.decode())
                response = ApprovalResponse.model_validate(payload)
            except Exception as e:
                logger.error(
                    "Invalid approval response format",
                    subject=msg.subject,
                    error=str(e),
                    payload=msg.data.decode()[:200]
                )
                await msg.nak()  # Negative acknowledge
                return
            
            logger.info(
                "Processing approval response",
                approval_id=str(response.approval_id),
                outcome=response.outcome.value,
                reviewed_by=response.reviewed_by
            )
            
            # Update audit log
            await self._update_audit_log(response)
            
            # Create audit entry for the response
            await self._create_response_audit_entry(response, msg.subject)
            
            # Trigger registered handlers
            await self._trigger_handlers(response)
            
            # Acknowledge message processing
            await msg.ack()
            
            logger.info(
                "Successfully processed approval response",
                approval_id=str(response.approval_id),
                outcome=response.outcome.value
            )
            
        except Exception as e:
            logger.error(
                "Failed to handle approval response",
                subject=msg.subject,
                error=str(e)
            )
            # Negative acknowledge to retry later
            await msg.nak()
    
    async def _update_audit_log(self, response: ApprovalResponse) -> None:
        """Update the original audit log entry with the approval response."""
        try:
            with get_sync_session() as session:
                # Find the original audit entry
                audit_entry = session.query(AuditLog).filter(
                    AuditLog.request_data.op('->>')('approval_id') == str(response.approval_id)
                ).first()
                
                if not audit_entry:
                    logger.warning(
                        "No audit entry found for approval response",
                        approval_id=str(response.approval_id)
                    )
                    return
                
                # Update approval status
                if response.outcome == ApprovalOutcome.APPROVED:
                    audit_entry.approval_status = ApprovalStatus.APPROVED
                elif response.outcome == ApprovalOutcome.REJECTED:
                    audit_entry.approval_status = ApprovalStatus.REJECTED
                    audit_entry.success = False
                    audit_entry.error_message = f"Approval rejected: {response.reason}"
                elif response.outcome == ApprovalOutcome.TIMEOUT:
                    audit_entry.approval_status = ApprovalStatus.TIMEOUT
                    audit_entry.success = False
                    audit_entry.error_message = "Approval request timed out"
                
                # Set approval details
                audit_entry.approved_by = response.reviewed_by
                audit_entry.approved_at = response.reviewed_at
                audit_entry.response_data = response.model_dump(mode='json')
                
                session.commit()
                
                logger.debug(
                    "Updated audit entry for approval response",
                    audit_id=str(audit_entry.id),
                    approval_id=str(response.approval_id),
                    status=audit_entry.approval_status.value
                )
                
        except Exception as e:
            logger.error(
                "Failed to update audit log",
                approval_id=str(response.approval_id),
                error=str(e)
            )
            # Don't re-raise to avoid breaking message processing
    
    async def _create_response_audit_entry(
        self, 
        response: ApprovalResponse, 
        subject: str
    ) -> None:
        """Create a separate audit entry for the response event."""
        try:
            audit_entry = ApprovalAuditEntry(
                approval_id=response.approval_id,
                event_type="response_received",
                actor=response.reviewed_by,
                details={
                    "outcome": response.outcome.value,
                    "reason": response.reason,
                    "conditions": response.conditions,
                    "subject": subject,
                },
                response_data=response,
            )
            
            logger.debug(
                "Created response audit entry",
                approval_id=str(response.approval_id),
                event_type=audit_entry.event_type
            )
            
        except Exception as e:
            logger.error(
                "Failed to create response audit entry",
                approval_id=str(response.approval_id),
                error=str(e)
            )
    
    async def _trigger_handlers(self, response: ApprovalResponse) -> None:
        """Trigger registered handlers for the approval outcome."""
        handlers = self._approval_handlers.get(response.outcome, [])
        
        if not handlers:
            logger.debug(
                "No handlers registered for outcome",
                outcome=response.outcome.value,
                approval_id=str(response.approval_id)
            )
            return
        
        # Execute handlers concurrently
        tasks = []
        for handler in handlers:
            task = asyncio.create_task(
                self._safe_execute_handler(handler, response)
            )
            tasks.append(task)
        
        # Wait for all handlers to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _safe_execute_handler(
        self, 
        handler: Callable, 
        response: ApprovalResponse
    ) -> None:
        """Safely execute a handler function with error isolation."""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(response)
            else:
                handler(response)
                
            logger.debug(
                "Executed approval handler",
                handler=handler.__name__,
                approval_id=str(response.approval_id),
                outcome=response.outcome.value
            )
            
        except Exception as e:
            logger.error(
                "Handler execution failed",
                handler=handler.__name__,
                approval_id=str(response.approval_id),
                error=str(e)
            )
            # Don't re-raise to avoid breaking other handlers
    
    async def _cleanup_subscriptions(self) -> None:
        """Cleanup active NATS subscriptions."""
        for subscription in self._subscriptions:
            try:
                await subscription.unsubscribe()
            except Exception as e:
                logger.warning(
                    "Error unsubscribing from approval responses",
                    error=str(e)
                )
        
        self._subscriptions.clear()
        logger.debug("Cleaned up approval subscriptions")
    
    async def publish_response(
        self,
        approval_id: uuid.UUID,
        outcome: ApprovalOutcome,
        reviewed_by: str,
        reason: Optional[str] = None,
        conditions: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        Publish an approval response (typically called by web dashboard).
        
        Args:
            approval_id: ID of the original approval request
            outcome: The approval decision
            reviewed_by: User who made the decision
            reason: Optional reason for the decision
            conditions: Optional conditions attached to approval
            correlation_id: Optional correlation ID from original request
            
        Raises:
            NATSConnectionError: If publishing fails
        """
        try:
            response = ApprovalResponse(
                approval_id=approval_id,
                correlation_id=correlation_id,
                outcome=outcome,
                reason=reason,
                conditions=conditions or [],
                reviewed_by=reviewed_by,
                reviewed_at=datetime.now(timezone.utc),
            )
            
            async with get_nats_connection(f"{self.connection_name}-publisher") as conn:
                client = await conn.connect()
                
                # Format response subject
                response_subject = f"{self.settings.nats.approval_subjects_prefix}.responses.{approval_id}"
                
                # Publish response
                await client.publish(
                    subject=response_subject,
                    payload=json.dumps(response.model_dump(mode='json'), default=str).encode()
                )
                
                logger.info(
                    "Published approval response",
                    approval_id=str(approval_id),
                    outcome=outcome.value,
                    reviewed_by=reviewed_by,
                    subject=response_subject
                )
                
        except Exception as e:
            logger.error(
                "Failed to publish approval response",
                approval_id=str(approval_id),
                error=str(e)
            )
            raise NATSConnectionError(f"Failed to publish approval response: {e}")
    
    def get_registered_handlers(self) -> Dict[str, List[str]]:
        """Get list of registered handlers by outcome."""
        return {
            outcome.value: [handler.__name__ for handler in handlers]
            for outcome, handlers in self._approval_handlers.items()
        }
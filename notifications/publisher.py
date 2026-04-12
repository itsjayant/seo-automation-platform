"""
NATS approval publisher for sending approval requests.

This module provides the ApprovalPublisher class for publishing approval requests
to NATS subjects with request-reply pattern support and timeout handling.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import structlog
from sqlalchemy.orm import Session

from config import get_settings
from db.connection import get_sync_session
from db.models import AuditLog, ActionType, EntityType, ApprovalStatus
from .exceptions import (
    ApprovalTimeoutError,
    ApprovalRejectedError,
    InvalidApprovalPayloadError,
    NATSConnectionError,
)
from .models import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalType,
    ApprovalPriority,
    ApprovalOutcome,
    EntityReference,
)
from .utils import (
    get_nats_connection,
    format_approval_subject,
    format_response_subject,
    publish_json_message,
)

logger = structlog.get_logger(__name__)


class ApprovalPublisher:
    """
    Publisher for NATS approval workflow requests.
    
    This class handles publishing approval requests to appropriate NATS subjects,
    managing request-reply patterns, and integrating with the audit log system.
    """
    
    def __init__(self, connection_name: str = "approval-publisher"):
        self.settings = get_settings()
        self.connection_name = connection_name
        
    async def request_approval(
        self,
        approval_type: ApprovalType,
        action: str,
        entity: EntityReference,
        description: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        changes: Optional[Dict[str, Any]] = None,
        risks: Optional[List[str]] = None,
        priority: ApprovalPriority = ApprovalPriority.MEDIUM,
        timeout_seconds: int = 300,
        requested_by: str,
        correlation_id: Optional[str] = None,
        wait_for_response: bool = True,
    ) -> Union[ApprovalResponse, ApprovalRequest]:
        """
        Request human approval for an automated action.
        
        Args:
            approval_type: Type of approval required (content, technical, publish)
            action: Specific action requiring approval
            entity: Entity reference (site, post, etc.)
            description: Human-readable description
            details: Additional context details
            changes: Proposed changes to be made
            risks: List of identified risks
            priority: Priority level for the request
            timeout_seconds: How long to wait for approval
            requested_by: Agent or system requesting approval
            correlation_id: Optional correlation ID for tracking
            wait_for_response: Whether to wait for human response
            
        Returns:
            ApprovalResponse if wait_for_response=True, otherwise ApprovalRequest
            
        Raises:
            ApprovalTimeoutError: If approval times out
            ApprovalRejectedError: If approval is rejected
            NATSConnectionError: If NATS communication fails
            InvalidApprovalPayloadError: If request validation fails
        """
        # Validate inputs
        if self.settings.development.skip_approval_gate:
            logger.warning(
                "Skipping approval gate due to development setting",
                action=action,
                requested_by=requested_by
            )
            # Create mock approval response for development
            return ApprovalResponse(
                approval_id=uuid.uuid4(),
                correlation_id=correlation_id,
                outcome=ApprovalOutcome.APPROVED,
                reason="Development mode - approval gate bypassed",
                reviewed_by="system",
                reviewed_at=datetime.now(timezone.utc),
            )
        
        # Create approval request
        try:
            request = ApprovalRequest(
                correlation_id=correlation_id,
                approval_type=approval_type,
                priority=priority,
                action=action,
                description=description,
                entity=entity,
                details=details or {},
                changes=changes,
                risks=risks or [],
                requested_by=requested_by,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            raise InvalidApprovalPayloadError(
                f"Invalid approval request data: {e}",
                payload={
                    "approval_type": approval_type,
                    "action": action,
                    "entity": entity.model_dump() if hasattr(entity, 'model_dump') else entity,
                    "description": description,
                }
            )
        
        # Create audit log entry
        audit_entry = self._create_audit_entry(request)
        
        # Publish approval request
        async with get_nats_connection(self.connection_name) as conn:
            client = await conn.connect()
            
            # Format NATS subject
            subject = format_approval_subject(
                approval_type=approval_type.value,
                action=action,
                site_id=entity.site_id
            )
            
            if wait_for_response:
                # Use request-reply pattern
                response = await self._request_with_reply(
                    client=client,
                    subject=subject,
                    request=request,
                    audit_entry=audit_entry,
                )
                return response
            else:
                # Fire and forget
                await self._publish_request(
                    client=client,
                    subject=subject,
                    request=request,
                    audit_entry=audit_entry,
                )
                return request
    
    async def _request_with_reply(
        self,
        client,
        subject: str,
        request: ApprovalRequest,
        audit_entry: AuditLog,
    ) -> ApprovalResponse:
        """Handle request-reply pattern for approval."""
        # Configure reply subject
        reply_subject = format_response_subject(str(request.approval_id))
        request_data = request.model_dump(mode='json')
        request_data['reply_subject'] = reply_subject
        
        try:
            logger.info(
                "Publishing approval request with reply",
                approval_id=str(request.approval_id),
                subject=subject,
                reply_subject=reply_subject,
                timeout=request.timeout_seconds
            )
            
            # Publish request and wait for reply
            response_msg = await client.request(
                subject=subject,
                payload=json.dumps(request_data, default=str).encode(),
                timeout=request.timeout_seconds,
            )
            
            # Parse response
            try:
                response_data = json.loads(response_msg.data.decode())
                response = ApprovalResponse.model_validate(response_data)
            except Exception as e:
                raise InvalidApprovalPayloadError(
                    f"Invalid approval response format: {e}",
                    payload=response_data if 'response_data' in locals() else None
                )
            
            # Update audit log
            audit_entry.approval_status = ApprovalStatus[response.outcome.value.upper()]
            audit_entry.approved_by = response.reviewed_by
            audit_entry.approved_at = response.reviewed_at
            audit_entry.response_data = response.model_dump(mode='json')
            
            if response.outcome == ApprovalOutcome.REJECTED:
                audit_entry.success = False
                audit_entry.error_message = f"Approval rejected: {response.reason}"
                
                self._save_audit_entry(audit_entry)
                raise ApprovalRejectedError(
                    approval_id=str(request.approval_id),
                    rejected_by=response.reviewed_by,
                    reason=response.reason,
                )
            
            self._save_audit_entry(audit_entry)
            
            logger.info(
                "Approval request completed",
                approval_id=str(request.approval_id),
                outcome=response.outcome.value,
                reviewed_by=response.reviewed_by
            )
            
            return response
            
        except asyncio.TimeoutError:
            # Handle timeout
            audit_entry.approval_status = ApprovalStatus.TIMEOUT
            audit_entry.success = False
            audit_entry.error_message = f"Approval timed out after {request.timeout_seconds} seconds"
            self._save_audit_entry(audit_entry)
            
            logger.warning(
                "Approval request timed out",
                approval_id=str(request.approval_id),
                timeout_seconds=request.timeout_seconds
            )
            
            raise ApprovalTimeoutError(
                approval_id=str(request.approval_id),
                timeout_seconds=request.timeout_seconds,
            )
            
        except Exception as e:
            audit_entry.success = False
            audit_entry.error_message = f"NATS communication error: {e}"
            self._save_audit_entry(audit_entry)
            
            logger.error(
                "Approval request failed",
                approval_id=str(request.approval_id),
                error=str(e)
            )
            
            raise NATSConnectionError(f"Approval request failed: {e}")
    
    async def _publish_request(
        self,
        client,
        subject: str,
        request: ApprovalRequest,
        audit_entry: AuditLog,
    ) -> None:
        """Publish approval request without waiting for reply."""
        try:
            await publish_json_message(
                client=client,
                subject=subject,
                data=request.model_dump(mode='json'),
                timeout=5.0,
            )
            
            audit_entry.approval_status = ApprovalStatus.PENDING
            self._save_audit_entry(audit_entry)
            
            logger.info(
                "Published approval request",
                approval_id=str(request.approval_id),
                subject=subject
            )
            
        except Exception as e:
            audit_entry.success = False
            audit_entry.error_message = f"Failed to publish approval request: {e}"
            self._save_audit_entry(audit_entry)
            raise
    
    def _create_audit_entry(self, request: ApprovalRequest) -> AuditLog:
        """Create audit log entry for approval request."""
        # Map approval types to action types
        APPROVAL_TO_ACTION_TYPE = {
            ApprovalType.CONTENT_PUBLISH: ActionType.CONTENT_PUBLISH,
            ApprovalType.CONTENT_UPDATE: ActionType.CONTENT_GENERATION,
            ApprovalType.KEYWORD_OPTIMIZATION: ActionType.KEYWORD_RESEARCH,
            ApprovalType.SITE_CONFIGURATION: ActionType.SITE_OPTIMIZATION,
        }
        
        action_type = APPROVAL_TO_ACTION_TYPE.get(request.approval_type, ActionType.CONTENT_GENERATION)
        
        return AuditLog(
            action_type=action_type,
            entity_type=EntityType[request.entity.entity_type.upper()],
            entity_id=request.entity.entity_id,
            description=f"Approval request: {request.description}",
            changes=request.changes,
            user_context={
                "requested_by": request.requested_by,
                "approval_type": request.approval_type.value,
                "priority": request.priority.value,
            },
            request_data=request.model_dump(mode='json'),
            requires_approval=True,
            approval_status=ApprovalStatus.PENDING,
        )
    
    def _save_audit_entry(self, audit_entry: AuditLog) -> None:
        """Save audit entry to database."""
        try:
            with get_sync_session() as session:
                session.add(audit_entry)
                session.commit()
                logger.debug(
                    "Saved audit entry",
                    audit_id=str(audit_entry.id),
                    action_type=audit_entry.action_type.value
                )
        except Exception as e:
            logger.error(
                "Failed to save audit entry",
                error=str(e),
                audit_data=audit_entry.__dict__
            )
            # Don't raise here to avoid breaking the approval flow
    
    async def cancel_approval(self, approval_id: Union[str, uuid.UUID]) -> bool:
        """
        Cancel a pending approval request.
        
        Args:
            approval_id: ID of the approval to cancel
            
        Returns:
            True if cancellation was successful
            
        Raises:
            NATSConnectionError: If NATS communication fails
        """
        approval_id_str = str(approval_id)
        
        try:
            # Update audit log to mark as cancelled
            with get_sync_session() as session:
                audit_entry = session.query(AuditLog).filter(
                    AuditLog.request_data.op('->>')('approval_id') == approval_id_str
                ).first()
                
                if audit_entry and audit_entry.approval_status == ApprovalStatus.PENDING:
                    audit_entry.approval_status = ApprovalStatus.TIMEOUT  # Using TIMEOUT as proxy for cancelled
                    audit_entry.success = False
                    audit_entry.error_message = "Approval request cancelled"
                    session.commit()
                    
                    logger.info(
                        "Cancelled approval request",
                        approval_id=approval_id_str
                    )
                    return True
                
                return False
                
        except Exception as e:
            logger.error(
                "Failed to cancel approval",
                approval_id=approval_id_str,
                error=str(e)
            )
            raise NATSConnectionError(f"Failed to cancel approval {approval_id_str}: {e}")
    
    async def get_pending_approvals(
        self, 
        approval_type: Optional[ApprovalType] = None,
        site_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get list of pending approval requests.
        
        Args:
            approval_type: Filter by approval type
            site_id: Filter by site ID
            
        Returns:
            List of pending approval request data
        """
        try:
            with get_sync_session() as session:
                query = session.query(AuditLog).filter(
                    AuditLog.requires_approval == True,
                    AuditLog.approval_status == ApprovalStatus.PENDING
                )
                
                if approval_type:
                    query = query.filter(
                        AuditLog.user_context.op('->>')('approval_type') == approval_type.value
                    )
                
                if site_id:
                    query = query.filter(
                        AuditLog.request_data.op('->>')('entity').op('->>')('site_id') == str(site_id)
                    )
                
                audit_entries = query.order_by(AuditLog.created_at.desc()).all()
                
                pending_approvals = []
                for entry in audit_entries:
                    pending_approvals.append({
                        "audit_id": str(entry.id),
                        "approval_id": entry.request_data.get("approval_id"),
                        "action": entry.request_data.get("action"),
                        "description": entry.description,
                        "requested_by": entry.request_data.get("requested_by"),
                        "requested_at": entry.created_at.isoformat(),
                        "priority": entry.user_context.get("priority"),
                        "approval_type": entry.user_context.get("approval_type"),
                    })
                
                return pending_approvals
                
        except Exception as e:
            logger.error("Failed to get pending approvals", error=str(e))
            raise NATSConnectionError(f"Failed to get pending approvals: {e}")
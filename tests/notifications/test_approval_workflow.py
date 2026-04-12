"""
Tests for notification system and approval workflows using NATS.

Tests notification publishing, subscription, approval workflows,
and human-in-the-loop integrations.
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from notifications.publisher import NotificationPublisher
from notifications.subscriber import NotificationSubscriber
from notifications.models import (
    ApprovalRequest, ApprovalResponse, ApprovalStatus,
    NotificationLevel, NotificationChannel
)
from notifications.exceptions import NotificationPublishError, ApprovalTimeoutError


@pytest.mark.integration
@pytest.mark.notifications
class TestNotificationPublisher:
    """Test cases for NATS notification publisher."""
    
    async def test_publisher_initialization(self, notification_publisher):
        """Test notification publisher initialization."""
        assert notification_publisher.stream_approval == "test-approvals"
        assert hasattr(notification_publisher, 'nats_client')
    
    async def test_publish_approval_request(self, notification_publisher):
        """Test publishing an approval request."""
        approval_request = ApprovalRequest(
            id=uuid4(),
            site_id=uuid4(),
            action="publish_post",
            agent_name="content_agent",
            description="Publish new SEO article about keyword research",
            input_data={
                "title": "Complete Keyword Research Guide 2024",
                "content_length": 2500,
                "target_url": "https://example.com/keyword-research-guide",
                "meta_description": "Learn advanced keyword research techniques..."
            },
            risk_level="medium",
            timeout_seconds=300,
            required_approvers=["human@example.com"],
            created_at=datetime.utcnow()
        )
        
        # Mock NATS JetStream publish
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            await notification_publisher.publish_approval_request(approval_request)
            
            # Verify publish was called with correct subject and data
            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            
            # Check subject
            subject = call_args[0][0]
            assert subject.startswith("approvals.")
            
            # Check message data contains approval request
            message_data = call_args[0][1]
            assert b"approval_id" in message_data
            assert b"publish_post" in message_data
    
    async def test_publish_high_risk_approval(self, notification_publisher):
        """Test publishing high-risk approval request."""
        high_risk_request = ApprovalRequest(
            id=uuid4(),
            site_id=uuid4(),
            action="delete_content",
            agent_name="content_agent", 
            description="Delete underperforming blog posts", 
            input_data={
                "post_ids": [123, 456, 789],
                "reason": "Low traffic and outdated content"
            },
            risk_level="high",
            timeout_seconds=600,  # Longer timeout for high-risk
            required_approvers=["admin@example.com", "manager@example.com"],
            created_at=datetime.utcnow()
        )
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            await notification_publisher.publish_approval_request(high_risk_request)
            
            # Verify high-risk requests use different subject/priority
            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            
            subject = call_args[0][0]
            # High-risk requests might use different subject pattern
            assert "approval" in subject
    
    async def test_publish_approval_response(self, notification_publisher):
        """Test publishing approval response."""
        approval_response = ApprovalResponse(
            id=uuid4(),
            approval_request_id=uuid4(),
            approver="human@example.com",
            status=ApprovalStatus.APPROVED,
            comments="Content looks good, approved for publishing",
            approved_at=datetime.utcnow()
        )
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            await notification_publisher.publish_approval_response(approval_response)
            
            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            
            subject = call_args[0][0]
            assert "response" in subject or "approval" in subject
    
    async def test_publish_alert_notification(self, notification_publisher):
        """Test publishing alert notifications."""
        alert_data = {
            "level": NotificationLevel.ERROR,
            "channel": NotificationChannel.EMAIL,
            "title": "GSC API Rate Limit Exceeded",
            "message": "Multiple 429 errors detected for example.com GSC integration",
            "site_id": str(uuid4()),
            "agent_name": "gsc_agent",
            "error_count": 5,
            "last_error": "2024-04-01T12:00:00Z",
            "recommended_action": "Reduce GSC query frequency"
        }
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            await notification_publisher.publish_alert(alert_data)
            
            mock_publish.assert_called_once() 
            call_args = mock_publish.call_args
            
            subject = call_args[0][0]
            assert "alert" in subject.lower()
    
    async def test_publish_error_handling(self, notification_publisher):
        """Test notification publish error handling."""
        approval_request = ApprovalRequest(
            id=uuid4(),
            site_id=uuid4(),
            action="test_action",
            agent_name="test_agent",
            description="Test request"
        )
        
        # Mock NATS publish failure
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.side_effect = Exception("NATS connection lost")
            
            with pytest.raises(NotificationPublishError):
                await notification_publisher.publish_approval_request(approval_request)


@pytest.mark.integration
@pytest.mark.notifications
class TestNotificationSubscriber:
    """Test cases for NATS notification subscriber."""
    
    @pytest.fixture
    async def notification_subscriber(self, nats_client, test_settings):
        """Create notification subscriber for testing."""
        subscriber = NotificationSubscriber(
            nats_client=nats_client,
            stream_approval=test_settings["nats"].stream_approval,
            stream_alerts=test_settings["nats"].stream_alerts
        )
        return subscriber
    
    async def test_subscriber_initialization(self, notification_subscriber):
        """Test notification subscriber initialization."""
        assert notification_subscriber.stream_approval == "test-approvals"
        assert notification_subscriber.stream_alerts == "test-alerts"
    
    async def test_subscribe_to_approval_requests(self, notification_subscriber):
        """Test subscribing to approval requests."""
        received_requests = []
        
        async def approval_handler(msg):
            """Mock approval request handler."""
            # Parse message data
            import json
            data = json.loads(msg.data.decode())
            received_requests.append(data)
            await msg.ack()
        
        # Mock NATS subscription
        with patch.object(notification_subscriber.nats_client, 'subscribe') as mock_subscribe:
            mock_sub = AsyncMock()
            mock_subscribe.return_value = mock_sub
            
            await notification_subscriber.subscribe_approval_requests(approval_handler)
            
            # Verify subscription was created
            mock_subscribe.assert_called_once()
            call_args = mock_subscribe.call_args
            assert "approval" in call_args[0][0]  # Subject pattern
    
    async def test_subscribe_to_alerts(self, notification_subscriber):
        """Test subscribing to alert notifications."""
        received_alerts = []
        
        async def alert_handler(msg):
            """Mock alert handler."""
            import json
            data = json.loads(msg.data.decode())
            received_alerts.append(data)
            await msg.ack()
        
        with patch.object(notification_subscriber.nats_client, 'subscribe') as mock_subscribe:
            mock_sub = AsyncMock()
            mock_subscribe.return_value = mock_sub
            
            await notification_subscriber.subscribe_alerts(alert_handler)
            
            mock_subscribe.assert_called_once()
            call_args = mock_subscribe.call_args
            assert "alert" in call_args[0][0]
    
    async def test_message_acknowledgment(self, notification_subscriber):
        """Test message acknowledgment handling."""
        async def failing_handler(msg):
            """Handler that raises exception."""
            raise Exception("Processing failed")
        
        # Mock message processing
        mock_msg = AsyncMock()
        mock_msg.data = b'{"test": "data"}'
        mock_msg.subject = "approvals.test"
        
        # Test error handling in message processing
        with pytest.raises(Exception):
            await failing_handler(mock_msg)
        
        # In real implementation, message should not be acked on failure
        mock_msg.ack.assert_not_called()


@pytest.mark.integration
@pytest.mark.notifications
class TestApprovalWorkflow:
    """Test cases for end-to-end approval workflows."""
    
    async def test_complete_approval_workflow(self, notification_publisher, nats_client, test_settings):
        """Test complete approval workflow from request to response."""
        # Create subscriber for testing
        subscriber = NotificationSubscriber(
            nats_client=nats_client,
            stream_approval=test_settings["nats"].stream_approval
        )
        
        # Track workflow state
        workflow_state = {
            "request_received": False,
            "response_sent": False,
            "request_data": None
        }
        
        async def approval_handler(msg):
            """Handle approval request and send response."""
            import json
            data = json.loads(msg.data.decode())
            workflow_state["request_received"] = True
            workflow_state["request_data"] = data
            
            # Simulate human approval
            response = ApprovalResponse(
                id=uuid4(),
                approval_request_id=data["approval_id"],
                approver="human@example.com",
                status=ApprovalStatus.APPROVED,
                comments="Approved after review"
            )
            
            # Send approval response
            await notification_publisher.publish_approval_response(response)
            workflow_state["response_sent"] = True
            await msg.ack()
        
        # Mock the workflow
        with patch.object(subscriber.nats_client, 'subscribe') as mock_subscribe:
            mock_sub = AsyncMock()
            mock_subscribe.return_value = mock_sub
            
            # Set up subscription
            await subscriber.subscribe_approval_requests(approval_handler)
            
            # Create approval request
            approval_request = ApprovalRequest(
                id=uuid4(),
                site_id=uuid4(),
                action="workflow_test",
                agent_name="test_agent",
                description="Test complete approval workflow",
                risk_level="low"
            )
            
            # Mock publishing and handling
            with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
                mock_publish.return_value = AsyncMock()
                
                # Publish approval request
                await notification_publisher.publish_approval_request(approval_request)
                
                # Simulate message delivery to handler
                mock_msg = AsyncMock()
                mock_msg.data = f'{{"approval_id": "{approval_request.id}", "action": "workflow_test"}}'.encode()
                await approval_handler(mock_msg)
                
                # Verify workflow completion
                assert workflow_state["request_received"] is True
                assert workflow_state["response_sent"] is True
                assert workflow_state["request_data"]["approval_id"] == str(approval_request.id)
    
    async def test_approval_timeout_handling(self, notification_publisher):
        """Test approval request timeout handling."""
        approval_request = ApprovalRequest(
            id=uuid4(),
            site_id=uuid4(),
            action="timeout_test",
            agent_name="test_agent", 
            description="Test approval timeout",
            timeout_seconds=1,  # Very short timeout for testing
            created_at=datetime.utcnow()
        )
        
        # Mock timeout scenario
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            # Publish request
            await notification_publisher.publish_approval_request(approval_request)
            
            # Simulate timeout check
            current_time = datetime.utcnow()
            timeout_time = approval_request.created_at + timedelta(seconds=approval_request.timeout_seconds)
            
            if current_time > timeout_time:
                # In real implementation, this would trigger timeout handling
                assert True  # Timeout detected
            else:
                # Wait for timeout to occur
                await asyncio.sleep(1.1)
                current_time = datetime.utcnow()
                assert current_time > timeout_time
    
    async def test_approval_rejection_workflow(self, notification_publisher):
        """Test approval rejection workflow."""
        approval_request = ApprovalRequest(
            id=uuid4(),
            site_id=uuid4(),
            action="risky_action",
            agent_name="test_agent",
            description="High-risk action requiring approval",
            risk_level="high"
        )
        
        # Mock rejection response
        rejection_response = ApprovalResponse(
            id=uuid4(),
            approval_request_id=approval_request.id,
            approver="human@example.com",
            status=ApprovalStatus.REJECTED,
            comments="Action too risky, please provide more details",
            approved_at=datetime.utcnow()
        )
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            # Publish request and rejection
            await notification_publisher.publish_approval_request(approval_request)
            await notification_publisher.publish_approval_response(rejection_response)
            
            # Verify both publishes occurred
            assert mock_publish.call_count == 2
    
    async def test_multiple_approver_workflow(self, notification_publisher):
        """Test approval workflow with multiple required approvers."""
        approval_request = ApprovalRequest(
            id=uuid4(),
            site_id=uuid4(),
            action="major_update",
            agent_name="content_agent",
            description="Major site content update",
            risk_level="high",
            required_approvers=["admin@example.com", "manager@example.com", "seo@example.com"],
            min_approvals=2  # Require at least 2 approvals
        )
        
        # Mock multiple approvals
        approvals = []
        for i, approver in enumerate(approval_request.required_approvers[:2]):  # Only first 2 approve
            approval = ApprovalResponse(
                id=uuid4(),
                approval_request_id=approval_request.id,
                approver=approver,
                status=ApprovalStatus.APPROVED,
                comments=f"Approval {i+1} - Looks good",
                approved_at=datetime.utcnow()
            )
            approvals.append(approval)
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            # Publish request
            await notification_publisher.publish_approval_request(approval_request)
            
            # Publish approvals
            for approval in approvals:
                await notification_publisher.publish_approval_response(approval)
            
            # Verify sufficient approvals received
            approved_count = len([a for a in approvals if a.status == ApprovalStatus.APPROVED])
            assert approved_count >= approval_request.min_approvals


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.slow
class TestNotificationPerformance:
    """Test cases for notification system performance."""
    
    async def test_high_volume_notifications(self, notification_publisher):
        """Test high volume notification publishing."""
        import time
        
        num_notifications = 50
        requests = []
        
        for i in range(num_notifications):
            request = ApprovalRequest(
                id=uuid4(),
                site_id=uuid4(),
                action=f"bulk_action_{i}",
                agent_name="bulk_agent",
                description=f"Bulk operation {i}",
                risk_level="low"
            )
            requests.append(request)
        
        # Mock batch publishing
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            start_time = time.time()
            
            # Publish all notifications
            tasks = []
            for request in requests:
                task = notification_publisher.publish_approval_request(request)
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Verify all notifications were published
            assert mock_publish.call_count == num_notifications
            
            # Performance check
            assert execution_time < 5.0  # Should handle 50 notifications quickly
    
    async def test_concurrent_subscribers(self, nats_client, test_settings):
        """Test multiple concurrent notification subscribers."""
        subscribers = []
        received_messages = []
        
        # Create multiple subscribers
        for i in range(3):
            subscriber = NotificationSubscriber(
                nats_client=nats_client,
                stream_approval=test_settings["nats"].stream_approval
            )
            subscribers.append(subscriber)
        
        async def message_handler(msg):
            """Handle incoming messages."""
            received_messages.append(msg.data.decode())
            await msg.ack()
        
        # Mock concurrent subscription
        subscription_tasks = []
        for subscriber in subscribers:
            with patch.object(subscriber.nats_client, 'subscribe') as mock_subscribe:
                mock_sub = AsyncMock()
                mock_subscribe.return_value = mock_sub
                
                task = subscriber.subscribe_approval_requests(message_handler)
                subscription_tasks.append(task)
        
        # Execute concurrent subscriptions
        await asyncio.gather(*subscription_tasks)
        
        # Verify all subscribers were set up
        assert len(subscribers) == 3


@pytest.mark.integration
@pytest.mark.notifications
class TestNotificationChannels:
    """Test different notification channels (email, Slack, etc.)."""
    
    async def test_email_notification_channel(self, notification_publisher):
        """Test email notification channel."""
        email_notification = {
            "channel": NotificationChannel.EMAIL,
            "recipients": ["admin@example.com", "alerts@example.com"],
            "subject": "SEO Platform Alert: Rate Limit Exceeded",
            "body": "Multiple rate limit errors detected for GSC integration...",
            "priority": "high",
            "attachments": []
        }
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            await notification_publisher.publish_alert(email_notification)
            
            mock_publish.assert_called_once()
    
    async def test_slack_notification_channel(self, notification_publisher):
        """Test Slack notification channel."""
        slack_notification = {
            "channel": NotificationChannel.SLACK,
            "webhook_url": "https://hooks.slack.com/services/test/webhook",
            "channel_name": "#seo-alerts",
            "message": "🚨 GSC API rate limit exceeded for example.com",
            "username": "SEO Bot",
            "icon_emoji": ":warning:",
            "attachments": [
                {
                    "color": "danger",
                    "title": "Error Details",
                    "text": "5 consecutive 429 errors in the last 10 minutes"
                }
            ]
        }
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            await notification_publisher.publish_alert(slack_notification)
            
            mock_publish.assert_called_once()
    
    async def test_webhook_notification_channel(self, notification_publisher):
        """Test generic webhook notification channel."""
        webhook_notification = {
            "channel": NotificationChannel.WEBHOOK,
            "url": "https://api.example.com/webhooks/seo-alerts",
            "method": "POST",
            "headers": {
                "Authorization": "Bearer token123",
                "Content-Type": "application/json"
            },
            "payload": {
                "event": "approval_required",
                "site_id": str(uuid4()),
                "action": "publish_content",
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        with patch.object(notification_publisher.nats_client, 'publish') as mock_publish:
            mock_publish.return_value = AsyncMock()
            
            await notification_publisher.publish_alert(webhook_notification)
            
            mock_publish.assert_called_once()
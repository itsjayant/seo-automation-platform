"""
NATS utilities for connection management and stream configuration.

This module provides utilities for managing NATS connections, configuring
JetStream streams, and handling common NATS operations for the approval workflow.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

import nats
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, StreamConfig, RetentionPolicy, StorageType
import structlog

from config import get_settings
from .exceptions import (
    NATSConnectionError,
    JetStreamConfigError,
    StreamNotFoundError,
)

logger = structlog.get_logger(__name__)


class NATSConnection:
    """
    Manages NATS connections with automatic reconnection and error handling.
    
    This class provides a centralized way to manage NATS connections,
    handle reconnections, and ensure proper cleanup of resources.
    """
    
    def __init__(self, connection_name: str = "approval-workflow"):
        self.settings = get_settings()
        self.connection_name = connection_name
        self._client: Optional[NATSClient] = None
        self._jetstream: Optional[JetStreamContext] = None
        self._is_connected = False
    
    async def connect(self) -> NATSClient:
        """
        Establish connection to NATS server with retry logic.
        
        Returns:
            Connected NATS client instance
            
        Raises:
            NATSConnectionError: If connection fails after retries
        """
        if self._client and self._is_connected:
            return self._client
        
        try:
            # Configure connection options
            options = {
                "servers": [self.settings.nats.connection_url],
                "name": self.connection_name,
                "ping_interval": 20,
                "max_outstanding_pings": 2,
                "reconnect_time_wait": 2,
                "max_reconnect_attempts": 10,
                "error_cb": self._error_callback,
                "disconnected_cb": self._disconnected_callback,
                "reconnected_cb": self._reconnected_callback,
                "closed_cb": self._closed_callback,
            }
            
            # Add authentication if configured
            if self.settings.nats.user and self.settings.nats.password:
                options["user"] = self.settings.nats.user
                options["password"] = self.settings.nats.password
            
            logger.info(
                "Connecting to NATS",
                url=self.settings.nats.connection_url,
                name=self.connection_name
            )
            
            self._client = await nats.connect(**options)
            self._is_connected = True
            
            # Initialize JetStream context
            if self.settings.nats.jetstream_enabled:
                self._jetstream = self._client.jetstream()
                await self._ensure_streams_exist()
            
            logger.info("NATS connection established successfully")
            return self._client
            
        except Exception as e:
            logger.error(
                "Failed to connect to NATS",
                error=str(e),
                url=self.settings.nats.connection_url
            )
            raise NATSConnectionError(
                f"Failed to connect to NATS: {e}",
                connection_url=self.settings.nats.connection_url,
                details={"original_error": str(e)}
            )
    
    async def disconnect(self) -> None:
        """Gracefully disconnect from NATS server."""
        if self._client and self._is_connected:
            try:
                await self._client.close()
                logger.info("NATS connection closed")
            except Exception as e:
                logger.warning("Error closing NATS connection", error=str(e))
            finally:
                self._client = None
                self._jetstream = None
                self._is_connected = False
    
    @property
    def client(self) -> Optional[NATSClient]:
        """Get the NATS client instance."""
        return self._client
    
    @property
    def jetstream(self) -> Optional[JetStreamContext]:
        """Get the JetStream context."""
        return self._jetstream
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to NATS."""
        return self._is_connected and self._client is not None
    
    async def _ensure_streams_exist(self) -> None:
        """Ensure required JetStream streams exist."""
        if not self._jetstream:
            return
        
        try:
            await create_jetstream_streams(self._jetstream)
        except Exception as e:
            logger.error("Failed to create JetStream streams", error=str(e))
            raise JetStreamConfigError(f"Failed to create streams: {e}")
    
    async def _error_callback(self, error: Exception) -> None:
        """Handle NATS connection errors."""
        logger.error("NATS connection error", error=str(error))
    
    async def _disconnected_callback(self) -> None:
        """Handle NATS disconnection."""
        logger.warning("NATS connection lost")
        self._is_connected = False
    
    async def _reconnected_callback(self) -> None:
        """Handle NATS reconnection."""
        logger.info("NATS connection re-established")
        self._is_connected = True
    
    async def _closed_callback(self) -> None:
        """Handle NATS connection closure."""
        logger.info("NATS connection closed")
        self._is_connected = False


@asynccontextmanager
async def get_nats_connection(
    connection_name: str = "temp-connection"
) -> AsyncGenerator[NATSConnection, None]:
    """
    Context manager for temporary NATS connections.
    
    Args:
        connection_name: Name for the connection (for debugging)
        
    Yields:
        Connected NATSConnection instance
        
    Usage:
        async with get_nats_connection() as conn:
            client = await conn.connect()
            # Use client for operations
    """
    connection = NATSConnection(connection_name)
    try:
        await connection.connect()
        yield connection
    finally:
        await connection.disconnect()


async def create_jetstream_streams(js: JetStreamContext) -> Dict[str, str]:
    """
    Create required JetStream streams for the approval workflow.
    
    Args:
        js: JetStream context
        
    Returns:
        Dictionary mapping stream names to their statuses
        
    Raises:
        JetStreamConfigError: If stream creation fails
    """
    settings = get_settings()
    stream_configs = {
        settings.nats.stream_approval: {
            "subjects": [
                f"{settings.nats.approval_subjects_prefix}.content.*",
                f"{settings.nats.approval_subjects_prefix}.technical.*", 
                f"{settings.nats.approval_subjects_prefix}.publish.*",
                f"{settings.nats.approval_subjects_prefix}.responses.*",
            ],
            "description": "SEO automation approval workflows",
            "retention": RetentionPolicy.LIMITS,
            "max_age": 7 * 24 * 3600,  # 7 days
            "max_msgs": 100000,
            "storage": StorageType.FILE,
        },
        settings.nats.stream_alerts: {
            "subjects": [
                "alerts.approval.timeout",
                "alerts.approval.rejected", 
                "alerts.system.error",
            ],
            "description": "SEO automation system alerts",
            "retention": RetentionPolicy.LIMITS,
            "max_age": 30 * 24 * 3600,  # 30 days
            "max_msgs": 50000,
            "storage": StorageType.FILE,
        },
        settings.nats.stream_tasks: {
            "subjects": [
                "tasks.delayed.*",
                "tasks.retry.*",
                "tasks.completion.*",
            ],
            "description": "SEO automation delayed tasks",
            "retention": RetentionPolicy.WORK_QUEUE,
            "max_age": 3 * 24 * 3600,  # 3 days  
            "max_msgs": 10000,
            "storage": StorageType.FILE,
        }
    }
    
    results = {}
    
    for stream_name, config in stream_configs.items():
        try:
            # Check if stream already exists
            try:
                stream_info = await js.stream_info(stream_name)
                logger.info(
                    "JetStream stream already exists",
                    stream=stream_name,
                    subjects=stream_info.config.subjects
                )
                results[stream_name] = "exists"
                continue
            except Exception:
                # Stream doesn't exist, create it
                pass
            
            # Create the stream
            stream_config = StreamConfig(
                name=stream_name,
                subjects=config["subjects"],
                description=config["description"],
                retention=config["retention"],
                max_age=config["max_age"],
                max_msgs=config["max_msgs"],
                storage=config["storage"],
            )
            
            stream_info = await js.add_stream(stream_config)
            logger.info(
                "Created JetStream stream",
                stream=stream_name,
                subjects=stream_info.config.subjects
            )
            results[stream_name] = "created"
            
        except Exception as e:
            logger.error(
                "Failed to create JetStream stream",
                stream=stream_name,
                error=str(e)
            )
            raise JetStreamConfigError(
                f"Failed to create stream {stream_name}: {e}",
                stream_name=stream_name,
                config_details=config
            )
    
    return results


async def create_approval_consumer(
    js: JetStreamContext,
    stream_name: str,
    consumer_name: str,
    filter_subject: str,
    durable: bool = True
) -> str:
    """
    Create a JetStream consumer for approval subjects.
    
    Args:
        js: JetStream context
        stream_name: Name of the stream
        consumer_name: Name for the consumer
        filter_subject: Subject pattern to filter messages
        durable: Whether to create a durable consumer
        
    Returns:
        Consumer name
        
    Raises:
        JetStreamConfigError: If consumer creation fails
    """
    try:
        # Check if consumer already exists
        try:
            consumer_info = await js.consumer_info(stream_name, consumer_name)
            logger.info(
                "JetStream consumer already exists",
                stream=stream_name,
                consumer=consumer_name
            )
            return consumer_name
        except Exception:
            # Consumer doesn't exist, create it
            pass
        
        # Create consumer configuration
        config = ConsumerConfig(
            durable_name=consumer_name if durable else None,
            filter_subject=filter_subject,
            ack_policy="explicit",
            max_deliver=3,
            ack_wait=30,  # 30 seconds to ack
            max_ack_pending=100,
        )
        
        consumer_info = await js.add_consumer(stream_name, config)
        logger.info(
            "Created JetStream consumer",
            stream=stream_name,
            consumer=consumer_name,
            filter=filter_subject
        )
        
        return consumer_info.name
        
    except Exception as e:
        logger.error(
            "Failed to create JetStream consumer",
            stream=stream_name,
            consumer=consumer_name,
            error=str(e)
        )
        raise JetStreamConfigError(
            f"Failed to create consumer {consumer_name} on stream {stream_name}: {e}",
            stream_name=stream_name,
            config_details={"consumer": consumer_name, "filter": filter_subject}
        )


def format_approval_subject(
    approval_type: str,
    action: str,
    site_id: Optional[int] = None
) -> str:
    """
    Format a NATS subject for approval requests.
    
    Args:
        approval_type: Type of approval (content, technical, publish)
        action: Specific action requiring approval
        site_id: Optional site ID for routing
        
    Returns:
        Formatted NATS subject
        
    Example:
        format_approval_subject("content", "create_post", 123)
        # Returns: "approvals.content.create_post.site123"
    """
    settings = get_settings()
    parts = [settings.nats.approval_subjects_prefix, approval_type, action]
    
    if site_id:
        parts.append(f"site{site_id}")
    
    return ".".join(parts)


def format_response_subject(approval_id: str) -> str:
    """
    Format a NATS subject for approval responses.
    
    Args:
        approval_id: Unique approval request ID
        
    Returns:
        Formatted response subject
    """
    settings = get_settings()
    return f"{settings.nats.approval_subjects_prefix}.responses.{approval_id}"


async def publish_json_message(
    client: NATSClient,
    subject: str,
    data: Dict[str, Any],
    reply_to: Optional[str] = None,
    timeout: float = 5.0
) -> None:
    """
    Publish a JSON message to a NATS subject.
    
    Args:
        client: NATS client instance
        subject: NATS subject to publish to
        data: Dictionary data to serialize as JSON
        reply_to: Optional reply subject
        timeout: Publish timeout in seconds
        
    Raises:
        NATSConnectionError: If publish fails
    """
    try:
        payload = json.dumps(data, default=str).encode()
        await client.publish(
            subject=subject,
            payload=payload,
            reply=reply_to,
            timeout=timeout
        )
        logger.debug(
            "Published JSON message",
            subject=subject,
            size=len(payload),
            reply_to=reply_to
        )
    except Exception as e:
        logger.error(
            "Failed to publish message",
            subject=subject,
            error=str(e)
        )
        raise NATSConnectionError(f"Failed to publish to {subject}: {e}")
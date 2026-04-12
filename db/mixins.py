"""
Model mixins for reusable functionality.

This module provides mixins for common model patterns like
metadata tracking, version control, and audit capabilities.
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional, Union

from sqlalchemy import JSON, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column


class MetadataMixin:
    """
    Mixin that adds a metadata JSON field for flexible data storage.
    
    Useful for storing additional configuration or dynamic data
    that doesn't require its own columns.
    """
    
    metadata_: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        default=dict,
        comment="JSON metadata for flexible data storage"
    )
    
    def set_metadata(self, key: str, value: Any) -> None:
        """Set a metadata value."""
        if self.metadata_ is None:
            self.metadata_ = {}
        self.metadata_[key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get a metadata value."""
        if self.metadata_ is None:
            return default
        return self.metadata_.get(key, default)
    
    def remove_metadata(self, key: str) -> None:
        """Remove a metadata key."""
        if self.metadata_ and key in self.metadata_:
            del self.metadata_[key]


class StatusMixin:
    """
    Mixin that adds a status field for tracking entity states.
    
    Common for entities that go through different lifecycle states
    like drafts, published, archived, etc.
    """
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        index=True,
        comment="Current status of the entity"
    )
    
    def is_active(self) -> bool:
        """Check if the entity is in active status."""
        return self.status == "active"
    
    def activate(self) -> None:
        """Set entity status to active."""
        self.status = "active"
    
    def deactivate(self) -> None:
        """Set entity status to inactive."""
        self.status = "inactive"


class AuditMixin:
    """
    Mixin that adds audit fields for tracking changes.
    
    Tracks who made changes and when for compliance and debugging.
    """
    
    created_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="User or system that created the record"
    )
    
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="User or system that last updated the record"
    )
    
    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        comment="Version number for optimistic locking"
    )


class ChangeTrackingMixin:
    """
    Mixin that tracks changes to model attributes.
    
    Automatically captures what fields were changed and their
    previous values for audit purposes.
    """
    
    change_log: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Log of changes made to the record"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_values = {}
    
    def _capture_original_values(self) -> None:
        """Capture the original values for change tracking."""
        self._original_values = {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
            if hasattr(self, column.name)
        }
    
    def get_changes(self) -> Dict[str, Dict[str, Any]]:
        """Get dictionary of changed fields with old and new values."""
        changes = {}
        for column in self.__table__.columns:
            attr_name = column.name
            if attr_name in ['change_log', 'updated_at']:
                continue
                
            original = self._original_values.get(attr_name)
            current = getattr(self, attr_name, None)
            
            if original != current:
                changes[attr_name] = {
                    'old': original,
                    'new': current
                }
        
        return changes


class TimescaleMixin:
    """
    Mixin for TimescaleDB hypertable configuration.
    
    Models that use this mixin will be configured as hypertables
    for optimal time-series data storage and querying.
    """
    
    @classmethod
    def create_hypertable(cls, connection, time_column: str = "created_at", 
                         chunk_time_interval: str = "7d") -> None:
        """
        Create a TimescaleDB hypertable for this model.
        
        Args:
            connection: Database connection
            time_column: Column to use for time partitioning
            chunk_time_interval: Size of time chunks (e.g., '7d', '1h')
        """
        import re
        
        table_name = cls.__tablename__
        
        # Validate table name against expected pattern
        if not re.match(r'^[a-z_][a-z0-9_]*$', table_name):
            raise ValueError(f"Invalid table name: {table_name}")
        
        # Validate time column name against expected pattern
        if not re.match(r'^[a-z_][a-z0-9_]*$', time_column):
            raise ValueError(f"Invalid time column name: {time_column}")
        
        # Validate chunk_time_interval against allowlist
        VALID_INTERVAL = re.compile(r'^\d+\s*(day|hour|minute)s?$', re.I)
        if not VALID_INTERVAL.match(chunk_time_interval):
            raise ValueError(f"Invalid chunk_time_interval: {chunk_time_interval}")
        
        # Create hypertable using parameterized query
        connection.execute(
            f"SELECT create_hypertable('{table_name}', '{time_column}', "
            f"chunk_time_interval => INTERVAL '{chunk_time_interval}')"
        )
        
        # Add compression policy (compress chunks older than 30 days)
        connection.execute(
            f"ALTER TABLE {table_name} SET (timescaledb.compress, "
            f"timescaledb.compress_segmentby = 'site_id')"
        )
        
        connection.execute(
            f"SELECT add_compression_policy('{table_name}', INTERVAL '30 days')"
        )


# Event listeners for change tracking
@event.listens_for(ChangeTrackingMixin, 'load', propagate=True)
def capture_original_values_on_load(target, context):
    """Capture original values when loading from database."""
    target._capture_original_values()


@event.listens_for(ChangeTrackingMixin, 'before_update', propagate=True)
def log_changes_before_update(mapper, connection, target):
    """Log changes before update."""
    changes = target.get_changes()
    if changes:
        if target.change_log is None:
            target.change_log = []
        
        target.change_log.append({
            'timestamp': datetime.utcnow().isoformat(),
            'changes': changes
        })
        
        # Keep only last 10 change entries to prevent bloat
        if len(target.change_log) > 10:
            target.change_log = target.change_log[-10:]
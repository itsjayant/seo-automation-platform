"""
Base classes for SQLAlchemy ORM models.

This module provides the base model class with common functionality
and configuration for all models in the SEO automation platform.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import MetaData, func, text
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime, UUID
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID


# Custom naming convention for constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    
    Provides consistent configuration and metadata for all models,
    including naming conventions for constraints and indexes.
    """
    
    metadata = metadata
    
    @declared_attr.directive
    def __tablename__(cls) -> str:
        """Generate table name from class name in snake_case."""
        # Convert CamelCase to snake_case
        name = cls.__name__
        import re
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name)
        return name.lower()
    
    def __repr__(self) -> str:
        """Default representation showing class name and id if available."""
        id_str = getattr(self, 'id', 'no_id')
        return f"<{self.__class__.__name__}(id={id_str})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }


class TimestampMixin:
    """
    Mixin that adds automatic created_at and updated_at timestamps.
    
    All models should inherit from this mixin to track creation
    and modification times.
    """
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when the record was created"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Timestamp when the record was last updated"
    )


class UUIDMixin:
    """
    Mixin that adds a UUID primary key.
    
    Useful for models that need globally unique identifiers
    instead of sequential integers.
    """
    
    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="Unique identifier for the record"
    )


class SoftDeleteMixin:
    """
    Mixin that adds soft delete functionality.
    
    Records are not physically deleted but marked as deleted
    with a timestamp for audit purposes.
    """
    
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp when the record was soft deleted"
    )
    
    @property
    def is_deleted(self) -> bool:
        """Check if the record is soft deleted."""
        return self.deleted_at is not None
    
    def soft_delete(self) -> None:
        """Mark the record as soft deleted."""
        self.deleted_at = datetime.now(timezone.utc)
    
    def restore(self) -> None:
        """Restore a soft deleted record."""
        self.deleted_at = None


def utcnow() -> datetime:
    """Helper function to get current UTC timestamp."""
    return datetime.now(timezone.utc)
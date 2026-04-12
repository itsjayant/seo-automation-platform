"""
Database module for SEO Automation Platform.

This module provides database connection utilities, schema management,
ORM models, and utilities for PostgreSQL with TimescaleDB and pgvector extensions.

Core components:
- connection.py: Database connection utilities and pooling
- models.py: SQLAlchemy ORM models for all entities
- base.py: Base model classes and mixins
- mixins.py: Reusable model functionality
- utils.py: Database utility functions and extension validation
- test_connection.py: Connection validation and health checks
"""

from .connection import (
    DatabaseManager,
    get_database_manager
)

from .models import (
    # Base classes
    Base,
    
    # Core models
    Site,
    Keyword,
    Ranking,
    GSCMetric,
    GA4Metric,
    AuditLog,
    
    # Enums
    CMSType,
    KeywordIntent,
    KeywordPriority,
    ActionType,
    EntityType,
    ApprovalStatus,
)

from .base import (
    TimestampMixin,
    UUIDMixin,
    SoftDeleteMixin,
    utcnow,
)

from .mixins import (
    MetadataMixin,
    StatusMixin,
    AuditMixin,
    ChangeTrackingMixin,
    TimescaleMixin,
)

from .utils import (
    validate_extensions,
    test_timescaledb,
    test_pgvector,
    get_database_info,
)

from .init_schema import (
    DatabaseInitializer,
    initialize_database,
    create_tables,
    configure_hypertables,
    async_initialize_database,
)

__all__ = [
    # Connection utilities
    "DatabaseManager",
    "get_database_manager",
    
    # Models
    "Base",
    "Site",
    "Keyword",
    "Ranking", 
    "GSCMetric",
    "GA4Metric",
    "AuditLog",
    
    # Enums
    "CMSType",
    "KeywordIntent",
    "KeywordPriority",
    "ActionType",
    "EntityType",
    "ApprovalStatus",
    
    # Base classes and mixins
    "TimestampMixin",
    "UUIDMixin",
    "SoftDeleteMixin",
    "MetadataMixin",
    "StatusMixin",
    "AuditMixin",
    "ChangeTrackingMixin",
    "TimescaleMixin",
    "utcnow",
    
    # Initialization utilities
    "DatabaseInitializer",
    "initialize_database",
    "create_tables",
    "configure_hypertables",
    "async_initialize_database",
    
    # Utility functions
    "validate_extensions",
    "test_timescaledb",
    "test_pgvector",
    "get_database_info",
]
"""
Alembic migration environment for SEO Automation Platform.

This module configures the Alembic migration environment to work with:
- Pydantic configuration system
- PostgreSQL with TimescaleDB and pgvector extensions
- SQLAlchemy models with automatic metadata detection
"""

import asyncio
import os
import sys
import importlib.util
from logging.config import fileConfig
from typing import List

from sqlalchemy import Connection, pool
from sqlalchemy.engine import create_engine
from sqlalchemy.ext.asyncio import async_engine_from_config, AsyncConnection

from alembic import context

# Add the project root to sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import configuration and base model
from config import get_settings
from db.base import Base

# Import models carefully to avoid problematic utils import
try:
    # Try to import models through the package first
    from db.models import *
except ImportError:
    # If that fails, import directly from the file to avoid __init__.py issues
    models_path = os.path.join(os.path.dirname(__file__), "..", "models.py")
    spec = importlib.util.spec_from_file_location("models", models_path)
    models_module = importlib.util.module_from_spec(spec)
    
    # Import required modules first
    import db.mixins
    sys.modules['db.mixins'] = db.mixins
    
    spec.loader.exec_module(models_module)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata from our SQLAlchemy Base
target_metadata = Base.metadata

# Get database settings from Pydantic configuration
try:
    settings = get_settings()
    database_url = settings.database.connection_url
    # Override the sqlalchemy.url in alembic.ini with our Pydantic config
    config.set_main_option("sqlalchemy.url", database_url)
except Exception as e:
    print(f"Warning: Could not load database settings: {e}")
    # Fallback to placeholder URL for offline mode
    database_url = "postgresql://placeholder"

def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """
    Custom type comparison for pgvector and other PostgreSQL types.
    
    This function handles special cases where SQLAlchemy's default type
    comparison might not work correctly with PostgreSQL extensions.
    """
    # Handle pgvector Vector type comparison
    if hasattr(metadata_type, "dialect") and "vector" in str(metadata_type).lower():
        # For vector types, compare the dimension if both types are vectors
        if hasattr(inspected_type, "dimension") and hasattr(metadata_type, "dimension"):
            return inspected_type.dimension != metadata_type.dimension
        # If one is vector and other isn't, they're different
        return "vector" not in str(inspected_type).lower()
    
    # Use default comparison for other types
    return None


def include_name(name, type_, parent_names):
    """
    Filter what objects should be included in autogenerate.
    
    Excludes certain system objects and TimescaleDB internal objects.
    """
    if type_ == "table":
        # Exclude TimescaleDB internal tables
        if name.startswith("_timescaledb_"):
            return False
        # Exclude PostGIS and other system tables
        if name in ["spatial_ref_sys", "geography_columns", "geometry_columns"]:
            return False
    
    return True


def include_object(object, name, type_, reflected, compare_to):
    """
    Filter objects for autogeneration.
    
    This is used to exclude certain objects from being considered during
    autogenerate operations.
    """
    if type_ == "table" and reflected and compare_to is None:
        # Don't auto-create tables that exist in the database but not in metadata
        # This prevents TimescaleDB internal tables from being included
        return False
    
    return True


def render_item(type_, obj, autogen_context):
    """
    Custom rendering for specific SQLAlchemy constructs.
    
    Handles special cases for PostgreSQL extensions like TimescaleDB and pgvector.
    """
    # Custom rendering can be added here if needed for specific types
    return False


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the
    Engine creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_type,
        include_name=include_name,
        include_object=include_object,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Run migrations with the given connection.
    
    This is extracted to a separate function to handle both sync and async cases.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=compare_type,
        include_name=include_name,
        include_object=include_object,
        render_item=render_item,
        # Configure for TimescaleDB and pgvector support
        compare_server_default=True,
        process_revision_directives=None,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate
    a connection with the context.
    """
    # Create engine with connection pooling disabled for migrations
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        # Enable echo for debugging if needed
        echo=False,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


async def run_async_migrations() -> None:
    """
    Run migrations in async mode.
    
    This is an option for async-only applications, though sync mode
    is typically sufficient for migrations.
    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = database_url
    
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

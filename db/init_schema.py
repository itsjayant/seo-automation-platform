"""
Database initialization utilities for SQLAlchemy models.

This module provides functions to create tables, configure TimescaleDB hypertables,
and set up indexes for optimal performance in the SEO automation platform.
"""

import asyncio
import logging
from typing import List, Optional

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config import get_settings
from .base import Base
from .models import Ranking, GSCMetric, GA4Metric

logger = structlog.get_logger(__name__)


class DatabaseInitializer:
    """
    Database initialization and schema management.
    
    Handles table creation, TimescaleDB hypertable configuration,
    and performance optimization setup.
    """
    
    def __init__(self):
        self.settings = get_settings().database
        
    def get_sync_engine(self) -> Engine:
        """Create synchronous SQLAlchemy engine."""
        database_url = (
            f"postgresql://{self.settings.username}:{self.settings.password}"
            f"@{self.settings.host}:{self.settings.port}/{self.settings.database}"
        )
        
        return create_engine(
            database_url,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    
    def get_async_engine(self) -> AsyncEngine:
        """Create asynchronous SQLAlchemy engine.""" 
        database_url = (
            f"postgresql+asyncpg://{self.settings.username}:{self.settings.password}"
            f"@{self.settings.host}:{self.settings.port}/{self.settings.database}"
        )
        
        return create_async_engine(
            database_url,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    
    def create_tables(self, engine: Optional[Engine] = None) -> None:
        """
        Create all SQLAlchemy tables.
        
        Args:
            engine: SQLAlchemy engine (creates new one if not provided)
        """
        if engine is None:
            engine = self.get_sync_engine()
        
        logger.info("Creating database tables...")
        
        try:
            Base.metadata.create_all(engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error("Failed to create database tables", error=str(e))
            raise
    
    def configure_hypertables(self, engine: Optional[Engine] = None) -> None:
        """
        Configure TimescaleDB hypertables for time-series models.
        
        Args:
            engine: SQLAlchemy engine (creates new one if not provided)
        """
        if engine is None:
            engine = self.get_sync_engine()
        
        logger.info("Configuring TimescaleDB hypertables...")
        
        hypertable_configs = [
            {
                'table': 'rankings',
                'time_column': 'date',
                'chunk_interval': self.settings.chunk_time_interval,
                'compress_after': '30 days'
            },
            {
                'table': 'gsc_metrics', 
                'time_column': 'date',
                'chunk_interval': self.settings.chunk_time_interval,
                'compress_after': '30 days'
            },
            {
                'table': 'ga4_metrics',
                'time_column': 'date', 
                'chunk_interval': self.settings.chunk_time_interval,
                'compress_after': '30 days'
            }
        ]
        
        with engine.connect() as conn:
            for config in hypertable_configs:
                try:
                    # Create hypertable
                    conn.execute(text(
                        f"SELECT create_hypertable('{config['table']}', '{config['time_column']}', "
                        f"chunk_time_interval => INTERVAL '{config['chunk_interval']}', "
                        f"if_not_exists => TRUE)"
                    ))
                    
                    # Enable compression
                    conn.execute(text(
                        f"ALTER TABLE {config['table']} SET ("
                        f"timescaledb.compress, "
                        f"timescaledb.compress_segmentby = 'site_id'"
                        f")"
                    ))
                    
                    # Add compression policy
                    conn.execute(text(
                        f"SELECT add_compression_policy('{config['table']}', "
                        f"INTERVAL '{config['compress_after']}', "
                        f"if_not_exists => TRUE)"
                    ))
                    
                    # Add retention policy (optional - keep last 2 years)
                    conn.execute(text(
                        f"SELECT add_retention_policy('{config['table']}', "
                        f"INTERVAL '2 years', "
                        f"if_not_exists => TRUE)"
                    ))
                    
                    logger.info(f"Configured hypertable: {config['table']}")
                    
                except Exception as e:
                    logger.warning(
                        f"Failed to configure hypertable {config['table']}: {str(e)}. "
                        f"This may be expected if already configured."
                    )
            
            conn.commit()
        
        logger.info("TimescaleDB hypertables configured successfully")
    
    def create_indexes(self, engine: Optional[Engine] = None) -> None:
        """
        Create additional performance indexes.
        
        Args:
            engine: SQLAlchemy engine (creates new one if not provided)
        """
        if engine is None:
            engine = self.get_sync_engine()
        
        logger.info("Creating additional performance indexes...")
        
        additional_indexes = [
            # Vector similarity indexes (if not already created by model)
            "CREATE INDEX IF NOT EXISTS ix_keywords_embedding_ip "
            "ON keywords USING ivfflat (embedding vector_ip_ops) "
            "WITH (lists = 100)",
            
            # Composite indexes for common query patterns
            "CREATE INDEX IF NOT EXISTS ix_rankings_site_keyword_date "
            "ON rankings (site_id, keyword_id, date DESC)",
            
            "CREATE INDEX IF NOT EXISTS ix_gsc_metrics_site_url_date " 
            "ON gsc_metrics (site_id, url, date DESC)",
            
            "CREATE INDEX IF NOT EXISTS ix_ga4_metrics_site_path_date "
            "ON ga4_metrics (site_id, page_path, date DESC)",
            
            # Audit log performance indexes
            "CREATE INDEX IF NOT EXISTS ix_audit_log_entity_created "
            "ON audit_log (entity_type, entity_id, created_at DESC)",
            
            "CREATE INDEX IF NOT EXISTS ix_audit_log_action_created "
            "ON audit_log (action_type, created_at DESC)",
        ]
        
        with engine.connect() as conn:
            for index_sql in additional_indexes:
                try:
                    conn.execute(text(index_sql))
                    logger.debug(f"Created index: {index_sql[:50]}...")
                except Exception as e:
                    logger.warning(f"Failed to create index: {str(e)}")
            
            conn.commit()
        
        logger.info("Additional performance indexes created successfully")
    
    def initialize_database(self, engine: Optional[Engine] = None) -> None:
        """
        Complete database initialization.
        
        Creates tables, configures hypertables, and sets up indexes.
        
        Args:
            engine: SQLAlchemy engine (creates new one if not provided)
        """
        if engine is None:
            engine = self.get_sync_engine()
        
        logger.info("Starting complete database initialization...")
        
        try:
            # Create all tables
            self.create_tables(engine)
            
            # Configure TimescaleDB hypertables
            if self.settings.timescaledb_enabled:
                self.configure_hypertables(engine)
            
            # Create additional indexes
            self.create_indexes(engine)
            
            logger.info("Database initialization completed successfully")
            
        except Exception as e:
            logger.error("Database initialization failed", error=str(e))
            raise
    
    def drop_all_tables(self, engine: Optional[Engine] = None) -> None:
        """
        Drop all tables (USE WITH CAUTION).
        
        Args:
            engine: SQLAlchemy engine (creates new one if not provided)
        """
        if engine is None:
            engine = self.get_sync_engine()
        
        logger.warning("Dropping all database tables...")
        
        try:
            Base.metadata.drop_all(engine)
            logger.warning("All database tables dropped")
        except Exception as e:
            logger.error("Failed to drop database tables", error=str(e))
            raise


# Convenience functions
def initialize_database() -> None:
    """Initialize the database with default settings."""
    initializer = DatabaseInitializer()
    initializer.initialize_database()


def create_tables() -> None:
    """Create all SQLAlchemy tables."""
    initializer = DatabaseInitializer()
    initializer.create_tables()


def configure_hypertables() -> None:
    """Configure TimescaleDB hypertables.""" 
    initializer = DatabaseInitializer()
    initializer.configure_hypertables()


async def async_initialize_database() -> None:
    """Asynchronous database initialization."""
    # Run sync initialization in thread pool
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, initialize_database)


if __name__ == "__main__":
    # Allow running this module directly for database initialization
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "init":
            initialize_database()
        elif command == "tables":
            create_tables()
        elif command == "hypertables":
            configure_hypertables()
        elif command == "drop":
            initializer = DatabaseInitializer()
            confirm = input("Are you sure you want to drop all tables? (yes/no): ")
            if confirm.lower() == "yes":
                initializer.drop_all_tables()
            else:
                print("Aborted.")
        else:
            print(f"Unknown command: {command}")
            print("Available commands: init, tables, hypertables, drop")
    else:
        print("Usage: python -m db.init_schema <command>")
        print("Commands:")
        print("  init       - Full database initialization")
        print("  tables     - Create tables only")
        print("  hypertables - Configure TimescaleDB hypertables only")
        print("  drop       - Drop all tables (dangerous!)")
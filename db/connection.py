"""
Database connection utilities for SEO Automation Platform.

This module provides connection pooling, async/sync connections,
and database health checking for PostgreSQL with TimescaleDB and pgvector.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
import asyncpg
import psycopg2
import psycopg2.pool
from psycopg2.extras import DictCursor
import structlog

from config import get_settings

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """
    Database connection manager with support for both async and sync connections.
    Handles connection pooling and provides database health checking.
    """

    def __init__(self):
        self.settings = get_settings().database
        self._async_pool: Optional[asyncpg.Pool] = None
        self._sync_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
        self._initialized = False

    async def initialize_async_pool(self) -> None:
        """Initialize async connection pool."""
        if self._async_pool:
            return

        try:
            self._async_pool = await asyncpg.create_pool(
                host=self.settings.host,
                port=self.settings.port,
                user=self.settings.username,
                password=self.settings.password,
                database=self.settings.database,
                min_size=self.settings.min_connections,
                max_size=self.settings.max_connections,
                command_timeout=self.settings.pool_timeout,
                server_settings={
                    "jit": "off",  # Disable JIT for better performance on small queries
                    "application_name": "seo_platform_async",
                }
            )
            logger.info(
                "Async database pool initialized",
                pool_size=f"{self.settings.min_connections}-{self.settings.max_connections}"
            )
        except Exception as e:
            logger.error("Failed to initialize async database pool", error=str(e))
            raise

    def initialize_sync_pool(self) -> None:
        """Initialize sync connection pool."""
        if self._sync_pool:
            return

        try:
            self._sync_pool = psycopg2.pool.ThreadedConnectionPool(
                self.settings.min_connections,
                self.settings.max_connections,
                host=self.settings.host,
                port=self.settings.port,
                user=self.settings.username,
                password=self.settings.password,
                database=self.settings.database,
                cursor_factory=DictCursor,
                application_name="seo_platform_sync",
            )
            logger.info(
                "Sync database pool initialized",
                pool_size=f"{self.settings.min_connections}-{self.settings.max_connections}"
            )
        except Exception as e:
            logger.error("Failed to initialize sync database pool", error=str(e))
            raise

    @asynccontextmanager
    async def async_connection(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """
        Get an async database connection from the pool.
        
        Usage:
            async with db_manager.async_connection() as conn:
                result = await conn.fetch("SELECT 1")
        """
        if not self._async_pool:
            await self.initialize_async_pool()
        
        connection = await self._async_pool.acquire()
        try:
            yield connection
        finally:
            await self._async_pool.release(connection)

    @contextmanager
    def sync_connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        """
        Get a sync database connection from the pool.
        
        Usage:
            with db_manager.sync_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    result = cur.fetchall()
        """
        if not self._sync_pool:
            self.initialize_sync_pool()
        
        connection = self._sync_pool.getconn()
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            self._sync_pool.putconn(connection)

    async def close_pools(self) -> None:
        """Close all connection pools."""
        if self._async_pool:
            await self._async_pool.close()
            self._async_pool = None
            logger.info("Async database pool closed")
        
        if self._sync_pool:
            self._sync_pool.closeall()
            self._sync_pool = None
            logger.info("Sync database pool closed")

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform comprehensive database health check.
        
        Returns:
            Dict with health status and extension information.
        """
        health_info = {
            "status": "unhealthy",
            "postgres_version": None,
            "extensions": {},
            "connection_pools": {
                "async": "not_initialized",
                "sync": "not_initialized"
            },
            "errors": []
        }

        try:
            # Test async connection
            async with self.async_connection() as conn:
                # Check PostgreSQL version
                version_result = await conn.fetchval("SELECT version()")
                health_info["postgres_version"] = version_result

                # Check required extensions
                extensions_query = """
                    SELECT extname, extversion 
                    FROM pg_extension 
                    WHERE extname IN ('timescaledb', 'vector', 'uuid-ossp', 'pg_stat_statements')
                """
                ext_records = await conn.fetch(extensions_query)
                for record in ext_records:
                    health_info["extensions"][record["extname"]] = record["extversion"]

                # Verify connection pools
                health_info["connection_pools"]["async"] = "healthy"
                
                # Test sync connection briefly
                with self.sync_connection() as sync_conn:
                    health_info["connection_pools"]["sync"] = "healthy"

                health_info["status"] = "healthy"
                
        except Exception as e:
            error_msg = f"Database health check failed: {str(e)}"
            health_info["errors"].append(error_msg)
            logger.error("Database health check failed", error=str(e))

        return health_info


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """Get or create the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


async def get_async_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Convenience function to get an async database connection.
    
    Usage:
        async with get_async_connection() as conn:
            result = await conn.fetch("SELECT 1")
    """
    db_manager = get_database_manager()
    async with db_manager.async_connection() as conn:
        yield conn


def get_sync_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Convenience function to get a sync database connection.
    
    Usage:
        with get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchall()
    """
    db_manager = get_database_manager()
    with db_manager.sync_connection() as conn:
        yield conn


@contextmanager
def get_sync_session():
    """
    Get a SQLAlchemy session from the sync connection pool.
    
    Usage:
        with get_sync_session() as session:
            result = session.query(Model).all()
            session.commit()
    """
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    from config import get_settings
    
    settings = get_settings()
    engine = create_engine(settings.database.connection_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def test_database_connection() -> Dict[str, Any]:
    """
    Test database connectivity and return detailed status.
    
    Returns:
        Dict with connection status, timing, and any errors.
    """
    import time
    
    start_time = time.time()
    result = {
        "status": "failed",
        "connection_time": 0,
        "postgres_version": None,
        "database_name": None,
        "errors": []
    }

    try:
        settings = get_settings().database
        
        # Test async connection
        async with get_async_connection() as conn:
            # Basic connectivity test
            test_result = await conn.fetchval("SELECT 1")
            if test_result != 1:
                raise Exception("Basic connectivity test failed")
            
            # Get database information
            db_name = await conn.fetchval("SELECT current_database()")
            version = await conn.fetchval("SELECT version()")
            
            result.update({
                "status": "success",
                "connection_time": round((time.time() - start_time) * 1000, 2),
                "postgres_version": version,
                "database_name": db_name,
            })
            
    except Exception as e:
        error_msg = f"Connection test failed: {str(e)}"
        result["errors"].append(error_msg)
        result["connection_time"] = round((time.time() - start_time) * 1000, 2)
        logger.error("Database connection test failed", error=str(e))

    return result
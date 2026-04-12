"""
Database utility functions for SEO Automation Platform.

This module provides utilities for validating database extensions,
testing TimescaleDB and pgvector functionality, and database administration.
"""

import asyncio
import json
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import structlog

from .connection import get_async_connection, get_sync_connection

logger = structlog.get_logger(__name__)


async def validate_extensions() -> Dict[str, Any]:
    """
    Validate that all required PostgreSQL extensions are installed and functional.
    
    Returns:
        Dict with validation results for each extension.
    """
    validation_results = {
        "status": "success",
        "extensions": {},
        "errors": []
    }
    
    required_extensions = {
        "timescaledb": "TimescaleDB for time-series data",
        "vector": "pgvector for semantic similarity",
        "uuid-ossp": "UUID generation functions", 
        "pg_stat_statements": "Query performance monitoring"
    }
    
    try:
        async with get_async_connection() as conn:
            # Check extension installation
            extensions_query = """
                SELECT 
                    extname,
                    extversion,
                    extrelocatable,
                    n.nspname AS schema
                FROM pg_extension e
                JOIN pg_namespace n ON e.extnamespace = n.oid
                WHERE extname = ANY($1)
            """
            
            extension_names = list(required_extensions.keys())
            installed_extensions = await conn.fetch(extensions_query, extension_names)
            
            # Process each required extension
            for ext_name, description in required_extensions.items():
                ext_info = {
                    "description": description,
                    "installed": False,
                    "version": None,
                    "schema": None,
                    "functional": False,
                    "test_results": {}
                }
                
                # Check if extension is installed
                for installed_ext in installed_extensions:
                    if installed_ext["extname"] == ext_name:
                        ext_info.update({
                            "installed": True,
                            "version": installed_ext["extversion"], 
                            "schema": installed_ext["schema"]
                        })
                        break
                
                # Run functional tests if installed
                if ext_info["installed"]:
                    if ext_name == "timescaledb":
                        ext_info["test_results"] = await test_timescaledb(conn)
                    elif ext_name == "vector":
                        ext_info["test_results"] = await test_pgvector(conn)
                    elif ext_name == "uuid-ossp":
                        ext_info["test_results"] = await test_uuid_functions(conn)
                    elif ext_name == "pg_stat_statements":
                        ext_info["test_results"] = await test_pg_stat_statements(conn)
                    
                    ext_info["functional"] = ext_info["test_results"].get("success", False)
                
                validation_results["extensions"][ext_name] = ext_info
            
            # Overall status
            all_functional = all(
                ext_info["functional"] for ext_info in validation_results["extensions"].values()
            )
            validation_results["status"] = "success" if all_functional else "partial"
            
    except Exception as e:
        error_msg = f"Extension validation failed: {str(e)}"
        validation_results["errors"].append(error_msg)
        validation_results["status"] = "failed"
        logger.error("Extension validation failed", error=str(e))
    
    return validation_results


async def test_timescaledb(conn) -> Dict[str, Any]:
    """Test TimescaleDB functionality by creating and testing a hypertable."""
    test_results = {
        "success": False,
        "features": {},
        "errors": []
    }
    
    try:
        # Test hypertable creation
        test_table_name = f"test_timescale_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create test table
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {test_table_name} (
                time TIMESTAMPTZ NOT NULL,
                device_id INTEGER,
                temperature DOUBLE PRECISION
            )
        """)
        
        # Convert to hypertable
        await conn.execute(f"""
            SELECT create_hypertable('{test_table_name}', 'time', if_not_exists => TRUE)
        """)
        
        # Insert test data
        test_time = datetime.now()
        await conn.execute(f"""
            INSERT INTO {test_table_name} (time, device_id, temperature) 
            VALUES ($1, $2, $3)
        """, test_time, 1, 25.5)
        
        # Verify data insertion
        result = await conn.fetchval(f"SELECT COUNT(*) FROM {test_table_name}")
        test_results["features"]["hypertable_creation"] = True
        test_results["features"]["data_insertion"] = result == 1
        
        # Test time-bucket aggregation
        bucket_result = await conn.fetchval(f"""
            SELECT time_bucket('1 hour', time) as bucket
            FROM {test_table_name}
            ORDER BY bucket
            LIMIT 1
        """)
        test_results["features"]["time_bucketing"] = bucket_result is not None
        
        # Clean up test table
        await conn.execute(f"DROP TABLE IF EXISTS {test_table_name}")
        
        # Check TimescaleDB version and configuration
        version_info = await conn.fetchrow("""
            SELECT extversion 
            FROM pg_extension 
            WHERE extname = 'timescaledb'
        """)
        
        if version_info:
            test_results["features"]["version"] = version_info["extversion"]
        
        test_results["success"] = all(test_results["features"].values())
        
    except Exception as e:
        error_msg = f"TimescaleDB test failed: {str(e)}"
        test_results["errors"].append(error_msg)
        logger.error("TimescaleDB test failed", error=str(e))
    
    return test_results


async def test_pgvector(conn) -> Dict[str, Any]:
    """Test pgvector functionality by creating and testing vector operations."""
    test_results = {
        "success": False,
        "features": {},
        "errors": []
    }
    
    try:
        test_table_name = f"test_vector_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create test table with vector column
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {test_table_name} (
                id SERIAL PRIMARY KEY,
                content TEXT,
                embedding VECTOR(3)
            )
        """)
        
        # Insert test vectors
        test_vectors = [
            (1, "test content 1", [0.1, 0.2, 0.3]),
            (2, "test content 2", [0.4, 0.5, 0.6]),
            (3, "test content 3", [0.7, 0.8, 0.9])
        ]
        
        for item_id, content, vector in test_vectors:
            await conn.execute(f"""
                INSERT INTO {test_table_name} (id, content, embedding) 
                VALUES ($1, $2, $3)
            """, item_id, content, vector)
        
        # Test vector similarity search (cosine distance)
        similarity_result = await conn.fetch(f"""
            SELECT id, content, (embedding <=> $1) AS distance
            FROM {test_table_name}
            ORDER BY distance
            LIMIT 2
        """, [0.1, 0.2, 0.3])
        
        test_results["features"]["vector_creation"] = True
        test_results["features"]["similarity_search"] = len(similarity_result) == 2
        test_results["features"]["cosine_distance"] = similarity_result[0]["distance"] is not None
        
        # Test dot product
        dot_result = await conn.fetchval(f"""
            SELECT (embedding <#> $1) as dot_product 
            FROM {test_table_name} 
            WHERE id = 1
        """, [0.1, 0.2, 0.3])
        test_results["features"]["dot_product"] = dot_result is not None
        
        # Test L2 distance  
        l2_result = await conn.fetchval(f"""
            SELECT (embedding <-> $1) as l2_distance 
            FROM {test_table_name} 
            WHERE id = 1
        """, [0.1, 0.2, 0.3])
        test_results["features"]["l2_distance"] = l2_result is not None
        
        # Clean up test table
        await conn.execute(f"DROP TABLE IF EXISTS {test_table_name}")
        
        # Check pgvector version
        version_info = await conn.fetchrow("""
            SELECT extversion 
            FROM pg_extension 
            WHERE extname = 'vector'
        """)
        
        if version_info:
            test_results["features"]["version"] = version_info["extversion"]
        
        test_results["success"] = all(
            test_results["features"][key] for key in test_results["features"] 
            if key != "version"
        )
        
    except Exception as e:
        error_msg = f"pgvector test failed: {str(e)}"
        test_results["errors"].append(error_msg)
        logger.error("pgvector test failed", error=str(e))
    
    return test_results


async def test_uuid_functions(conn) -> Dict[str, Any]:
    """Test UUID generation functions."""
    test_results = {
        "success": False,
        "features": {},
        "errors": []
    }
    
    try:
        # Test uuid_generate_v4()
        uuid_v4 = await conn.fetchval("SELECT uuid_generate_v4()")
        test_results["features"]["uuid_v4"] = uuid_v4 is not None and len(str(uuid_v4)) == 36
        
        # Test uuid_generate_v1()
        uuid_v1 = await conn.fetchval("SELECT uuid_generate_v1()")
        test_results["features"]["uuid_v1"] = uuid_v1 is not None and len(str(uuid_v1)) == 36
        
        # Check extension version
        version_info = await conn.fetchrow("""
            SELECT extversion 
            FROM pg_extension 
            WHERE extname = 'uuid-ossp'
        """)
        
        if version_info:
            test_results["features"]["version"] = version_info["extversion"]
        
        test_results["success"] = all(
            test_results["features"][key] for key in test_results["features"] 
            if key != "version"
        )
        
    except Exception as e:
        error_msg = f"UUID functions test failed: {str(e)}"
        test_results["errors"].append(error_msg)
        logger.error("UUID functions test failed", error=str(e))
    
    return test_results


async def test_pg_stat_statements(conn) -> Dict[str, Any]:
    """Test pg_stat_statements extension for query monitoring.""" 
    test_results = {
        "success": False,
        "features": {},
        "errors": []
    }
    
    try:
        # Test basic functionality
        stats_count = await conn.fetchval("SELECT COUNT(*) FROM pg_stat_statements")
        test_results["features"]["stats_collection"] = stats_count >= 0
        
        # Test that we can reset stats (requires superuser or appropriate permissions)
        try:
            await conn.execute("SELECT pg_stat_statements_reset()")
            test_results["features"]["stats_reset"] = True
        except Exception:
            # Reset might not be allowed for non-superuser, but that's okay
            test_results["features"]["stats_reset"] = False
        
        # Check extension version
        version_info = await conn.fetchrow("""
            SELECT extversion 
            FROM pg_extension 
            WHERE extname = 'pg_stat_statements'
        """)
        
        if version_info:
            test_results["features"]["version"] = version_info["extversion"]
        
        test_results["success"] = test_results["features"]["stats_collection"]
        
    except Exception as e:
        error_msg = f"pg_stat_statements test failed: {str(e)}"
        test_results["errors"].append(error_msg)
        logger.error("pg_stat_statements test failed", error=str(e))
    
    return test_results


async def get_database_info() -> Dict[str, Any]:
    """
    Get comprehensive database information including server stats and configuration.
    
    Returns:
        Dict with database server information, configuration, and statistics.
    """
    db_info = {
        "server": {},
        "configuration": {},
        "statistics": {},
        "extensions": {},
        "errors": []
    }
    
    try:
        async with get_async_connection() as conn:
            # Server information
            server_queries = {
                "version": "SELECT version()",
                "current_database": "SELECT current_database()",
                "current_user": "SELECT current_user",
                "server_encoding": "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database()",
                "timezone": "SELECT current_setting('timezone')",
                "server_uptime": "SELECT date_trunc('second', current_timestamp - pg_postmaster_start_time()) as uptime"
            }
            
            for key, query in server_queries.items():
                try:
                    result = await conn.fetchval(query)
                    db_info["server"][key] = str(result) if result else None
                except Exception as e:
                    db_info["errors"].append(f"Failed to get {key}: {str(e)}")
            
            # Configuration settings
            config_settings = [
                "max_connections",
                "shared_buffers", 
                "effective_cache_size",
                "work_mem",
                "maintenance_work_mem",
                "checkpoint_completion_target",
                "wal_buffers",
                "default_statistics_target"
            ]
            
            for setting in config_settings:
                try:
                    value = await conn.fetchval("SELECT current_setting($1)", setting)
                    db_info["configuration"][setting] = value
                except Exception as e:
                    db_info["errors"].append(f"Failed to get setting {setting}: {str(e)}")
            
            # Database statistics
            stats_queries = {
                "database_size": "SELECT pg_size_pretty(pg_database_size(current_database()))",
                "total_connections": "SELECT count(*) FROM pg_stat_activity",
                "active_connections": "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'",
                "idle_connections": "SELECT count(*) FROM pg_stat_activity WHERE state = 'idle'"
            }
            
            for key, query in stats_queries.items():
                try:
                    result = await conn.fetchval(query)
                    db_info["statistics"][key] = result
                except Exception as e:
                    db_info["errors"].append(f"Failed to get statistic {key}: {str(e)}")
            
            # Extensions information
            extensions_query = """
                SELECT 
                    extname as name,
                    extversion as version,
                    n.nspname as schema,
                    extrelocatable as relocatable
                FROM pg_extension e
                JOIN pg_namespace n ON n.oid = e.extnamespace
                ORDER BY extname
            """
            
            extensions = await conn.fetch(extensions_query)
            for ext in extensions:
                db_info["extensions"][ext["name"]] = {
                    "version": ext["version"],
                    "schema": ext["schema"],
                    "relocatable": ext["relocatable"]
                }
                
    except Exception as e:
        error_msg = f"Failed to get database info: {str(e)}"
        db_info["errors"].append(error_msg)
        logger.error("Failed to get database info", error=str(e))
    
    return db_info


def create_alembic_foundation() -> Dict[str, Any]:
    """
    Create foundation for Alembic database migrations.
    This sets up the basic structure needed for future schema management.
    
    Returns:
        Dict with setup status and any errors.
    """
    result = {
        "status": "success",
        "files_created": [],
        "errors": []
    }
    
    try:
        import os
        from pathlib import Path
        
        # Alembic directory structure
        db_path = Path(__file__).parent
        alembic_path = db_path / "alembic"
        
        # Create alembic directory if it doesn't exist
        alembic_path.mkdir(exist_ok=True)
        
        # Create versions directory
        versions_path = alembic_path / "versions"
        versions_path.mkdir(exist_ok=True)
        
        # Create alembic.ini (basic template)
        alembic_ini_content = """# Alembic configuration file for SEO Platform

[alembic]
# Path to migration scripts
script_location = alembic

# Template to use for generating migration file names
# file_template = %(year)d%(month).02d%(day).02d_%(hour).02d%(minute).02d_%(rev)s_%(slug)s

# Timezone for migration timestamps
timezone = 

# Max length of characters to apply to the "slug" field
truncate_slug_length = 40

# Set to 'true' to run the environment during the 'revision' command
revision_environment = false

# Set to 'true' to allow .pyc and .pyo files without a source .py file
sourceless = false

# Version locations - where to find migration versions
# version_locations = %(here)s/alembic/versions

# Version naming scheme
version_path_separator = os

# Database connection configuration
# Will be set programmatically by env.py using Pydantic settings
# sqlalchemy.url = 

[post_write_hooks]
# Post-write hooks for code formatting
hooks = black,ruff
black.type = console_scripts
black.entrypoint = black
black.options = --line-length 88

ruff.type = console_scripts  
ruff.entrypoint = ruff
ruff.options = check --fix

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
# format = %(levelname)-5.5s [%(name)s] %(message)s
# datefmt = %H:%M:%S"""
        
        alembic_ini_path = db_path.parent / "alembic.ini"
        if not alembic_ini_path.exists():
            with open(alembic_ini_path, "w") as f:
                f.write(alembic_ini_content)
            result["files_created"].append(str(alembic_ini_path))
        
        # Note: We're not creating the full Alembic environment yet
        # That will be done in the next task (P1-T006) when SQLAlchemy models are created
        
        logger.info("Alembic foundation created", path=str(alembic_path))
        
    except Exception as e:
        error_msg = f"Failed to create Alembic foundation: {str(e)}"
        result["errors"].append(error_msg)
        result["status"] = "failed"
        logger.error("Failed to create Alembic foundation", error=str(e))
    
    return result
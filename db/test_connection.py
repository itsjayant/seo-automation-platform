"""
Database connection validation script for SEO Automation Platform.

This script validates database connectivity, extension functionality,
and provides detailed diagnostics for troubleshooting.

Usage:
    python -m db.test_connection
    python db/test_connection.py --json
    python db/test_connection.py --verbose --test-extensions
"""

import asyncio
import json
import sys
import argparse
from datetime import datetime
from typing import Dict, Any
import structlog

# Setup structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Import database modules
def load_database_config():
    """Load database configuration with fallback options."""
    try:
        from config import get_settings
        settings = get_settings().database
        return {
            "host": settings.host,
            "port": settings.port,
            "database": settings.database,
            "username": settings.username,
            "password": settings.password,
            "min_connections": settings.min_connections,
            "max_connections": settings.max_connections,
        }
    except Exception as config_error:
        print(f"⚠️  Config loading failed: {config_error}")
        print("📝 Falling back to environment variables...")
        
        import os
        from dotenv import load_dotenv
        load_dotenv()  # Load .env file explicitly
        
        return {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "database": os.getenv("POSTGRES_DB", "seo_platform"), 
            "username": os.getenv("POSTGRES_USER", "seo"),
            "password": os.getenv("POSTGRES_PASSWORD"),
            "min_connections": int(os.getenv("POSTGRES_MIN_CONNECTIONS", "5")),
            "max_connections": int(os.getenv("POSTGRES_MAX_CONNECTIONS", "20")),
        }

try:
    # Test configuration loading
    db_config = load_database_config()
    if not db_config["password"]:
        print("❌ Database password not found in configuration")
        print("   Please set POSTGRES_PASSWORD in your .env file or environment variables")
        sys.exit(1)
    
    from db.connection import DatabaseManager
    from db.utils import validate_extensions, get_database_info
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)


async def run_basic_connection_test() -> Dict[str, Any]:
    """Run basic database connection test."""
    print("🔍 Testing database connection...")
    
    try:
        import asyncpg
        import time
        
        start_time = time.time()
        
        # Use manual configuration
        conn_params = {
            "host": db_config["host"],
            "port": db_config["port"],
            "user": db_config["username"], 
            "password": db_config["password"],
            "database": db_config["database"],
        }
        
        # Test connection
        conn = await asyncpg.connect(**conn_params)
        
        try:
            # Basic connectivity test
            test_result = await conn.fetchval("SELECT 1")
            if test_result != 1:
                raise Exception("Basic connectivity test failed")
            
            # Get database information
            db_name = await conn.fetchval("SELECT current_database()")
            version = await conn.fetchval("SELECT version()")
            
            connection_time = round((time.time() - start_time) * 1000, 2)
            
            result = {
                "status": "success",
                "connection_time": connection_time,
                "postgres_version": version,
                "database_name": db_name,
                "errors": []
            }
            
            print(f"✅ Connection successful in {connection_time}ms")
            print(f"   Database: {db_name}")
            print(f"   PostgreSQL: {version.split()[1] if version else 'Unknown'}")
                
        finally:
            await conn.close()
            
        return result
        
    except Exception as e:
        connection_time = round((time.time() - start_time) * 1000, 2)
        error_result = {
            "status": "failed",
            "connection_time": connection_time,
            "errors": [f"Connection test exception: {str(e)}"]
        }
        print(f"❌ Connection failed: {e}")
        return error_result


async def run_extension_validation() -> Dict[str, Any]:
    """Run comprehensive extension validation."""
    print("\n🧪 Validating database extensions...")
    
    try:
        import asyncpg
        
        # Connect directly using manual config
        conn_params = {
            "host": db_config["host"],
            "port": db_config["port"],
            "user": db_config["username"],
            "password": db_config["password"],
            "database": db_config["database"],
        }
        
        conn = await asyncpg.connect(**conn_params)
        
        try:
            result = await validate_extensions_manual(conn)
        finally:
            await conn.close()
        
        print(f"   Overall Status: {'✅ All functional' if result['status'] == 'success' else '⚠️ Issues detected'}")
        
        for ext_name, ext_info in result["extensions"].items():
            status_icon = "✅" if ext_info["functional"] else "❌"
            version_info = f"v{ext_info['version']}" if ext_info["version"] else "not installed"
            print(f"   {status_icon} {ext_name}: {version_info}")
            
            # Show test details if verbose
            if hasattr(sys, '_verbose') and sys._verbose and ext_info.get("test_results"):
                for feature, status in ext_info["test_results"].get("features", {}).items():
                    feature_icon = "✓" if status else "✗"
                    print(f"      {feature_icon} {feature}")
        
        if result.get("errors"):
            print("\n   Errors:")
            for error in result["errors"]:
                print(f"   ❌ {error}")
                
        return result
        
    except Exception as e:
        error_result = {
            "status": "failed", 
            "extensions": {},
            "errors": [f"Extension validation exception: {str(e)}"]
        }
        print(f"❌ Extension validation failed: {e}")
        return error_result


async def validate_extensions_manual(conn) -> Dict[str, Any]:
    """Manual extension validation that doesn't depend on configuration classes."""
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
                    from db.utils import test_timescaledb
                    ext_info["test_results"] = await test_timescaledb(conn)
                elif ext_name == "vector":
                    from db.utils import test_pgvector
                    ext_info["test_results"] = await test_pgvector(conn)
                elif ext_name == "uuid-ossp":
                    from db.utils import test_uuid_functions
                    ext_info["test_results"] = await test_uuid_functions(conn)
                elif ext_name == "pg_stat_statements":
                    from db.utils import test_pg_stat_statements
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


async def run_database_info_check() -> Dict[str, Any]:
    """Get comprehensive database information."""
    print("\n📊 Gathering database information...")
    
    try:
        import asyncpg
        
        # Connect directly using manual config
        conn_params = {
            "host": db_config["host"],
            "port": db_config["port"],
            "user": db_config["username"],
            "password": db_config["password"],
            "database": db_config["database"],
        }
        
        conn = await asyncpg.connect(**conn_params)
        
        try:
            result = await get_database_info_manual(conn)
        finally:
            await conn.close()
        
        # Server info
        if result.get("server"):
            print("   Server Information:")
            server_info = result["server"]
            if server_info.get("current_database"):
                print(f"     Database: {server_info['current_database']}")
            if server_info.get("current_user"):
                print(f"     User: {server_info['current_user']}")
            if server_info.get("server_uptime"):
                print(f"     Uptime: {server_info['server_uptime']}")
        
        # Statistics
        if result.get("statistics"):
            print("   Connection Statistics:")
            stats = result["statistics"]
            if stats.get("total_connections"):
                print(f"     Total connections: {stats['total_connections']}")
            if stats.get("active_connections"):
                print(f"     Active connections: {stats['active_connections']}")
            if stats.get("database_size"):
                print(f"     Database size: {stats['database_size']}")
        
        # Extensions summary
        if result.get("extensions"):
            ext_count = len(result["extensions"])
            print(f"   Extensions: {ext_count} installed")
        
        if result.get("errors"):
            print("\n   Information gathering errors:")
            for error in result["errors"]:
                print(f"     ❌ {error}")
                
        return result
        
    except Exception as e:
        error_result = {
            "server": {},
            "statistics": {},
            "extensions": {},
            "errors": [f"Database info check exception: {str(e)}"]
        }
        print(f"❌ Database info check failed: {e}")
        return error_result


async def get_database_info_manual(conn) -> Dict[str, Any]:
    """Manual database info gathering without configuration dependencies."""
    db_info = {
        "server": {},
        "configuration": {},
        "statistics": {},
        "extensions": {},
        "errors": []
    }
    
    try:
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
            JOIN pg_namespace n ON e.extnamespace = n.oid
            ORDER by extname
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


async def run_pool_health_check() -> Dict[str, Any]:
    """Test connection pool health (simplified version)."""
    print("\n🏊 Testing connection capabilities...")
    
    try:
        import asyncpg
        import psycopg2
        from psycopg2.extras import DictCursor
        
        result = {
            "status": "healthy",
            "connection_pools": {},
            "errors": []
        }
        
        # Test async connection
        try:
            conn_params = {
                "host": db_config["host"],
                "port": db_config["port"],
                "user": db_config["username"],
                "password": db_config["password"],
                "database": db_config["database"],
            }
            
            conn = await asyncpg.connect(**conn_params)
            version = await conn.fetchval("SELECT version()")
            await conn.close()
            
            result["connection_pools"]["async"] = "healthy"
            print("   ✅ Async connection: healthy")
            
        except Exception as e:
            result["connection_pools"]["async"] = f"failed: {str(e)}"
            result["errors"].append(f"Async connection failed: {str(e)}")
            print(f"   ❌ Async connection: failed")
        
        # Test sync connection
        try:
            sync_conn = psycopg2.connect(
                host=db_config["host"],
                port=db_config["port"],
                user=db_config["username"],
                password=db_config["password"],
                database=db_config["database"],
                cursor_factory=DictCursor
            )
            with sync_conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            sync_conn.close()
            
            result["connection_pools"]["sync"] = "healthy"
            print("   ✅ Sync connection: healthy")
            
        except Exception as e:
            result["connection_pools"]["sync"] = f"failed: {str(e)}"
            result["errors"].append(f"Sync connection failed: {str(e)}")
            print(f"   ❌ Sync connection: failed")
        
        # Overall status
        if result["errors"]:
            result["status"] = "unhealthy"
            
        return result
        
    except Exception as e:
        error_result = {
            "status": "unhealthy",
            "connection_pools": {},
            "errors": [f"Pool health check exception: {str(e)}"]
        }
        print(f"❌ Connection capability check failed: {e}")
        return error_result


async def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="SEO Platform Database Connection Validator")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--test-extensions", action="store_true", help="Run extension functionality tests")
    parser.add_argument("--test-pools", action="store_true", help="Test connection pool health")
    parser.add_argument("--full", action="store_true", help="Run all tests")
    
    args = parser.parse_args()
    
    # Set verbose flag for module access
    sys._verbose = args.verbose
    
    # Determine which tests to run
    run_extensions = args.test_extensions or args.full
    run_pools = args.test_pools or args.full
    run_info = args.verbose or args.full
    
    # Test results container
    test_results = {
        "timestamp": datetime.now().isoformat(),
        "tests": {},
        "overall_status": "success"
    }
    
    if not args.json:
        print("🚀 SEO Platform Database Connection Validator")
        print("=" * 50)
    
    # Always run basic connection test
    test_results["tests"]["connection"] = await run_basic_connection_test()
    
    # Run extension tests if requested
    if run_extensions:
        test_results["tests"]["extensions"] = await run_extension_validation()
    
    # Run database info check if requested
    if run_info:
        test_results["tests"]["database_info"] = await run_database_info_check()
    
    # Run pool health check if requested
    if run_pools:
        test_results["tests"]["pool_health"] = await run_pool_health_check()
    
    # Determine overall status
    failed_tests = []
    for test_name, test_result in test_results["tests"].items():
        test_status = test_result.get("status")
        if test_status in ["failed", "unhealthy"] or (test_status == "partial" and test_name == "extensions"):
            failed_tests.append(test_name)
            test_results["overall_status"] = "failed"
    
    # Output results
    if args.json:
        print(json.dumps(test_results, indent=2, default=str))
    else:
        print("\n" + "=" * 50)
        if test_results["overall_status"] == "success":
            print("🎉 All tests passed! Database is ready for use.")
        else:
            print(f"⚠️ Some tests failed: {', '.join(failed_tests)}")
            print("Review the output above for detailed error information.")
        
        # Show configuration summary
        try:
            print(f"\nConfiguration:")
            print(f"  Host: {db_config['host']}:{db_config['port']}")
            print(f"  Database: {db_config['database']}")
            print(f"  User: {db_config['username']}")
            print(f"  Pool size: {db_config['min_connections']}-{db_config['max_connections']} connections")
        except Exception as e:
            print(f"\nConfiguration display error: {e}")
    
    # Exit with appropriate code
    sys.exit(0 if test_results["overall_status"] == "success" else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        logger.exception("Unexpected error in test runner")
        sys.exit(1)
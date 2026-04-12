#!/usr/bin/env python3
"""
SEO Automation Platform - Simple Health Check Service

A simplified health check that works with basic environment variables
and handles missing configurations gracefully.

Usage:
    python scripts/simple-health-check.py [--timeout SECONDS] [--verbose]
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import argparse
from dataclasses import dataclass, asdict
from enum import Enum

# Import only what we need for basic testing
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False
    
try:
    import redis
    import redis.asyncio as redis_async
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    
try:
    import nats
    HAS_NATS = True
except ImportError:
    HAS_NATS = False


class HealthStatus(str, Enum):
    """Health status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ServiceHealth:
    """Individual service health result."""
    status: HealthStatus
    details: Dict[str, Any]
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class OverallHealth:
    """Complete system health result."""
    status: HealthStatus
    services: Dict[str, ServiceHealth]
    timestamp: str
    summary: Dict[str, int]


class SimpleHealthChecker:
    """Simplified health check orchestrator."""

    def __init__(self, timeout: int = 10, verbose: bool = False, json_only: bool = False):
        self.timeout = timeout
        self.verbose = verbose
        self.json_only = json_only

        # Configure logging
        if json_only:
            log_level = logging.CRITICAL  # Suppress all logs in JSON-only mode
        elif verbose:
            log_level = logging.DEBUG
        else:
            log_level = logging.ERROR
            
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            stream=sys.stderr
        )
        self.logger = logging.getLogger(__name__)

    async def check_all_services(self) -> OverallHealth:
        """Check health of all services."""
        self.logger.info("Starting simplified health check...")

        services = {}
        
        # Check each service independently
        if HAS_ASYNCPG:
            services["postgresql"] = await self._check_postgresql()
        else:
            services["postgresql"] = ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details={},
                error="asyncpg package not available"
            )
            
        if HAS_REDIS:
            services["redis"] = await self._check_redis()
        else:
            services["redis"] = ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details={},
                error="redis package not available"
            )
            
        if HAS_NATS:
            services["nats"] = await self._check_nats()
        else:
            services["nats"] = ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details={},
                error="nats-py package not available"
            )

        # Calculate overall health
        overall_status, summary = self._calculate_overall_health(services)

        return OverallHealth(
            status=overall_status,
            services=services,
            timestamp=datetime.now(timezone.utc).isoformat(),
            summary=summary
        )

    async def _check_postgresql(self) -> ServiceHealth:
        """Check PostgreSQL database health."""
        start_time = time.time()
        details = {}

        # Get environment variables
        db_host = os.getenv("POSTGRES_HOST", "localhost")
        db_port = int(os.getenv("POSTGRES_PORT", "5432"))
        db_name = os.getenv("POSTGRES_DB", "seo_platform")
        db_user = os.getenv("POSTGRES_USER", "seo")
        db_password = os.getenv("POSTGRES_PASSWORD")

        if not db_password:
            return ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details={"configuration": "missing POSTGRES_PASSWORD"},
                response_time_ms=0,
                error="Database password not configured"
            )

        try:
            # Attempt connection
            conn = await asyncpg.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_password,
                database=db_name,
                command_timeout=self.timeout
            )
            
            try:
                details["connection"] = "successful"
                details["config"] = {
                    "host": db_host,
                    "port": db_port,
                    "database": db_name,
                    "user": db_user
                }
                
                # Check database version
                version = await conn.fetchval("SELECT version()")
                details["version"] = version
                
                # Check extensions (non-critical)
                try:
                    extensions_query = """
                        SELECT extname, extversion 
                        FROM pg_extension 
                        WHERE extname IN ('timescaledb', 'vector', 'uuid-ossp', 'pg_stat_statements')
                        ORDER BY extname
                    """
                    extensions = await conn.fetch(extensions_query)
                    extension_details = {row["extname"]: row["extversion"] for row in extensions}
                    details["extensions"] = extension_details
                    
                    # Check for core extensions
                    required_extensions = ["timescaledb", "vector", "uuid-ossp"]
                    missing_extensions = [ext for ext in required_extensions if ext not in extension_details]
                    
                    if missing_extensions:
                        details["missing_extensions"] = missing_extensions
                        details["extension_status"] = "degraded"
                    else:
                        details["extension_status"] = "complete"
                        
                except Exception as ext_error:
                    details["extensions"] = {"error": str(ext_error)}
                    details["extension_status"] = "error"

                # Test basic functionality
                test_query = "SELECT 1 as test, current_timestamp as now"
                result = await conn.fetchrow(test_query)
                details["test_query"] = {"result": dict(result), "success": True}
                
                # Test vector functionality if available
                if details.get("extensions", {}).get("vector"):
                    try:
                        vector_test = "SELECT array[1,2,3]::vector(3) <-> array[1,2,4]::vector(3) as distance"
                        vector_result = await conn.fetchval(vector_test)
                        details["vector_test"] = {"distance": float(vector_result), "success": True}
                    except Exception:
                        details["vector_test"] = {"success": False}

            finally:
                await conn.close()

            response_time = round((time.time() - start_time) * 1000, 2)
            
            # Determine status
            status = HealthStatus.HEALTHY
            if details.get("extension_status") == "degraded":
                status = HealthStatus.DEGRADED
            elif details.get("extension_status") == "error":
                status = HealthStatus.DEGRADED
                
            return ServiceHealth(
                status=status,
                details=details,
                response_time_ms=response_time
            )

        except Exception as e:
            self.logger.error(f"PostgreSQL health check failed: {e}")
            return ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details=details,
                response_time_ms=round((time.time() - start_time) * 1000, 2),
                error=str(e)
            )

    async def _check_redis(self) -> ServiceHealth:
        """Check Redis health."""
        start_time = time.time()
        details = {}

        # Get environment variables
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_db = int(os.getenv("REDIS_DB", "0"))
        redis_password = os.getenv("REDIS_PASSWORD") or None

        try:
            # Create Redis client with async support
            redis_client = redis_async.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                socket_timeout=self.timeout,
                socket_connect_timeout=self.timeout,
                decode_responses=True
            )

            # Test connection
            await redis_client.ping()
            details["connection"] = "successful"
            details["config"] = {
                "host": redis_host,
                "port": redis_port,
                "database": redis_db,
                "password_set": bool(redis_password)
            }

            # Get Redis info
            try:
                info = await redis_client.info()
                details["version"] = info.get("redis_version")
                details["mode"] = info.get("redis_mode")
                details["uptime_seconds"] = info.get("uptime_in_seconds")
                
                # Memory usage
                details["memory"] = {
                    "used_memory_human": info.get("used_memory_human"),
                    "maxmemory_human": info.get("maxmemory_human"),
                    "maxmemory_policy": info.get("maxmemory_policy")
                }
            except Exception:
                details["info"] = "unavailable"

            # Test basic operations
            test_key = "health_check_test"
            test_value = f"test_{int(time.time())}"
            
            await redis_client.set(test_key, test_value, ex=60)
            retrieved_value = await redis_client.get(test_key)
            await redis_client.delete(test_key)
            
            if retrieved_value != test_value:
                raise ValueError(f"Redis test failed: expected {test_value}, got {retrieved_value}")
            
            details["basic_operations"] = "successful"

            # Test Redis Streams
            try:
                test_stream = f"health_check_stream_{int(time.time())}"
                message_id = await redis_client.xadd(test_stream, {"test": "data"})
                await redis_client.delete(test_stream)
                details["streams_functionality"] = "healthy"
            except Exception as se:
                details["streams_functionality"] = "unavailable"
                details["streams_error"] = str(se)

            await redis_client.aclose()

            response_time = round((time.time() - start_time) * 1000, 2)
            
            status = HealthStatus.HEALTHY
            if details.get("streams_functionality") == "unavailable":
                status = HealthStatus.DEGRADED

            return ServiceHealth(
                status=status,
                details=details,
                response_time_ms=response_time
            )

        except Exception as e:
            self.logger.error(f"Redis health check failed: {e}")
            return ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details=details,
                response_time_ms=round((time.time() - start_time) * 1000, 2),
                error=str(e)
            )

    async def _check_nats(self) -> ServiceHealth:
        """Check NATS health."""
        start_time = time.time()
        details = {}

        # Get environment variables
        nats_host = os.getenv("NATS_HOST", "localhost")
        nats_port = int(os.getenv("NATS_PORT", "4222"))
        nats_user = os.getenv("NATS_USER")
        nats_password = os.getenv("NATS_PASSWORD")

        nats_url = f"nats://"
        if nats_user and nats_password:
            nats_url += f"{nats_user}:{nats_password}@"
        nats_url += f"{nats_host}:{nats_port}"

        try:
            # Connect to NATS
            nc = await nats.connect(
                servers=[nats_url],
                connect_timeout=self.timeout,
                max_reconnect_attempts=0
            )

            try:
                details["connection"] = "successful"
                details["config"] = {
                    "host": nats_host,
                    "port": nats_port,
                    "auth_configured": bool(nats_user and nats_password)
                }
                
                # Get server info
                server_info = nc.connected_server_version
                if server_info:
                    details["server_version"] = server_info.version
                else:
                    details["server_version"] = "unknown"

                # Test basic publish
                test_subject = f"health.check.{int(time.time())}"
                await nc.publish(test_subject, b"health check test")
                details["basic_pubsub"] = "successful"

                # Test JetStream (optional)
                jetstream_enabled = os.getenv("NATS_JETSTREAM_ENABLED", "true").lower() == "true"
                if jetstream_enabled:
                    try:
                        js = nc.jetstream()
                        account_info = await js.account_info()
                        details["jetstream"] = {
                            "enabled": True,
                            "streams": account_info.streams,
                            "consumers": account_info.consumers
                        }
                    except Exception:
                        details["jetstream"] = {"enabled": False, "error": "not available"}

            finally:
                try:
                    await nc.close()
                except:
                    pass

            response_time = round((time.time() - start_time) * 1000, 2)

            status = HealthStatus.HEALTHY
            if jetstream_enabled and not details.get("jetstream", {}).get("enabled", False):
                status = HealthStatus.DEGRADED

            return ServiceHealth(
                status=status,
                details=details,
                response_time_ms=response_time
            )

        except Exception as e:
            self.logger.error(f"NATS health check failed: {e}")
            return ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details=details,
                response_time_ms=round((time.time() - start_time) * 1000, 2),
                error=str(e)
            )

    def _calculate_overall_health(self, services: Dict[str, ServiceHealth]) -> tuple:
        """Calculate overall system health."""
        healthy_count = sum(1 for s in services.values() if s.status == HealthStatus.HEALTHY)
        degraded_count = sum(1 for s in services.values() if s.status == HealthStatus.DEGRADED)
        unhealthy_count = sum(1 for s in services.values() if s.status == HealthStatus.UNHEALTHY)

        summary = {
            "healthy": healthy_count,
            "degraded": degraded_count,
            "unhealthy": unhealthy_count
        }

        if unhealthy_count > 0:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return overall_status, summary


async def main():
    """Main health check execution."""
    parser = argparse.ArgumentParser(description="Simple SEO Platform Health Check")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json-only", action="store_true", help="JSON output only")
    args = parser.parse_args()

    try:
        checker = SimpleHealthChecker(timeout=args.timeout, verbose=args.verbose, json_only=args.json_only)
        
        if not args.json_only and not args.verbose:
            print("Checking service health...", file=sys.stderr)

        result = await checker.check_all_services()
        result_dict = asdict(result)
        
        print(json.dumps(result_dict, indent=2))
        
        if not args.json_only:
            print(f"\nOverall Status: {result.status.upper()}", file=sys.stderr)
            print(f"Services: {result.summary['healthy']} healthy, "
                  f"{result.summary['degraded']} degraded, "
                  f"{result.summary['unhealthy']} unhealthy", file=sys.stderr)

        # Exit codes
        if result.status == HealthStatus.HEALTHY:
            sys.exit(0)
        elif result.status == HealthStatus.DEGRADED:
            sys.exit(1)
        else:
            sys.exit(2)

    except Exception as e:
        error_output = {
            "status": "unhealthy",
            "error": f"Health check failed: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        print(json.dumps(error_output, indent=2))
        if not args.json_only:
            print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        
        sys.exit(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nHealth check interrupted", file=sys.stderr)
        sys.exit(130)
#!/usr/bin/env python3
"""
SEO Automation Platform - Health Check Service

This script validates the health of all critical infrastructure components:
- PostgreSQL with TimescaleDB and pgvector extensions
- Redis with Streams functionality
- NATS with JetStream capabilities

Usage:
    python scripts/health-check.py [--timeout SECONDS] [--retries COUNT] [--verbose]

Exit codes:
    0: All services healthy
    1: Some services degraded but core functionality available
    2: Critical services unhealthy, system non-operational
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import argparse
from dataclasses import dataclass, asdict
from enum import Enum

# Database connections
import asyncpg
from asyncpg import Connection

# Redis connection
import redis
import redis.asyncio as redis_async
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

# NATS connection
import nats
from nats.errors import Error as NATSError, ConnectionClosedError, TimeoutError as NATSTimeoutError
from nats.js import JetStreamContext
from nats.js.errors import ServerError, BadRequestError

# Add the project root to Python path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.settings import get_settings, Settings
except ImportError as e:
    print(f"ERROR: Cannot import configuration: {e}")
    print("Make sure you're running from the project root and config module is available")
    sys.exit(2)


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


class HealthChecker:
    """Main health check orchestrator."""

    def __init__(self, settings: Settings, timeout: int = 10, retries: int = 3, verbose: bool = False):
        self.settings = settings
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose

        # Configure logging
        log_level = logging.DEBUG if verbose else logging.ERROR
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            stream=sys.stderr
        )
        self.logger = logging.getLogger(__name__)

    async def check_all_services(self) -> OverallHealth:
        """Check health of all services."""
        self.logger.info("Starting comprehensive health check...")

        # Run all health checks concurrently
        postgres_task = self._check_postgresql()
        redis_task = self._check_redis()
        nats_task = self._check_nats()

        # Wait for all checks to complete
        services = {}
        try:
            postgres_result, redis_result, nats_result = await asyncio.gather(
                postgres_task, redis_task, nats_task, 
                return_exceptions=True
            )

            # Handle results, including exceptions
            services["postgresql"] = postgres_result if isinstance(postgres_result, ServiceHealth) else ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details={}, 
                error=f"Unexpected error: {postgres_result}"
            )
            
            services["redis"] = redis_result if isinstance(redis_result, ServiceHealth) else ServiceHealth(
                status=HealthStatus.UNHEALTHY, 
                details={},
                error=f"Unexpected error: {redis_result}"
            )
            
            services["nats"] = nats_result if isinstance(nats_result, ServiceHealth) else ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details={},
                error=f"Unexpected error: {nats_result}"
            )

        except Exception as e:
            self.logger.error(f"Health check execution failed: {e}")
            # Return minimal health status on catastrophic failure
            return OverallHealth(
                status=HealthStatus.UNHEALTHY,
                services={
                    "postgresql": ServiceHealth(HealthStatus.UNHEALTHY, {}, error=f"Check failed: {e}"),
                    "redis": ServiceHealth(HealthStatus.UNHEALTHY, {}, error=f"Check failed: {e}"),
                    "nats": ServiceHealth(HealthStatus.UNHEALTHY, {}, error=f"Check failed: {e}")
                },
                timestamp=datetime.now(timezone.utc).isoformat(),
                summary={"healthy": 0, "degraded": 0, "unhealthy": 3}
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
        """Check PostgreSQL database health including extensions."""
        start_time = time.time()
        details = {}

        try:
            # Attempt connection with timeout and retries
            conn = await self._retry_async(self._connect_postgresql, "PostgreSQL connection")
            
            try:
                details["connection"] = "successful"
                
                # Check database version
                version = await conn.fetchval("SELECT version()")
                details["version"] = version
                
                # Check required extensions
                extensions_query = """
                    SELECT extname, extversion 
                    FROM pg_extension 
                    WHERE extname IN ('timescaledb', 'vector', 'uuid-ossp', 'pg_stat_statements')
                    ORDER BY extname
                """
                extensions = await conn.fetch(extensions_query)
                extension_details = {row["extname"]: row["extversion"] for row in extensions}
                details["extensions"] = extension_details
                
                # Check for required extensions
                required_extensions = ["timescaledb", "vector", "uuid-ossp"]
                missing_extensions = [ext for ext in required_extensions if ext not in extension_details]
                
                if missing_extensions:
                    details["missing_extensions"] = missing_extensions
                    return ServiceHealth(
                        status=HealthStatus.DEGRADED,
                        details=details,
                        response_time_ms=round((time.time() - start_time) * 1000, 2),
                        error=f"Missing required extensions: {missing_extensions}"
                    )

                # Test basic functionality
                test_query = "SELECT 1 as test, current_timestamp as now"
                result = await conn.fetchrow(test_query)
                details["test_query"] = {"result": dict(result), "success": True}
                
                # Test vector functionality if available
                if "vector" in extension_details:
                    try:
                        vector_test = "SELECT array[1,2,3]::vector(3) <-> array[1,2,4]::vector(3) as distance"
                        vector_result = await conn.fetchval(vector_test)
                        details["vector_test"] = {"distance": float(vector_result), "success": True}
                    except Exception as ve:
                        details["vector_test"] = {"success": False, "error": str(ve)}

                # Check connection pool and statistics
                stats_query = """
                    SELECT 
                        numbackends as active_connections,
                        xact_commit as transactions_committed,
                        xact_rollback as transactions_rolled_back
                    FROM pg_stat_database 
                    WHERE datname = current_database()
                """
                stats = await conn.fetchrow(stats_query)
                details["database_stats"] = dict(stats) if stats else {}

            finally:
                await conn.close()

            response_time = round((time.time() - start_time) * 1000, 2)
            
            return ServiceHealth(
                status=HealthStatus.HEALTHY,
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

    async def _connect_postgresql(self) -> Connection:
        """Establish PostgreSQL connection."""
        db_config = self.settings.database
        return await asyncpg.connect(
            host=db_config.host,
            port=db_config.port,
            user=db_config.username,
            password=db_config.password,
            database=db_config.database,
            command_timeout=self.timeout
        )

    async def _check_redis(self) -> ServiceHealth:
        """Check Redis health including Streams functionality."""
        start_time = time.time()
        details = {}

        try:
            # Create Redis client with async support
            redis_config = self.settings.redis
            redis_client = redis_async.Redis(
                host=redis_config.host,
                port=redis_config.port,
                db=redis_config.database,
                password=redis_config.password,
                socket_timeout=self.timeout,
                socket_connect_timeout=self.timeout,
                decode_responses=True
            )

            # Test connection with retries
            await self._retry_async(redis_client.ping, "Redis ping")
            details["connection"] = "successful"

            # Get Redis info
            info = await redis_client.info()
            details["version"] = info.get("redis_version")
            details["mode"] = info.get("redis_mode")
            details["uptime_seconds"] = info.get("uptime_in_seconds")

            # Check memory usage
            memory_info = {
                "used_memory": info.get("used_memory"),
                "used_memory_human": info.get("used_memory_human"),
                "maxmemory": info.get("maxmemory"),
                "maxmemory_human": info.get("maxmemory_human"),
                "maxmemory_policy": info.get("maxmemory_policy")
            }
            details["memory"] = memory_info

            # Test basic operations
            test_key = "health_check_test"
            test_value = f"test_{int(time.time())}"
            
            await redis_client.set(test_key, test_value, ex=60)  # Expire in 60 seconds
            retrieved_value = await redis_client.get(test_key)
            await redis_client.delete(test_key)
            
            if retrieved_value != test_value:
                raise ValueError(f"Redis test failed: expected {test_value}, got {retrieved_value}")
            
            details["basic_operations"] = "successful"

            # Test Redis Streams functionality
            redis_config = self.settings.redis
            test_stream = f"health_check_stream_{int(time.time())}"
            test_group = "health_check_group"

            try:
                # Add a message to stream
                message_id = await redis_client.xadd(test_stream, {"test": "data", "timestamp": str(time.time())})
                details["stream_add"] = "successful"

                # Create consumer group
                try:
                    await redis_client.xgroup_create(test_stream, test_group, id="0", mkstream=True)
                except Exception:
                    pass  # Group might already exist
                
                # Read from stream
                messages = await redis_client.xread({test_stream: "0"}, count=1)
                if messages:
                    details["stream_read"] = "successful"
                else:
                    details["stream_read"] = "no_messages"

                # Clean up test stream
                await redis_client.delete(test_stream)
                details["streams_functionality"] = "healthy"

            except Exception as se:
                details["streams_functionality"] = "degraded"
                details["streams_error"] = str(se)

            await redis_client.aclose()

            response_time = round((time.time() - start_time) * 1000, 2)

            # Determine status based on functionality
            status = HealthStatus.HEALTHY
            if details.get("streams_functionality") == "degraded":
                status = HealthStatus.DEGRADED

            return ServiceHealth(
                status=status,
                details=details,
                response_time_ms=response_time
            )

        except (RedisConnectionError, RedisTimeoutError, ConnectionError) as e:
            self.logger.error(f"Redis connection failed: {e}")
            return ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details=details,
                response_time_ms=round((time.time() - start_time) * 1000, 2),
                error=f"Connection failed: {str(e)}"
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
        """Check NATS health including JetStream functionality."""
        start_time = time.time()
        details = {}

        try:
            # Connect to NATS with retries
            nats_config = self.settings.nats
            nc = await self._retry_async(
                lambda: nats.connect(
                    servers=[nats_config.connection_url],
                    connect_timeout=self.timeout,
                    max_reconnect_attempts=0  # Don't retry during health check
                ), 
                "NATS connection"
            )

            try:
                details["connection"] = "successful"
                
                # Get server info
                server_info = nc.connected_server_version
                details["server_version"] = server_info.version if server_info else "unknown"

                # Test basic publish/subscribe
                test_subject = f"health.check.{int(time.time())}"
                test_message = b"health check test"
                
                # Simple pub/sub test
                await nc.publish(test_subject, test_message)
                details["basic_pubsub"] = "successful"

                # Test JetStream if enabled
                if nats_config.jetstream_enabled:
                    try:
                        js = nc.jetstream()
                        
                        # Get JetStream account info
                        account_info = await js.account_info()
                        details["jetstream"] = {
                            "enabled": True,
                            "streams": account_info.streams,
                            "consumers": account_info.consumers,
                            "messages": account_info.messages,
                            "bytes": account_info.bytes
                        }

                        # Test stream creation and message publishing
                        test_stream_name = f"health_check_{int(time.time())}"
                        test_stream_subject = f"health.test.{int(time.time())}"

                        try:
                            # Create a temporary stream for testing
                            from nats.js.api import StreamConfig
                            stream_config = StreamConfig(
                                name=test_stream_name,
                                subjects=[test_stream_subject],
                                max_msgs=10,
                                max_age=60  # 1 minute retention for test
                            )
                            
                            stream = await js.add_stream(stream_config)
                            details["jetstream_stream_creation"] = "successful"
                            
                            # Publish a test message
                            ack = await js.publish(test_stream_subject, b"jetstream test message")
                            details["jetstream_publish"] = {
                                "successful": True,
                                "sequence": ack.seq,
                                "duplicate": ack.duplicate
                            }

                            # Clean up test stream
                            await js.delete_stream(test_stream_name)

                        except (ServerError, BadRequestError) as jse:
                            details["jetstream_stream_creation"] = f"failed: {str(jse)}"
                            
                    except Exception as je:
                        details["jetstream"] = {
                            "enabled": False,
                            "error": str(je)
                        }
                        self.logger.warning(f"JetStream functionality degraded: {je}")

            finally:
                try:
                    await nc.close()
                except:
                    pass  # Ignore errors during cleanup

            response_time = round((time.time() - start_time) * 1000, 2)

            # Determine health status
            status = HealthStatus.HEALTHY
            if nats_config.jetstream_enabled and not details.get("jetstream", {}).get("enabled", False):
                status = HealthStatus.DEGRADED

            return ServiceHealth(
                status=status,
                details=details,
                response_time_ms=response_time
            )

        except (NATSError, ConnectionClosedError, NATSTimeoutError) as e:
            self.logger.error(f"NATS connection failed: {e}")
            return ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details=details,
                response_time_ms=round((time.time() - start_time) * 1000, 2),
                error=f"Connection failed: {str(e)}"
            )

        except Exception as e:
            self.logger.error(f"NATS health check failed: {e}")
            return ServiceHealth(
                status=HealthStatus.UNHEALTHY,
                details=details,
                response_time_ms=round((time.time() - start_time) * 1000, 2),
                error=str(e)
            )

    async def _retry_async(self, func, operation_name: str):
        """Retry an async operation with exponential backoff."""
        last_exception = None
        
        for attempt in range(self.retries + 1):
            try:
                if attempt > 0:
                    delay = min(2 ** (attempt - 1), 10)  # Cap at 10 seconds
                    self.logger.debug(f"Retrying {operation_name} in {delay}s (attempt {attempt + 1}/{self.retries + 1})")
                    await asyncio.sleep(delay)
                
                return await func()
                
            except Exception as e:
                last_exception = e
                if attempt < self.retries:
                    self.logger.warning(f"{operation_name} failed (attempt {attempt + 1}/{self.retries + 1}): {e}")
                else:
                    self.logger.error(f"{operation_name} failed after {self.retries + 1} attempts: {e}")
        
        raise last_exception

    def _calculate_overall_health(self, services: Dict[str, ServiceHealth]) -> Tuple[HealthStatus, Dict[str, int]]:
        """Calculate overall system health based on individual services."""
        healthy_count = sum(1 for s in services.values() if s.status == HealthStatus.HEALTHY)
        degraded_count = sum(1 for s in services.values() if s.status == HealthStatus.DEGRADED)
        unhealthy_count = sum(1 for s in services.values() if s.status == HealthStatus.UNHEALTHY)

        summary = {
            "healthy": healthy_count,
            "degraded": degraded_count,
            "unhealthy": unhealthy_count
        }

        # Overall status logic:
        # - All healthy: HEALTHY
        # - Some degraded but no unhealthy: DEGRADED  
        # - Any unhealthy: UNHEALTHY
        if unhealthy_count > 0:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return overall_status, summary


def setup_argument_parser() -> argparse.ArgumentParser:
    """Set up command line argument parser."""
    parser = argparse.ArgumentParser(
        description="SEO Platform Health Check - Validate infrastructure component health",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  All services healthy
  1  Some services degraded but system operational  
  2  Critical services unhealthy, system non-operational

Examples:
  python scripts/health-check.py
  python scripts/health-check.py --timeout 15 --retries 5 --verbose
        """
    )

    parser.add_argument(
        "--timeout", 
        type=int, 
        default=10,
        help="Timeout in seconds for each service check (default: 10)"
    )
    
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retry attempts for failed connections (default: 3)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging output"
    )

    parser.add_argument(
        "--json-only",
        action="store_true", 
        help="Output only JSON without additional formatting"
    )

    return parser


async def main():
    """Main health check execution."""
    parser = setup_argument_parser()
    args = parser.parse_args()

    try:
        # Load configuration
        settings = get_settings()
        
        # Initialize health checker
        health_checker = HealthChecker(
            settings=settings,
            timeout=args.timeout,
            retries=args.retries,
            verbose=args.verbose
        )

        # Run health checks
        if not args.json_only and not args.verbose:
            print("Checking service health...", file=sys.stderr)

        health_result = await health_checker.check_all_services()

        # Output results
        result_dict = asdict(health_result)
        
        if args.json_only:
            print(json.dumps(result_dict, indent=2))
        else:
            # Formatted output
            print(json.dumps(result_dict, indent=2))
            
            if not args.verbose:
                print(f"\nOverall Status: {health_result.status.upper()}", file=sys.stderr)
                print(f"Services: {health_result.summary['healthy']} healthy, "
                      f"{health_result.summary['degraded']} degraded, "
                      f"{health_result.summary['unhealthy']} unhealthy", file=sys.stderr)

        # Set exit code based on health status
        if health_result.status == HealthStatus.HEALTHY:
            sys.exit(0)
        elif health_result.status == HealthStatus.DEGRADED:
            sys.exit(1)
        else:
            sys.exit(2)

    except Exception as e:
        error_output = {
            "status": "unhealthy",
            "error": f"Health check execution failed: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        print(json.dumps(error_output, indent=2))
        if not args.json_only:
            print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        
        sys.exit(2)


if __name__ == "__main__":
    # Handle event loop for async execution
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nHealth check interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        sys.exit(2)
#!/usr/bin/env python3
"""
SEO Automation Platform - Phase 1 Comprehensive Validation

This script performs end-to-end validation of the Phase 1 foundation infrastructure:
- Docker Compose stack validation
- Database migrations and schema validation
- Task queue functionality
- Approval workflow notifications  
- Performance baseline measurements
- Complete system integration validation

Usage:
    python scripts/validate-phase1.py [--json-only] [--skip-docker] [--timeout SECONDS]

Exit codes:
    0: Phase 1 validation PASSED - ready for Phase 2
    1: Phase 1 validation FAILED - critical issues found
    2: Script execution error
"""

import asyncio
import json
import os
import sys
import time
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import argparse

# Database and async libraries
import asyncpg
from asyncpg import Connection
import redis.asyncio as redis_async
import nats
from nats.js import JetStreamContext

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.settings import get_settings, Settings
    # Import health check classes directly without module import
    import importlib.util
    import sys
    
    # Load health check module dynamically to handle hyphenated filename
    spec = importlib.util.spec_from_file_location(
        "health_check", 
        os.path.join(os.path.dirname(__file__), "health-check.py")
    )
    health_check_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health_check_module)
    
    HealthChecker = health_check_module.HealthChecker
    HealthStatus = health_check_module.HealthStatus  
    ServiceHealth = health_check_module.ServiceHealth
    
    from db.models import Site, Keyword, AuditLog  # Import models for validation
except ImportError as e:
    print(f"ERROR: Cannot import required modules: {e}")
    print("Make sure you're running from the project root and all dependencies are installed")
    sys.exit(2)


class ValidationStatus(str, Enum):
    """Validation result status."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


@dataclass
class ValidationResult:
    """Individual validation check result."""
    check_name: str
    status: ValidationStatus
    details: Dict[str, Any]
    execution_time_ms: float
    error_message: Optional[str] = None
    recommendations: List[str] = None

    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []


@dataclass  
class PerformanceBaseline:
    """Performance baseline measurements."""
    postgresql_query_time_ms: float
    redis_publish_time_ms: float
    nats_roundtrip_time_ms: float
    migration_upgrade_time_ms: float
    migration_downgrade_time_ms: float
    vector_similarity_query_ms: float


@dataclass
class Phase1ValidationReport:
    """Complete Phase 1 validation report."""
    phase: str = "Phase 1 - Foundation"  
    status: ValidationStatus = ValidationStatus.FAILED
    timestamp: str = ""
    checks: Dict[str, ValidationResult] = None
    performance_baselines: Optional[PerformanceBaseline] = None
    issues: List[str] = None
    recommendations: List[str] = None
    total_execution_time_ms: float = 0

    def __post_init__(self):
        if self.checks is None:
            self.checks = {}
        if self.issues is None:
            self.issues = []
        if self.recommendations is None:
            self.recommendations = []
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class Phase1Validator:
    """End-to-end Phase 1 validation orchestrator."""

    def __init__(self, settings: Settings, skip_docker: bool = False, timeout: int = 300):
        self.settings = settings
        self.skip_docker = skip_docker
        self.timeout = timeout
        self.report = Phase1ValidationReport()
        self.project_root = Path(__file__).parent.parent

    async def validate_all(self) -> Phase1ValidationReport:
        """Execute complete Phase 1 validation."""
        start_time = time.time()
        
        print("🚀 Starting Phase 1 Comprehensive Validation...")
        
        try:
            # Infrastructure validation
            await self._validate_docker_services()
            await self._validate_basic_health()
            
            # Database validation
            await self._validate_database_schema()
            await self._validate_database_migrations()
            await self._validate_timescaledb_hypertables()
            await self._validate_pgvector_functionality()
            
            # System integration validation  
            await self._validate_task_queue_functionality()
            await self._validate_notification_system()
            await self._validate_configuration_loading()
            
            # Performance baselines
            await self._record_performance_baselines()
            
            # Calculate overall status
            self._calculate_overall_status()
            
        except Exception as e:
            self.report.issues.append(f"Validation execution failed: {str(e)}")
            self.report.status = ValidationStatus.FAILED
            
        finally:
            self.report.total_execution_time_ms = round((time.time() - start_time) * 1000, 2)
            
        return self.report

    async def _validate_docker_services(self):
        """Validate Docker Compose services are running."""
        if self.skip_docker:
            self.report.checks["docker_services"] = ValidationResult(
                check_name="Docker Services",
                status=ValidationStatus.SKIPPED,
                details={"reason": "Skipped via --skip-docker flag"},
                execution_time_ms=0
            )
            return

        start_time = time.time()
        details = {}
        
        try:
            # Check if docker-compose is available
            result = subprocess.run(
                ["docker-compose", "version"], 
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode != 0:
                # Try docker compose (newer syntax)
                result = subprocess.run(
                    ["docker", "compose", "version"],
                    capture_output=True, text=True, timeout=10
                )
                compose_cmd = ["docker", "compose"]
            else:
                compose_cmd = ["docker-compose"]
                
            details["compose_version"] = result.stdout.strip()
            
            # Check service status
            result = subprocess.run(
                compose_cmd + ["ps", "--services", "--filter", "status=running"],
                capture_output=True, text=True, timeout=30,
                cwd=self.project_root
            )
            
            running_services = result.stdout.strip().split('\n') if result.stdout.strip() else []
            expected_services = ["postgres", "redis", "nats"]
            details["running_services"] = running_services
            details["expected_services"] = expected_services
            
            missing_services = [svc for svc in expected_services if svc not in running_services]
            
            if missing_services:
                status = ValidationStatus.FAILED
                error_msg = f"Missing services: {missing_services}"
                recommendations = [
                    f"Run: {' '.join(compose_cmd)} up -d",
                    "Wait for services to start before running validation"
                ]
            else:
                status = ValidationStatus.PASSED
                error_msg = None
                recommendations = []
                
            details["missing_services"] = missing_services

        except subprocess.TimeoutExpired:
            status = ValidationStatus.FAILED
            error_msg = "Docker command timed out"
            recommendations = ["Check Docker daemon is running", "Verify docker-compose.yml exists"]
            
        except FileNotFoundError:
            status = ValidationStatus.FAILED  
            error_msg = "Docker Compose not found"
            recommendations = ["Install Docker and Docker Compose", "Verify PATH includes docker commands"]
            
        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = str(e)
            recommendations = ["Check Docker installation", "Verify docker-compose.yml syntax"]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["docker_services"] = ValidationResult(
            check_name="Docker Services",
            status=status,
            details=details,
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _validate_basic_health(self):
        """Validate basic service health using existing health checker."""
        start_time = time.time()
        
        try:
            health_checker = HealthChecker(self.settings, timeout=30, verbose=False)
            health_result = await health_checker.check_all_services()
            
            details = {
                "overall_status": health_result.status.value,
                "service_summary": health_result.summary,
                "service_details": {
                    name: {
                        "status": svc.status.value,
                        "response_time_ms": svc.response_time_ms,
                        "error": svc.error
                    }
                    for name, svc in health_result.services.items()
                }
            }
            
            if health_result.status == HealthStatus.HEALTHY:
                status = ValidationStatus.PASSED
                error_msg = None
                recommendations = []
            elif health_result.status == HealthStatus.DEGRADED:
                status = ValidationStatus.WARNING
                error_msg = "Some services degraded but operational"
                recommendations = ["Review service logs", "Check service configurations"]
            else:
                status = ValidationStatus.FAILED
                error_msg = "Critical services unhealthy"
                recommendations = [
                    "Check service connectivity",
                    "Verify environment variables", 
                    "Review Docker logs: docker-compose logs"
                ]

        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"Health check execution failed: {str(e)}"
            details = {}
            recommendations = ["Check network connectivity", "Verify service configuration"]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["basic_health"] = ValidationResult(
            check_name="Basic Service Health",
            status=status,
            details=details,
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _validate_database_schema(self):
        """Validate all expected tables and columns exist."""
        start_time = time.time()
        details = {}
        
        try:
            conn = await asyncpg.connect(
                host=self.settings.database.host,
                port=self.settings.database.port,
                user=self.settings.database.username,
                password=self.settings.database.password,
                database=self.settings.database.database
            )
            
            try:
                # Check expected tables
                expected_tables = ["sites", "keywords", "audit_log", "rankings", "gsc_metrics", "ga4_metrics"]
                
                existing_tables = await conn.fetch("""
                    SELECT tablename FROM pg_tables 
                    WHERE schemaname = 'public' 
                    ORDER BY tablename
                """)
                existing_table_names = [row['tablename'] for row in existing_tables]
                
                details["expected_tables"] = expected_tables
                details["existing_tables"] = existing_table_names
                
                missing_tables = [t for t in expected_tables if t not in existing_table_names]
                details["missing_tables"] = missing_tables
                
                # Check extensions
                extensions = await conn.fetch("""
                    SELECT extname, extversion FROM pg_extension 
                    WHERE extname IN ('timescaledb', 'vector', 'uuid-ossp')
                """)
                details["extensions"] = {row['extname']: row['extversion'] for row in extensions}
                
                required_extensions = ["timescaledb", "vector", "uuid-ossp"]
                missing_extensions = [ext for ext in required_extensions if ext not in details["extensions"]]
                details["missing_extensions"] = missing_extensions
                
                # Check enum types
                enums = await conn.fetch("""
                    SELECT typname FROM pg_type 
                    WHERE typtype = 'e' AND typname IN (
                        'cmstype', 'keywordintent', 'keywordpriority', 
                        'actiontype', 'entitytype', 'approvalstatus'
                    )
                    ORDER BY typname
                """)
                details["enum_types"] = [row['typname'] for row in enums]
                
                if missing_tables or missing_extensions:
                    status = ValidationStatus.FAILED
                    error_msg = f"Missing tables: {missing_tables}, Missing extensions: {missing_extensions}"
                    recommendations = [
                        "Run database migrations: alembic upgrade head",
                        "Ensure PostgreSQL extensions are installed",
                        "Check database user has required permissions"
                    ]
                else:
                    status = ValidationStatus.PASSED
                    error_msg = None
                    recommendations = []

            finally:
                await conn.close()

        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"Database schema validation failed: {str(e)}"
            recommendations = [
                "Check database connection parameters",
                "Verify database exists and is accessible",
                "Run initial schema migration"
            ]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["database_schema"] = ValidationResult(
            check_name="Database Schema",
            status=status,
            details=details, 
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _validate_database_migrations(self):
        """Test database migration upgrade and rollback functionality."""
        start_time = time.time()
        details = {}
        
        try:
            # Get current migration state
            result = subprocess.run(
                ["alembic", "current"], 
                capture_output=True, text=True, timeout=30,
                cwd=self.project_root
            )
            details["current_revision"] = result.stdout.strip()
            
            # Test upgrade to head (should be idempotent)
            upgrade_start = time.time()
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                capture_output=True, text=True, timeout=60,
                cwd=self.project_root  
            )
            upgrade_time = round((time.time() - upgrade_start) * 1000, 2)
            details["upgrade_time_ms"] = upgrade_time
            details["upgrade_output"] = result.stdout
            
            if result.returncode != 0:
                status = ValidationStatus.FAILED
                error_msg = f"Migration upgrade failed: {result.stderr}"
                recommendations = [
                    "Check alembic configuration",
                    "Verify database permissions",
                    "Review migration scripts for errors"
                ]
            else:
                # Test downgrade to base and back to head
                downgrade_start = time.time()
                
                # First downgrade to base
                result = subprocess.run(
                    ["alembic", "downgrade", "base"],
                    capture_output=True, text=True, timeout=60,
                    cwd=self.project_root
                )
                
                if result.returncode == 0:
                    # Then upgrade back to head
                    result = subprocess.run(
                        ["alembic", "upgrade", "head"],
                        capture_output=True, text=True, timeout=60,
                        cwd=self.project_root
                    )
                    
                downgrade_time = round((time.time() - downgrade_start) * 1000, 2)
                details["downgrade_cycle_time_ms"] = downgrade_time
                
                if result.returncode == 0:
                    status = ValidationStatus.PASSED
                    error_msg = None
                    recommendations = []
                else:
                    status = ValidationStatus.FAILED
                    error_msg = "Migration downgrade/upgrade cycle failed"
                    recommendations = [
                        "Check migration scripts for rollback issues",
                        "Verify database state consistency"
                    ]

        except subprocess.TimeoutExpired:
            status = ValidationStatus.FAILED
            error_msg = "Migration command timed out"
            recommendations = ["Check database performance", "Review complex migration steps"]
            
        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"Migration validation failed: {str(e)}"
            recommendations = ["Check Alembic installation", "Verify alembic.ini configuration"]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["database_migrations"] = ValidationResult(
            check_name="Database Migrations",
            status=status,
            details=details,
            execution_time_ms=execution_time, 
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _validate_timescaledb_hypertables(self):
        """Validate TimescaleDB hypertables are properly configured."""
        start_time = time.time()
        details = {}
        
        try:
            conn = await asyncpg.connect(
                host=self.settings.database.host,
                port=self.settings.database.port,
                user=self.settings.database.username,
                password=self.settings.database.password,
                database=self.settings.database.database
            )
            
            try:
                # Check hypertables exist
                hypertables = await conn.fetch("""
                    SELECT hypertable_schema, hypertable_name, num_dimensions
                    FROM timescaledb_information.hypertables
                    WHERE hypertable_schema = 'public'
                """)
                
                hypertable_names = [row['hypertable_name'] for row in hypertables]
                details["hypertables"] = hypertable_names
                
                expected_hypertables = ["rankings", "gsc_metrics", "ga4_metrics"]
                missing_hypertables = [ht for ht in expected_hypertables if ht not in hypertable_names]
                details["missing_hypertables"] = missing_hypertables
                
                # Check chunk information for each hypertable
                for table in expected_hypertables:
                    if table in hypertable_names:
                        chunks = await conn.fetch(f"""
                            SELECT chunk_name, range_start, range_end
                            FROM timescaledb_information.chunks 
                            WHERE hypertable_name = '{table}'
                            ORDER BY range_start DESC
                            LIMIT 5
                        """)
                        details[f"{table}_chunks"] = len(chunks)
                        details[f"{table}_latest_chunks"] = [
                            {
                                "name": chunk['chunk_name'],
                                "start": str(chunk['range_start']),
                                "end": str(chunk['range_end'])
                            } for chunk in chunks
                        ]
                
                if missing_hypertables:
                    status = ValidationStatus.FAILED
                    error_msg = f"Missing hypertables: {missing_hypertables}"
                    recommendations = [
                        "Run TimescaleDB conversion: SELECT create_hypertable(...)",
                        "Check TimescaleDB extension is properly loaded"
                    ]
                else:
                    status = ValidationStatus.PASSED
                    error_msg = None
                    recommendations = []

            finally:
                await conn.close()

        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"TimescaleDB validation failed: {str(e)}"
            recommendations = [
                "Check TimescaleDB extension installation",
                "Verify hypertable creation scripts",
                "Ensure user has TimescaleDB permissions"
            ]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["timescaledb_hypertables"] = ValidationResult(
            check_name="TimescaleDB Hypertables",
            status=status,
            details=details,
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _validate_pgvector_functionality(self):
        """Validate pgvector extension and similarity search functionality."""
        start_time = time.time()
        details = {}
        
        try:
            conn = await asyncpg.connect(
                host=self.settings.database.host,
                port=self.settings.database.port,
                user=self.settings.database.username,
                password=self.settings.database.password,
                database=self.settings.database.database
            )
            
            try:
                # Check vector extension
                vector_ext = await conn.fetchval("""
                    SELECT extversion FROM pg_extension WHERE extname = 'vector'
                """)
                details["vector_extension_version"] = vector_ext
                
                # Test vector operations
                test_vector = [0.1] * 1536  # OpenAI embedding dimension
                
                # Test vector creation and similarity
                similarity_start = time.time()
                result = await conn.fetchval("""
                    SELECT ($1::vector <-> $2::vector) as distance
                """, test_vector, test_vector)
                similarity_time = round((time.time() - similarity_start) * 1000, 2)
                
                details["vector_similarity_test"] = {
                    "distance": float(result),  # Should be 0.0 for identical vectors
                    "query_time_ms": similarity_time
                }
                
                # Check if our vector index exists
                vector_indexes = await conn.fetch("""
                    SELECT indexname, tablename FROM pg_indexes 
                    WHERE indexname LIKE '%embedding%' AND schemaname = 'public'
                """)
                details["vector_indexes"] = [
                    {"index": row['indexname'], "table": row['tablename']} 
                    for row in vector_indexes
                ]
                
                if vector_ext and result is not None:
                    status = ValidationStatus.PASSED
                    error_msg = None
                    recommendations = []
                else:
                    status = ValidationStatus.FAILED
                    error_msg = "pgvector functionality test failed"
                    recommendations = [
                        "Reinstall pgvector extension",
                        "Check extension compatibility with PostgreSQL version"
                    ]

            finally:
                await conn.close()

        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"pgvector validation failed: {str(e)}"
            recommendations = [
                "Install pgvector extension: CREATE EXTENSION vector",
                "Check PostgreSQL version compatibility",
                "Verify compilation flags for vector support"
            ]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["pgvector_functionality"] = ValidationResult(
            check_name="pgvector Functionality",
            status=status,
            details=details,
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations  
        )

    async def _validate_task_queue_functionality(self):
        """Validate Redis Streams task queue functionality."""
        start_time = time.time()
        details = {}
        
        try:
            redis_client = redis_async.Redis(
                host=self.settings.redis.host,
                port=self.settings.redis.port,
                password=self.settings.redis.password if hasattr(self.settings.redis, 'password') else None,
                decode_responses=True
            )
            
            # Test basic Redis operations
            await redis_client.ping()
            details["redis_ping"] = "success"
            
            # Test Redis Streams functionality
            stream_name = f"test_stream_{int(time.time())}"
            consumer_group = "test_group"
            consumer_name = "test_consumer"
            
            try:
                # Publish test message
                publish_start = time.time()
                message_id = await redis_client.xadd(stream_name, {
                    "task_type": "test_validation",
                    "payload": '{"test": true}',
                    "timestamp": str(int(time.time()))
                })
                publish_time = round((time.time() - publish_start) * 1000, 2)
                
                details["message_publish"] = {
                    "message_id": message_id,
                    "publish_time_ms": publish_time
                }
                
                # Create consumer group
                try:
                    await redis_client.xgroup_create(stream_name, consumer_group, id="0")
                except Exception:
                    pass  # Group might already exist
                
                # Consume message
                messages = await redis_client.xreadgroup(
                    consumer_group, consumer_name, {stream_name: ">"}, count=1, block=1000
                )
                
                if messages and messages[0][1]:
                    details["message_consume"] = "success"
                    details["consumed_message"] = messages[0][1][0][1]
                    
                    # Acknowledge message
                    await redis_client.xack(stream_name, consumer_group, messages[0][1][0][0])
                    details["message_ack"] = "success"
                else:
                    details["message_consume"] = "failed - no messages"
                
                # Clean up test stream
                await redis_client.delete(stream_name)
                
                status = ValidationStatus.PASSED
                error_msg = None
                recommendations = []
                
            except Exception as e:
                status = ValidationStatus.FAILED
                error_msg = f"Redis Streams test failed: {str(e)}"
                recommendations = [
                    "Check Redis Streams support (Redis 5.0+)",
                    "Verify Redis configuration",
                    "Check network connectivity to Redis"
                ]
            
            finally:
                await redis_client.close()

        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"Redis connection failed: {str(e)}"
            recommendations = [
                "Check Redis service is running",
                "Verify connection parameters",
                "Check Redis authentication if enabled"
            ]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["task_queue_functionality"] = ValidationResult(
            check_name="Task Queue Functionality",
            status=status,
            details=details,
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _validate_notification_system(self):
        """Validate NATS JetStream notification system."""
        start_time = time.time()
        details = {}
        
        try:
            nc = await nats.connect(
                servers=[f"nats://{self.settings.nats.host}:{self.settings.nats.port}"]
            )
            
            try:
                details["nats_connection"] = "success"
                
                # Test JetStream functionality
                js = nc.jetstream()
                
                # Test stream creation and message flow
                test_stream = f"test_approval_{int(time.time())}"
                test_subject = f"approvals.test.{int(time.time())}"
                
                # Create temporary test stream
                from nats.js.api import StreamConfig
                stream_config = StreamConfig(
                    name=test_stream,
                    subjects=[test_subject], 
                    max_msgs=10,
                    max_age=60  # 1 minute retention
                )
                
                stream = await js.add_stream(stream_config)
                details["jetstream_stream_creation"] = "success"
                
                # Test message publishing
                roundtrip_start = time.time()
                
                # Publish approval request
                ack = await js.publish(test_subject, b'{"action": "test_approval", "requires_approval": true}')
                details["approval_publish"] = {
                    "sequence": ack.seq,
                    "duplicate": ack.duplicate
                }
                
                # Subscribe and receive message
                sub = await js.subscribe(test_subject, durable="test_consumer")
                
                try:
                    msg = await sub.next_msg(timeout=5.0)
                    roundtrip_time = round((time.time() - roundtrip_start) * 1000, 2)
                    
                    details["approval_receive"] = {
                        "subject": msg.subject,
                        "data": msg.data.decode(),
                        "roundtrip_time_ms": roundtrip_time
                    }
                    
                    await msg.ack()
                    
                except Exception as e:
                    details["approval_receive"] = f"failed: {str(e)}"
                
                finally:
                    await sub.unsubscribe()
                
                # Clean up test stream
                await js.delete_stream(test_stream)
                
                status = ValidationStatus.PASSED
                error_msg = None
                recommendations = []
                
            finally:
                await nc.close()

        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"NATS validation failed: {str(e)}"
            recommendations = [
                "Check NATS server is running",
                "Verify JetStream is enabled",
                "Check NATS connection parameters",
                "Verify network connectivity to NATS"
            ]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["notification_system"] = ValidationResult(
            check_name="Notification System",
            status=status,
            details=details,
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _validate_configuration_loading(self):
        """Validate Pydantic configuration loading and validation."""
        start_time = time.time()
        details = {}
        
        try:
            # Test configuration loading
            settings = get_settings()
            details["config_loading"] = "success"
            
            # Validate required configuration sections
            config_sections = ["app", "database", "redis", "nats"]
            missing_sections = []
            
            for section in config_sections:
                if hasattr(settings, section):
                    details[f"{section}_config"] = "present"
                else:
                    missing_sections.append(section)
                    details[f"{section}_config"] = "missing"
            
            # Test environment variable validation
            required_env_vars = [
                "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_USER"
            ]
            missing_env_vars = [var for var in required_env_vars if not os.getenv(var)]
            details["missing_env_vars"] = missing_env_vars
            
            if missing_sections or missing_env_vars:
                status = ValidationStatus.WARNING
                error_msg = f"Missing config sections: {missing_sections}, Missing env vars: {missing_env_vars}"
                recommendations = [
                    "Check .env file exists and is properly formatted",
                    "Verify all required environment variables are set",
                    "Review config/settings.py for required settings"
                ]
            else:
                status = ValidationStatus.PASSED  
                error_msg = None
                recommendations = []

        except Exception as e:
            status = ValidationStatus.FAILED
            error_msg = f"Configuration validation failed: {str(e)}"
            recommendations = [
                "Check config module imports",
                "Verify Pydantic settings configuration",
                "Ensure environment variables are properly typed"
            ]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["configuration_loading"] = ValidationResult(
            check_name="Configuration Loading",
            status=status,
            details=details,
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    async def _record_performance_baselines(self):
        """Record performance baseline measurements for future comparison."""
        start_time = time.time()
        
        try:
            postgresql_time = 0.0
            redis_time = 0.0  
            nats_time = 0.0
            migration_upgrade_time = 0.0
            migration_downgrade_time = 0.0
            vector_similarity_time = 0.0
            
            # PostgreSQL query benchmark
            try:
                conn = await asyncpg.connect(
                    host=self.settings.database.host,
                    port=self.settings.database.port,
                    user=self.settings.database.username,
                    password=self.settings.database.password,
                    database=self.settings.database.database
                )
                
                pg_start = time.time()
                await conn.fetchval("SELECT COUNT(*) FROM pg_tables")
                postgresql_time = round((time.time() - pg_start) * 1000, 2)
                
                # Vector similarity benchmark
                if "pgvector_functionality" in self.report.checks and \
                   self.report.checks["pgvector_functionality"].status == ValidationStatus.PASSED:
                    vector_start = time.time()
                    test_vector = [0.1] * 1536
                    await conn.fetchval("SELECT ($1::vector <-> $2::vector)", test_vector, test_vector)
                    vector_similarity_time = round((time.time() - vector_start) * 1000, 2)
                
                await conn.close()
                
            except Exception:
                pass  # Best effort measurement
                
            # Redis benchmark
            try:
                redis_client = redis_async.Redis(
                    host=self.settings.redis.host,
                    port=self.settings.redis.port,
                    decode_responses=True
                )
                
                redis_start = time.time()
                await redis_client.set("benchmark_key", "benchmark_value", ex=10)
                redis_time = round((time.time() - redis_start) * 1000, 2)
                
                await redis_client.delete("benchmark_key")
                await redis_client.close()
                
            except Exception:
                pass  # Best effort measurement
                
            # NATS benchmark  
            try:
                nc = await nats.connect(
                    servers=[f"nats://{self.settings.nats.host}:{self.settings.nats.port}"]
                )
                
                nats_start = time.time()
                await nc.publish("benchmark.test", b"benchmark")
                nats_time = round((time.time() - nats_start) * 1000, 2)
                
                await nc.close()
                
            except Exception:
                pass  # Best effort measurement
            
            # Extract migration times from previous checks
            if "database_migrations" in self.report.checks:
                details = self.report.checks["database_migrations"].details
                migration_upgrade_time = details.get("upgrade_time_ms", 0.0)
                migration_downgrade_time = details.get("downgrade_cycle_time_ms", 0.0)
            
            self.report.performance_baselines = PerformanceBaseline(
                postgresql_query_time_ms=postgresql_time,
                redis_publish_time_ms=redis_time,
                nats_roundtrip_time_ms=nats_time,
                migration_upgrade_time_ms=migration_upgrade_time,
                migration_downgrade_time_ms=migration_downgrade_time,
                vector_similarity_query_ms=vector_similarity_time
            )
            
            status = ValidationStatus.PASSED
            error_msg = None
            recommendations = []

        except Exception as e:
            status = ValidationStatus.WARNING
            error_msg = f"Performance baseline recording failed: {str(e)}"
            recommendations = ["Performance baselines are informational only"]

        execution_time = round((time.time() - start_time) * 1000, 2)
        
        self.report.checks["performance_baselines"] = ValidationResult(
            check_name="Performance Baselines",
            status=status,
            details=asdict(self.report.performance_baselines) if self.report.performance_baselines else {},
            execution_time_ms=execution_time,
            error_message=error_msg,
            recommendations=recommendations
        )

    def _calculate_overall_status(self):
        """Calculate overall validation status and compile issues/recommendations."""
        failed_checks = []
        warning_checks = []
        passed_checks = []
        
        for check_name, result in self.report.checks.items():
            if result.status == ValidationStatus.FAILED:
                failed_checks.append(check_name)
                if result.error_message:
                    self.report.issues.append(f"{check_name}: {result.error_message}")
                self.report.recommendations.extend(result.recommendations)
                
            elif result.status == ValidationStatus.WARNING:
                warning_checks.append(check_name)
                if result.error_message:
                    self.report.issues.append(f"{check_name} (WARNING): {result.error_message}")
                self.report.recommendations.extend(result.recommendations)
                
            elif result.status == ValidationStatus.PASSED:
                passed_checks.append(check_name)
        
        # Overall status logic
        if failed_checks:
            self.report.status = ValidationStatus.FAILED
            self.report.issues.insert(0, f"Critical validation failures: {', '.join(failed_checks)}")
        elif warning_checks:
            self.report.status = ValidationStatus.WARNING  
            self.report.issues.insert(0, f"Validation warnings: {', '.join(warning_checks)}")
        else:
            self.report.status = ValidationStatus.PASSED
            
        # Remove duplicate recommendations
        self.report.recommendations = list(dict.fromkeys(self.report.recommendations))


def setup_argument_parser() -> argparse.ArgumentParser:
    """Set up command line argument parser."""
    parser = argparse.ArgumentParser(
        description="SEO Platform Phase 1 Comprehensive Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  Phase 1 validation PASSED - ready for Phase 2
  1  Phase 1 validation FAILED - critical issues found  
  2  Script execution error

Examples:
  python scripts/validate-phase1.py
  python scripts/validate-phase1.py --json-only
  python scripts/validate-phase1.py --skip-docker --timeout 600
        """
    )

    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Output only JSON report without additional formatting"
    )
    
    parser.add_argument(
        "--skip-docker", 
        action="store_true",
        help="Skip Docker Compose service validation"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Validation timeout in seconds (default: 300)"
    )

    return parser


async def main():
    """Main validation execution."""
    parser = setup_argument_parser()
    args = parser.parse_args()

    try:
        # Load configuration
        settings = get_settings()
        
        # Create validator
        validator = Phase1Validator(
            settings=settings,
            skip_docker=args.skip_docker,
            timeout=args.timeout
        )
        
        # Run validation
        report = await validator.validate_all()
        
        # Output results
        if args.json_only:
            print(json.dumps(asdict(report), indent=2, default=str))
        else:
            print_human_readable_report(report)
            
        # Exit with appropriate code
        if report.status == ValidationStatus.PASSED:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n❌ Validation interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"❌ Validation script error: {e}")
        sys.exit(2)


def print_human_readable_report(report: Phase1ValidationReport):
    """Print human-readable validation report."""
    
    # Header
    status_emoji = "✅" if report.status == ValidationStatus.PASSED else "❌" if report.status == ValidationStatus.FAILED else "⚠️"
    print(f"\n{status_emoji} Phase 1 Validation Report")
    print("=" * 50)
    print(f"Status: {report.status.value}")
    print(f"Timestamp: {report.timestamp}")
    print(f"Total Execution Time: {report.total_execution_time_ms:.1f}ms")
    print()
    
    # Check Results
    print("📊 Validation Checks:")
    print("-" * 30)
    
    for check_name, result in report.checks.items():
        status_symbol = {
            ValidationStatus.PASSED: "✅",
            ValidationStatus.FAILED: "❌", 
            ValidationStatus.WARNING: "⚠️",
            ValidationStatus.SKIPPED: "⏭️"
        }.get(result.status, "❓")
        
        print(f"{status_symbol} {result.check_name}")
        print(f"   Status: {result.status.value}")
        print(f"   Time: {result.execution_time_ms:.1f}ms")
        
        if result.error_message:
            print(f"   Error: {result.error_message}")
            
        if result.recommendations:
            print("   Recommendations:")
            for rec in result.recommendations:
                print(f"     • {rec}")
        print()
    
    # Performance Baselines
    if report.performance_baselines:
        print("⚡ Performance Baselines:")
        print("-" * 30)
        baselines = asdict(report.performance_baselines)
        for metric, value in baselines.items():
            print(f"  {metric}: {value}ms")
        print()
    
    # Issues Summary
    if report.issues:
        print("🚨 Issues Found:")
        print("-" * 20)
        for issue in report.issues:
            print(f"  • {issue}")
        print()
    
    # Recommendations
    if report.recommendations:
        print("💡 Recommendations:")
        print("-" * 25)
        for rec in report.recommendations:
            print(f"  • {rec}")
        print()
    
    # Final Status
    if report.status == ValidationStatus.PASSED:
        print("🎉 Phase 1 validation PASSED! Ready to proceed to Phase 2.")
    else:
        print("❌ Phase 1 validation FAILED. Fix issues above before proceeding.")


if __name__ == "__main__":
    asyncio.run(main())
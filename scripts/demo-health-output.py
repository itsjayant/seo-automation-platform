#!/usr/bin/env python3
"""
Demo script showing expected health check JSON output format
"""

import json
from datetime import datetime, timezone

def demo_healthy_output():
    """Generate sample healthy system output."""
    return {
        "status": "healthy",
        "services": {
            "postgresql": {
                "status": "healthy",
                "details": {
                    "connection": "successful",
                    "config": {
                        "host": "localhost",
                        "port": 5432,
                        "database": "seo_platform",
                        "user": "seo"
                    },
                    "version": "PostgreSQL 16.1 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 11.2.0, 64-bit",
                    "extensions": {
                        "timescaledb": "2.12.2",
                        "vector": "0.5.1",
                        "uuid-ossp": "1.1",
                        "pg_stat_statements": "1.10"
                    },
                    "extension_status": "complete",
                    "test_query": {
                        "result": {
                            "test": 1,
                            "now": "2026-04-12T10:30:00+00:00"
                        },
                        "success": True
                    },
                    "vector_test": {
                        "distance": 1.0,
                        "success": True
                    }
                },
                "response_time_ms": 45.2,
                "error": None,
                "timestamp": "2026-04-12T10:30:00Z"
            },
            "redis": {
                "status": "healthy",
                "details": {
                    "connection": "successful",
                    "config": {
                        "host": "localhost",
                        "port": 6379,
                        "database": 0,
                        "password_set": False
                    },
                    "version": "7.2.4",
                    "mode": "standalone",
                    "uptime_seconds": 86400,
                    "memory": {
                        "used_memory_human": "2.00M",
                        "maxmemory_human": "256.00M",
                        "maxmemory_policy": "allkeys-lru"
                    },
                    "basic_operations": "successful",
                    "streams_functionality": "healthy"
                },
                "response_time_ms": 12.8,
                "error": None,
                "timestamp": "2026-04-12T10:30:00Z"
            },
            "nats": {
                "status": "healthy",
                "details": {
                    "connection": "successful",
                    "config": {
                        "host": "localhost",
                        "port": 4222,
                        "auth_configured": False
                    },
                    "server_version": "2.10.7",
                    "basic_pubsub": "successful",
                    "jetstream": {
                        "enabled": True,
                        "streams": 3,
                        "consumers": 5
                    }
                },
                "response_time_ms": 23.1,
                "error": None,
                "timestamp": "2026-04-12T10:30:00Z"
            }
        },
        "timestamp": "2026-04-12T10:30:00Z",
        "summary": {
            "healthy": 3,
            "degraded": 0,
            "unhealthy": 0
        }
    }

def demo_degraded_output():
    """Generate sample degraded system output."""
    return {
        "status": "degraded",
        "services": {
            "postgresql": {
                "status": "degraded",
                "details": {
                    "connection": "successful",
                    "version": "PostgreSQL 16.1...",
                    "extensions": {
                        "timescaledb": "2.12.2",
                        "uuid-ossp": "1.1"
                    },
                    "missing_extensions": ["vector"],
                    "extension_status": "degraded"
                },
                "response_time_ms": 67.3,
                "error": "Missing required extensions: ['vector']",
                "timestamp": "2026-04-12T10:30:00Z"
            },
            "redis": {
                "status": "healthy", 
                "details": {
                    "connection": "successful",
                    "version": "7.2.4",
                    "basic_operations": "successful",
                    "streams_functionality": "healthy"
                },
                "response_time_ms": 15.2,
                "error": None,
                "timestamp": "2026-04-12T10:30:00Z"
            },
            "nats": {
                "status": "degraded",
                "details": {
                    "connection": "successful",
                    "server_version": "2.10.7",
                    "basic_pubsub": "successful",
                    "jetstream": {
                        "enabled": False,
                        "error": "not available"
                    }
                },
                "response_time_ms": 28.7,
                "error": None,
                "timestamp": "2026-04-12T10:30:00Z"
            }
        },
        "timestamp": "2026-04-12T10:30:00Z",
        "summary": {
            "healthy": 1,
            "degraded": 2,
            "unhealthy": 0
        }
    }

def demo_unhealthy_output():
    """Generate sample unhealthy system output."""
    return {
        "status": "unhealthy",
        "services": {
            "postgresql": {
                "status": "unhealthy",
                "details": {
                    "configuration": "missing POSTGRES_PASSWORD"
                },
                "response_time_ms": 0,
                "error": "Database password not configured",
                "timestamp": "2026-04-12T10:30:00Z"  
            },
            "redis": {
                "status": "unhealthy",
                "details": {
                    "config": {
                        "host": "localhost",
                        "port": 6379
                    }
                },
                "response_time_ms": 10003.2,
                "error": "Connection timeout after 10000ms",
                "timestamp": "2026-04-12T10:30:00Z"
            },
            "nats": {
                "status": "unhealthy",
                "details": {
                    "config": {
                        "host": "localhost",
                        "port": 4222
                    }
                },
                "response_time_ms": 10004.1,
                "error": "Connection failed: [Errno 61] Connection refused",
                "timestamp": "2026-04-12T10:30:00Z"
            }
        },
        "timestamp": "2026-04-12T10:30:00Z",
        "summary": {
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 3
        }
    }

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        scenario = sys.argv[1]
    else:
        scenario = "healthy"
    
    if scenario == "healthy":
        output = demo_healthy_output()
        exit_code = 0
    elif scenario == "degraded":
        output = demo_degraded_output()
        exit_code = 1  
    elif scenario == "unhealthy":
        output = demo_unhealthy_output()
        exit_code = 2
    else:
        print(f"Usage: {sys.argv[0]} [healthy|degraded|unhealthy]", file=sys.stderr)
        sys.exit(1)
    
    print(json.dumps(output, indent=2))
    sys.exit(exit_code)
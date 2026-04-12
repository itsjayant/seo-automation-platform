# SEO Platform Scripts

This directory contains operational scripts for maintaining and monitoring the SEO automation platform.

## Scripts Overview

### Health Check (`health-check.py`)

Comprehensive health validation for all infrastructure components.

#### Features

- **PostgreSQL Health Check**
  - Database connection validation
  - Extension verification (TimescaleDB, pgvector, uuid-ossp)
  - Basic functionality testing
  - Performance metrics collection

- **Redis Health Check**
  - Connection and basic operations testing
  - Redis Streams functionality validation
  - Memory usage monitoring
  - Configuration verification

- **NATS Health Check**
  - Server connectivity validation
  - JetStream availability testing
  - Stream creation and message publishing
  - Account information collection

#### Usage

```bash
# Basic health check
python scripts/health-check.py

# With custom timeout and retries
python scripts/health-check.py --timeout 15 --retries 5

# Verbose output for debugging
python scripts/health-check.py --verbose

# JSON-only output for programmatic use
python scripts/health-check.py --json-only
```

#### Command Line Options

- `--timeout SECONDS`: Timeout for each service check (default: 10)
- `--retries COUNT`: Number of retry attempts for failed connections (default: 3)  
- `--verbose, -v`: Enable verbose logging output
- `--json-only`: Output only JSON without additional formatting

#### Exit Codes

- `0`: All services healthy
- `1`: Some services degraded but system operational
- `2`: Critical services unhealthy, system non-operational

#### Output Format

The health check returns structured JSON with the following format:

```json
{
  "status": "healthy|degraded|unhealthy",
  "services": {
    "postgresql": {
      "status": "healthy",
      "details": {
        "connection": "successful",
        "version": "PostgreSQL 16.1...",
        "extensions": {
          "timescaledb": "2.12.2",
          "vector": "0.5.1",
          "uuid-ossp": "1.1"
        },
        "test_query": {"success": true},
        "vector_test": {"distance": 1.0, "success": true},
        "database_stats": {
          "active_connections": 2,
          "transactions_committed": 1234,
          "transactions_rolled_back": 0
        }
      },
      "response_time_ms": 45.2,
      "timestamp": "2026-04-12T10:30:00Z"
    },
    "redis": {
      "status": "healthy", 
      "details": {
        "connection": "successful",
        "version": "7.2.4",
        "mode": "standalone",
        "uptime_seconds": 86400,
        "memory": {
          "used_memory": 2048000,
          "used_memory_human": "2.00M",
          "maxmemory": 268435456,
          "maxmemory_human": "256.00M",
          "maxmemory_policy": "allkeys-lru"
        },
        "basic_operations": "successful",
        "streams_functionality": "healthy"
      },
      "response_time_ms": 12.8,
      "timestamp": "2026-04-12T10:30:00Z"
    },
    "nats": {
      "status": "healthy",
      "details": {
        "connection": "successful",
        "server_version": "2.10.7",
        "basic_pubsub": "successful",
        "jetstream": {
          "enabled": true,
          "streams": 3,
          "consumers": 5,
          "messages": 1024,
          "bytes": 65536
        },
        "jetstream_stream_creation": "successful",
        "jetstream_publish": {
          "successful": true,
          "sequence": 1,
          "duplicate": false
        }
      },
      "response_time_ms": 23.1,
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
```

#### Dependencies

The health check script requires the following Python packages:

```bash
pip install asyncpg redis nats-py pydantic pydantic-settings
```

#### Integration with Docker Compose

The health check script can be integrated with Docker Compose health check directives:

```yaml
services:
  orchestrator:
    # ... other configuration
    healthcheck:
      test: ["CMD", "python", "/app/scripts/health-check.py", "--timeout", "30", "--json-only"]
      interval: 30s
      timeout: 45s
      retries: 3
      start_period: 60s
```

#### Error Handling

The script implements robust error handling with:

- **Timeout Management**: Configurable timeouts for each service check
- **Retry Logic**: Exponential backoff for failed connections
- **Graceful Degradation**: Partial functionality reporting when some services fail
- **Detailed Error Reporting**: Specific error messages for debugging

#### Monitoring Integration

The structured JSON output is designed for integration with monitoring systems:

- **Prometheus**: Parse JSON metrics for alerting
- **Grafana**: Visualize service health trends  
- **ELK Stack**: Log structured health data for analysis
- **Custom Dashboards**: Use JSON API for real-time status displays

## Development Guidelines

### Adding New Scripts

When adding new operational scripts to this directory:

1. **Follow Naming Convention**: Use kebab-case for script files (`my-script.py`)
2. **Include Docstring**: Add comprehensive module docstring explaining purpose and usage
3. **Use Configuration**: Import and use the Pydantic settings system from `config/settings.py`
4. **Error Handling**: Implement proper exception handling and meaningful exit codes
5. **Logging**: Use structured logging with appropriate levels
6. **CLI Interface**: Use argparse for command-line options with help text
7. **Update README**: Document the new script in this README file

### Script Requirements

All scripts in this directory should:

- Be executable (`#!/usr/bin/env python3`)
- Use type hints for better code clarity
- Include comprehensive error handling
- Provide meaningful exit codes for automation
- Support JSON output for programmatic consumption
- Be compatible with the project's Docker environment

### Testing Scripts

Test operational scripts using:

```bash
# Test in development environment
python scripts/health-check.py --verbose

# Test with Docker Compose services
docker-compose up -d && python scripts/health-check.py

# Test error conditions
docker-compose stop postgres && python scripts/health-check.py
```

## Troubleshooting

### Common Issues

#### "Cannot import configuration" Error
- Ensure you're running from the project root directory
- Verify the `config` module is available in the Python path
- Check that all required environment variables are set

#### Service Connection Failures
- Verify Docker Compose services are running: `docker-compose ps`
- Check network connectivity: `docker network ls`
- Validate environment variables: `python debug_env.py`

#### Timeout Issues
- Increase timeout values with `--timeout` flag
- Check service logs: `docker-compose logs <service-name>`
- Verify resource availability (CPU, memory, disk)

#### Extension Missing Errors
- Restart PostgreSQL container: `docker-compose restart postgres`
- Check extension initialization: `docker-compose logs postgres`
- Verify TimescaleDB and pgvector installation

### Debug Mode

Enable verbose output for detailed debugging:

```bash
python scripts/health-check.py --verbose --timeout 30
```

This will show:
- Connection attempt details
- Retry logic execution
- Service-specific test results  
- Timing information for each check
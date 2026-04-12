# Configuration Management

This directory contains the configuration management system for the SEO Automation Platform. It provides type-safe, validated access to all environment variables using Pydantic BaseSettings.

## Overview

The configuration system is organized into logical sections that mirror the system architecture:

- **AppSettings**: Environment type, logging, debug flags
- **DatabaseSettings**: PostgreSQL, TimescaleDB, pgvector configuration
- **RedisSettings**: Task queue and caching configuration  
- **NATSSettings**: Approval workflows and notifications
- **ExternalAPISettings**: Google Search Console, GA4, SerpAPI credentials
- **SecuritySettings**: JWT, encryption, CORS, rate limiting
- **ApplicationSettings**: Web dashboard, agents, content generation
- **CMSIntegrationSettings**: WordPress and custom CMS configuration
- **MonitoringSettings**: Observability and performance monitoring
- **DevelopmentSettings**: Development and testing toggles

## Quick Start

### Basic Usage

```python
from config import get_settings

# Get complete settings
settings = get_settings()

# Access database configuration  
db_url = settings.database.connection_url
db_pool_size = settings.database.max_connections

# Access API credentials
gsc_api_key = settings.external_apis.gsc_api_key
serpapi_key = settings.external_apis.serpapi_key

# Check environment
from config import Environment
if settings.app.environment == Environment.PRODUCTION:
    # Production-specific logic
    pass
```

### Convenience Functions

```python
from config import (
    get_database_settings,
    get_redis_settings, 
    get_security_settings
)

# Get specific configuration sections
db_config = get_database_settings()
redis_config = get_redis_settings()
security_config = get_security_settings()
```

### Environment Detection

```python
from config import get_settings, Environment

settings = get_settings()

match settings.app.environment:
    case Environment.DEVELOPMENT:
        # Development-specific setup
        pass
    case Environment.STAGING:
        # Staging-specific setup
        pass
    case Environment.PRODUCTION:
        # Production-specific setup
        pass
```

## Configuration Sources

The system loads configuration from multiple sources in order of precedence:

1. **Environment variables** (highest priority)
2. **`.env` file** in the project root
3. **Default values** defined in the setting classes

### Environment File Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Update required values (marked as `# REQUIRED` in `.env.example`):
   ```bash
   # Database
   POSTGRES_PASSWORD=your_secure_password_here
   
   # API Keys  
   GSC_API_KEY=your_google_search_console_key
   GA4_API_KEY=your_google_analytics_key
   SERPAPI_KEY=your_serpapi_key
   
   # Security
   JWT_SECRET_KEY=your_super_secret_jwt_key_32_chars_min
   ENCRYPTION_KEY=your_32_byte_base64_encoded_key
   ```

## Validation Features

### Type Safety

All configuration fields have strict type hints:

```python
class DatabaseSettings(BaseSettings):
    host: str                           # String validation
    port: PositiveInt                  # Positive integer only
    max_connections: PositiveInt       # Must be > 0  
    password: constr(min_length=8)     # Minimum length constraint
    url: Optional[str]                 # Optional field
```

### Environment-Specific Validation

The system enforces security requirements based on environment:

**Production Environment:**
- `DEBUG` must be `False`
- `DEV_SKIP_APPROVAL_GATE` must be `False`
- All placeholder values must be replaced with real credentials
- Strong passwords are required (minimum 8 characters)

**Development Environment:**
- Relaxed validation for easier local development
- Warning messages for insecure settings (but allows them)

### Cross-Field Validation

Some fields are validated against each other:

```python
@validator("min_connections")
def validate_connection_pool(cls, v, values):
    """Ensure min_connections <= max_connections."""
    if "max_connections" in values and v > values["max_connections"]:
        raise ValueError("min_connections cannot exceed max_connections")
    return v
```

## Security Features

### Sensitive Data Protection

The configuration system includes built-in protection for sensitive data:

```python
# Safe export masks sensitive values
safe_config = settings.model_dump_safe()
# Returns: {"security": {"jwt_secret_key": "***MASKED***"}}
```

### Required Credential Validation

All API keys and secrets have minimum length requirements:

```python
class ExternalAPISettings(BaseSettings):
    gsc_api_key: constr(min_length=10) = Field(..., env="GSC_API_KEY")
    jwt_secret_key: constr(min_length=32) = Field(..., env="JWT_SECRET_KEY")
```

### Production Safety Checks

The system prevents common security mistakes:

- Placeholder credentials in production
- Debug mode enabled in production  
- Approval gate disabled in production
- Weak passwords or encryption keys

## Connection URL Generation

Database and messaging configurations automatically generate connection URLs:

```python
# PostgreSQL connection URL
db_url = settings.database.connection_url
# Returns: "postgresql://user:pass@host:port/database"

# Redis connection URL  
redis_url = settings.redis.connection_url
# Returns: "redis://host:port/db" or "redis://:pass@host:port/db"

# NATS connection URL
nats_url = settings.nats.connection_url  
# Returns: "nats://host:port" or "nats://user:pass@host:port"
```

## Error Handling

The configuration system provides detailed error messages for common issues:

### Missing Required Values

```
ValidationError: 1 validation error for ExternalAPISettings
gsc_api_key
  field required (type=value_error.missing)
  
🔧 Fix: Set GSC_API_KEY environment variable or add to .env file
📖 Get API key: https://console.cloud.google.com/apis/credentials
```

### Invalid Values

```
ValidationError: 1 validation error for DatabaseSettings  
password
  ensure this value has at least 8 characters (type=value_error.any_str.min_length; limit_value=8)
  
🔧 Fix: Use a password with at least 8 characters
🛡️  Tip: Use a strong, randomly generated password
```

### Environment-Specific Errors

```
ValueError: DEBUG must be False in production environment

🔧 Fix: Set DEBUG=false in production .env file
⚠️  Security: Debug mode exposes sensitive information
```

## Usage Examples

### Basic Agent Implementation

```python
from config import get_settings

class BaseAgent:
    def __init__(self):
        self.settings = get_settings()
        self.db_url = self.settings.database.connection_url
        self.redis_url = self.settings.redis.connection_url
        
    async def connect(self):
        # Use validated configuration for connections
        pass
```

### API Rate Limiting

```python
from config import get_external_api_settings

api_config = get_external_api_settings()

# Configure rate limiters with validated limits
gsc_limiter = RateLimiter(
    rate=api_config.rate_limit_gsc,
    per=60  # per minute
)

serpapi_limiter = RateLimiter(
    rate=api_config.rate_limit_serpapi, 
    per=60  # per minute
)
```

### Environment-Specific Behavior

```python
from config import get_settings, Environment

settings = get_settings()

if settings.app.environment == Environment.DEVELOPMENT:
    # Enable extra logging, mock external APIs
    logging_level = "DEBUG"
    mock_apis = settings.development.mock_external_apis
    
elif settings.app.environment == Environment.PRODUCTION:
    # Strict security, real APIs only
    logging_level = "WARNING" 
    mock_apis = False
```

## Testing

### Test Configuration

Use environment-specific settings for testing:

```python  
import os
from config import reload_settings

def test_configuration():
    # Override for testing
    os.environ["ENVIRONMENT"] = "development"
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test_db"
    
    # Force reload to pick up test settings
    settings = reload_settings()
    
    assert settings.app.environment == "development"
    assert "test_db" in settings.database.connection_url
```

### Mock External APIs in Development

```python
from config import get_settings

settings = get_settings()

if settings.development.mock_external_apis:
    # Use mock implementations
    gsc_client = MockGSCClient()
    serpapi_client = MockSerpAPIClient()
else:
    # Use real API clients
    gsc_client = GoogleSearchConsoleClient(settings.external_apis.gsc_api_key)
    serpapi_client = SerpAPIClient(settings.external_apis.serpapi_key)
```

## Troubleshooting

### Common Issues

1. **Import Error**: Ensure `pydantic` is installed: `pip install pydantic[dotenv]`

2. **Validation Error**: Check `.env` file format and required values

3. **Missing .env File**: Copy `.env.example` to `.env` and update values

4. **Permission Error**: Ensure `.env` file has appropriate read permissions

### Debug Configuration Loading

```python
from config import get_settings

try:
    settings = get_settings()
    print("✅ Configuration loaded successfully")
    print(f"Environment: {settings.app.environment}")
    print(f"Database: {settings.database.host}:{settings.database.port}")
except Exception as e:
    print(f"❌ Configuration error: {e}")
```

### Validate Production Readiness

```python
from config import get_settings, Environment

settings = get_settings()

if settings.app.environment == Environment.PRODUCTION:
    print("🔍 Production safety check:")
    
    # Check critical settings
    checks = [
        (not settings.app.debug, "Debug mode disabled"),
        (not settings.development.skip_approval_gate, "Approval gate enabled"),
        (len(settings.security.jwt_secret_key) >= 32, "Strong JWT secret"),
        (settings.database.password != "your_secure_postgres_password_here", "Real DB password"),
    ]
    
    for passed, description in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {description}")
```

## Migration from Manual Configuration

If migrating from manual configuration management:

1. **Replace manual env access**:
   ```python
   # Old
   database_url = os.getenv("DATABASE_URL")
   
   # New  
   from config import get_database_settings
   database_url = get_database_settings().connection_url
   ```

2. **Replace hardcoded defaults**:
   ```python
   # Old
   max_connections = int(os.getenv("MAX_CONNECTIONS", "10"))
   
   # New
   from config import get_database_settings
   max_connections = get_database_settings().max_connections
   ```

3. **Add type safety**:
   ```python
   # Old (no validation)
   port = int(os.getenv("PORT"))  # Could crash
   
   # New (validated)
   from config import get_settings
   port = get_settings().application.web_port  # Guaranteed PositiveInt
   ```
"""
SEO Automation Platform Configuration Management

This module provides type-safe configuration management using Pydantic BaseSettings.
All environment variables are validated and typed according to the system requirements.

Usage:
    from config import get_settings
    settings = get_settings()
    print(settings.database.host)
"""

from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import Field, HttpUrl, field_validator
from pydantic.types import PositiveInt, constr, conint
from pydantic_settings import BaseSettings
import os
from functools import lru_cache


class Environment(str, Enum):
    """Environment type enumeration."""
    DEVELOPMENT = "development"
    STAGING = "staging" 
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Log level enumeration."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(str, Enum):
    """Log format enumeration."""
    JSON = "json"
    TEXT = "text"


class JWTAlgorithm(str, Enum):
    """JWT algorithm enumeration."""
    HS256 = "HS256"
    HS384 = "HS384"
    HS512 = "HS512"
    RS256 = "RS256"


class PostStatus(str, Enum):
    """WordPress post status enumeration."""
    DRAFT = "draft"
    PUBLISH = "publish"
    PRIVATE = "private"


class AppSettings(BaseSettings):
    """Application-level configuration settings."""
    
    # Environment identification
    environment: Environment = Field(Environment.DEVELOPMENT, env="ENVIRONMENT")
    debug: bool = Field(False, env="DEBUG")
    
    # Application metadata
    app_name: str = Field("seo-automation-platform", env="APP_NAME")
    app_version: str = Field("1.0.0", env="APP_VERSION")
    
    # Logging configuration
    log_level: LogLevel = Field(LogLevel.INFO, env="LOG_LEVEL")
    log_format: LogFormat = Field(LogFormat.JSON, env="LOG_FORMAT")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class DatabaseSettings(BaseSettings):
    """PostgreSQL + TimescaleDB + pgvector configuration."""
    
    # Connection parameters
    host: str = Field("localhost", env="POSTGRES_HOST")
    port: PositiveInt = Field(5432, env="POSTGRES_PORT")
    database: str = Field("seo_platform", env="POSTGRES_DB") 
    username: str = Field("seo", env="POSTGRES_USER")
    password: constr(min_length=8) = Field(..., env="POSTGRES_PASSWORD")
    
    # Connection pool settings
    max_connections: PositiveInt = Field(20, env="POSTGRES_MAX_CONNECTIONS")
    min_connections: PositiveInt = Field(5, env="POSTGRES_MIN_CONNECTIONS") 
    pool_timeout: PositiveInt = Field(30, env="POSTGRES_POOL_TIMEOUT")
    
    # TimescaleDB settings
    timescaledb_enabled: bool = Field(True, env="TIMESCALEDB_ENABLED")
    chunk_time_interval: str = Field("7d", env="TIMESCALE_CHUNK_TIME_INTERVAL")
    
    # pgvector settings
    pgvector_enabled: bool = Field(True, env="PGVECTOR_ENABLED")
    vector_dimension: PositiveInt = Field(1536, env="VECTOR_DIMENSION")
    
    # Connection URL override (optional)
    url: Optional[str] = Field(None, env="DATABASE_URL")
    
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password meets minimum security requirements."""
        if len(v) < 8:
            raise ValueError("Database password must be at least 8 characters long")
        return v
    
    @field_validator("min_connections")
    @classmethod
    def validate_connection_pool(cls, v, info):
        """Ensure min_connections <= max_connections."""
        if info.data and "max_connections" in info.data and v > info.data["max_connections"]:
            raise ValueError("min_connections cannot exceed max_connections")
        return v
    
    @property
    def connection_url(self) -> str:
        """Generate database connection URL if not explicitly set."""
        if self.url:
            return self.url
        from urllib.parse import quote_plus
        return f"postgresql://{quote_plus(self.username)}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.database}"
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class RedisSettings(BaseSettings):
    """Redis configuration for task queues and caching."""
    
    # Connection parameters
    host: str = Field("localhost", env="REDIS_HOST")
    port: PositiveInt = Field(6379, env="REDIS_PORT")
    database: conint(ge=0, le=15) = Field(0, env="REDIS_DB")
    password: Optional[str] = Field(None, env="REDIS_PASSWORD")
    
    # Connection pool settings
    max_connections: PositiveInt = Field(10, env="REDIS_MAX_CONNECTIONS")
    socket_timeout: PositiveInt = Field(30, env="REDIS_SOCKET_TIMEOUT")
    socket_connect_timeout: PositiveInt = Field(30, env="REDIS_SOCKET_CONNECT_TIMEOUT")
    
    # Task queue configuration
    stream_name: str = Field("seo:tasks", env="REDIS_STREAM_NAME")
    consumer_group: str = Field("seo-agents", env="REDIS_CONSUMER_GROUP")
    consumer_timeout: PositiveInt = Field(30000, env="REDIS_CONSUMER_TIMEOUT")
    max_stream_length: PositiveInt = Field(10000, env="REDIS_MAX_STREAM_LENGTH")
    
    # Caching settings
    cache_ttl: PositiveInt = Field(3600, env="REDIS_CACHE_TTL")
    cache_prefix: str = Field("seo:cache", env="REDIS_CACHE_PREFIX")
    
    # Connection URL override (optional)
    url: Optional[str] = Field(None, env="REDIS_URL")
    
    @property
    def connection_url(self) -> str:
        """Generate Redis connection URL if not explicitly set."""
        if self.url:
            return self.url
        
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.database}"
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class NATSSettings(BaseSettings):
    """NATS configuration for approval workflows and notifications."""
    
    # Connection parameters
    host: str = Field("localhost", env="NATS_HOST")
    port: PositiveInt = Field(4222, env="NATS_PORT")
    http_port: PositiveInt = Field(8222, env="NATS_HTTP_PORT")
    
    # Authentication (optional)
    user: Optional[str] = Field(None, env="NATS_USER")
    password: Optional[str] = Field(None, env="NATS_PASSWORD") 
    
    # JetStream configuration
    jetstream_enabled: bool = Field(True, env="NATS_JETSTREAM_ENABLED")
    stream_approval: str = Field("seo-approvals", env="NATS_STREAM_APPROVAL")
    stream_alerts: str = Field("seo-alerts", env="NATS_STREAM_ALERTS")
    stream_tasks: str = Field("seo-tasks", env="NATS_STREAM_TASKS")
    
    # Approval workflow settings
    approval_timeout: PositiveInt = Field(300, env="APPROVAL_TIMEOUT")
    approval_retry_attempts: PositiveInt = Field(3, env="APPROVAL_RETRY_ATTEMPTS")
    approval_subjects_prefix: str = Field("approvals", env="APPROVAL_SUBJECTS_PREFIX")
    
    # Connection URL override (optional)
    url: Optional[str] = Field(None, env="NATS_URL")
    
    @property
    def connection_url(self) -> str:
        """Generate NATS connection URL if not explicitly set."""
        if self.url:
            return self.url
        
        auth = f"{self.user}:{self.password}@" if self.user and self.password else ""
        return f"nats://{auth}{self.host}:{self.port}"
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class ExternalAPISettings(BaseSettings):
    """External API credentials and configuration."""
    
    # Google Search Console
    gsc_api_key: constr(min_length=10) = Field(..., env="GSC_API_KEY")
    gsc_client_id: constr(min_length=10) = Field(..., env="GSC_CLIENT_ID")
    gsc_client_secret: constr(min_length=10) = Field(..., env="GSC_CLIENT_SECRET")
    gsc_redirect_uri: HttpUrl = Field(..., env="GSC_REDIRECT_URI")
    
    # Google Analytics 4
    ga4_api_key: constr(min_length=10) = Field(..., env="GA4_API_KEY")
    ga4_client_id: constr(min_length=10) = Field(..., env="GA4_CLIENT_ID")
    ga4_client_secret: constr(min_length=10) = Field(..., env="GA4_CLIENT_SECRET")
    ga4_redirect_uri: HttpUrl = Field(..., env="GA4_REDIRECT_URI")
    
    # SerpAPI
    serpapi_key: constr(min_length=10) = Field(..., env="SERPAPI_KEY")
    
    # Rate limiting (requests per minute)
    rate_limit_gsc: PositiveInt = Field(200, env="API_RATE_LIMIT_GSC")
    rate_limit_ga4: PositiveInt = Field(200, env="API_RATE_LIMIT_GA4")
    rate_limit_serpapi: PositiveInt = Field(100, env="API_RATE_LIMIT_SERPAPI")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class SecuritySettings(BaseSettings):
    """Security and authentication configuration."""
    
    # JWT settings
    jwt_secret_key: constr(min_length=32) = Field(..., env="JWT_SECRET_KEY")
    jwt_algorithm: JWTAlgorithm = Field(JWTAlgorithm.HS256, env="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: PositiveInt = Field(30, env="JWT_ACCESS_TOKEN_EXPIRE_MINUTES")
    jwt_refresh_token_expire_days: PositiveInt = Field(7, env="JWT_REFRESH_TOKEN_EXPIRE_DAYS")
    
    # Encryption
    encryption_key: constr(min_length=32) = Field(..., env="ENCRYPTION_KEY")
    
    # CORS settings
    cors_origins: str = Field("http://localhost:3000,http://127.0.0.1:3000", env="CORS_ORIGINS")
    cors_allow_credentials: bool = Field(True, env="CORS_ALLOW_CREDENTIALS")
    cors_allow_methods: str = Field("GET,POST,PUT,DELETE,OPTIONS", env="CORS_ALLOW_METHODS")
    cors_allow_headers: str = Field("*", env="CORS_ALLOW_HEADERS")
    
    # API rate limiting
    api_max_requests_per_minute: PositiveInt = Field(100, env="API_MAX_REQUESTS_PER_MINUTE")
    api_max_requests_per_hour: PositiveInt = Field(1000, env="API_MAX_REQUESTS_PER_HOUR")
    
    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v):
        """Validate JWT secret key strength."""
        if len(v) < 32:
            raise ValueError("JWT secret key must be at least 32 characters long")
        return v
    
    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, v):
        """Validate encryption key format."""
        if len(v) < 32:
            raise ValueError("Encryption key must be at least 32 characters long")
        return v
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins string to list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    @property  
    def cors_methods_list(self) -> List[str]:
        """Parse CORS methods string to list."""
        return [method.strip() for method in self.cors_allow_methods.split(",")]
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class ApplicationSettings(BaseSettings):
    """Application-specific configuration."""
    
    # Web dashboard settings
    web_host: str = Field("localhost", env="WEB_HOST")
    web_port: PositiveInt = Field(3000, env="WEB_PORT")
    web_url: HttpUrl = Field("http://localhost:3000", env="WEB_URL")
    
    # Agent orchestration
    agent_max_concurrent_tasks: PositiveInt = Field(5, env="AGENT_MAX_CONCURRENT_TASKS")
    agent_task_timeout: PositiveInt = Field(1800, env="AGENT_TASK_TIMEOUT")
    agent_retry_attempts: PositiveInt = Field(3, env="AGENT_RETRY_ATTEMPTS")
    agent_backoff_factor: PositiveInt = Field(2, env="AGENT_BACKOFF_FACTOR")
    
    # Content generation
    content_max_words: PositiveInt = Field(2000, env="CONTENT_MAX_WORDS")
    content_min_words: PositiveInt = Field(300, env="CONTENT_MIN_WORDS")
    content_readability_target: conint(ge=1, le=20) = Field(8, env="CONTENT_READABILITY_TARGET")
    
    # SEO analysis
    seo_keyword_density_max: float = Field(3.0, env="SEO_KEYWORD_DENSITY_MAX")
    seo_title_length_max: PositiveInt = Field(60, env="SEO_TITLE_LENGTH_MAX")
    seo_meta_description_length_max: PositiveInt = Field(155, env="SEO_META_DESCRIPTION_LENGTH_MAX")
    seo_h1_count_max: PositiveInt = Field(1, env="SEO_H1_COUNT_MAX")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class CMSIntegrationSettings(BaseSettings):
    """Content Management System integration configuration."""
    
    # WordPress settings
    wordpress_sites: Optional[str] = Field(None, env="WORDPRESS_SITES")
    wordpress_default_author_id: PositiveInt = Field(1, env="WORDPRESS_DEFAULT_AUTHOR_ID")
    wordpress_post_status: PostStatus = Field(PostStatus.DRAFT, env="WORDPRESS_POST_STATUS")
    wordpress_media_upload_max_size: PositiveInt = Field(5242880, env="WORDPRESS_MEDIA_UPLOAD_MAX_SIZE")
    
    # Custom CMS settings
    custom_cms_api_base_url: Optional[HttpUrl] = Field(None, env="CUSTOM_CMS_API_BASE_URL")
    custom_cms_api_key: Optional[constr(min_length=10)] = Field(None, env="CUSTOM_CMS_API_KEY")
    custom_cms_webhook_secret: Optional[constr(min_length=16)] = Field(None, env="CUSTOM_CMS_WEBHOOK_SECRET")
    
    @field_validator("wordpress_sites")
    @classmethod
    def validate_wordpress_sites_json(cls, v):
        """Validate WordPress sites JSON format if provided."""
        if v:
            try:
                import json
                json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("WORDPRESS_SITES must be valid JSON")
        return v
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class MonitoringSettings(BaseSettings):
    """Monitoring and observability configuration."""
    
    # Application monitoring
    monitoring_enabled: bool = Field(True, env="MONITORING_ENABLED")
    health_check_interval: PositiveInt = Field(30, env="HEALTH_CHECK_INTERVAL")
    metrics_collection_enabled: bool = Field(True, env="METRICS_COLLECTION_ENABLED")
    
    # Performance monitoring
    performance_monitoring: bool = Field(True, env="PERFORMANCE_MONITORING")
    slow_query_threshold: PositiveInt = Field(1000, env="SLOW_QUERY_THRESHOLD")
    slow_api_call_threshold: PositiveInt = Field(5000, env="SLOW_API_CALL_THRESHOLD")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class DevelopmentSettings(BaseSettings):
    """Development and testing configuration."""
    
    # Development toggles
    auto_migrate: bool = Field(True, env="DEV_AUTO_MIGRATE")
    seed_database: bool = Field(False, env="DEV_SEED_DATABASE")
    mock_external_apis: bool = Field(False, env="DEV_MOCK_EXTERNAL_APIS")
    skip_approval_gate: bool = Field(False, env="DEV_SKIP_APPROVAL_GATE")
    
    # Test environment URLs
    test_database_url: Optional[str] = Field(None, env="TEST_DATABASE_URL")
    test_redis_url: Optional[str] = Field(None, env="TEST_REDIS_URL")
    test_nats_url: Optional[str] = Field(None, env="TEST_NATS_URL")
    
    @field_validator("skip_approval_gate")
    @classmethod
    def validate_approval_gate_safety(cls, v):
        """Prevent skipping approval gate in production."""
        # This will be validated by the main Settings class based on environment
        return v
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class RateLimiterSettings(BaseSettings):
    """Rate limiter configuration for external API integrations."""
    
    # Global rate limiter settings
    enabled: bool = Field(True, env="RATE_LIMITER_ENABLED")
    algorithm: str = Field("sliding_window", env="RATE_LIMITER_ALGORITHM")
    
    # Circuit breaker configuration
    circuit_breaker_enabled: bool = Field(True, env="CIRCUIT_BREAKER_ENABLED") 
    failure_threshold: PositiveInt = Field(5, env="CIRCUIT_BREAKER_FAILURE_THRESHOLD")
    recovery_timeout: PositiveInt = Field(60, env="CIRCUIT_BREAKER_RECOVERY_TIMEOUT")
    success_threshold: PositiveInt = Field(3, env="CIRCUIT_BREAKER_SUCCESS_THRESHOLD")
    
    # Exponential backoff configuration
    backoff_enabled: bool = Field(True, env="BACKOFF_ENABLED")
    backoff_base_delay: float = Field(1.0, env="BACKOFF_BASE_DELAY")
    backoff_max_delay: float = Field(300.0, env="BACKOFF_MAX_DELAY")
    backoff_max_attempts: PositiveInt = Field(5, env="BACKOFF_MAX_ATTEMPTS")
    backoff_jitter_type: str = Field("full", env="BACKOFF_JITTER_TYPE")
    
    # Google Search Console rate limits
    gsc_requests_per_minute: PositiveInt = Field(200, env="GSC_REQUESTS_PER_MINUTE")
    gsc_requests_per_day: PositiveInt = Field(1200, env="GSC_REQUESTS_PER_DAY")
    gsc_burst_capacity: Optional[PositiveInt] = Field(250, env="GSC_BURST_CAPACITY")
    gsc_priority_reserve: float = Field(0.1, env="GSC_PRIORITY_RESERVE")
    
    # Google Analytics 4 rate limits
    ga4_requests_per_minute: PositiveInt = Field(200, env="GA4_REQUESTS_PER_MINUTE")
    ga4_requests_per_day: PositiveInt = Field(10000, env="GA4_REQUESTS_PER_DAY")
    ga4_burst_capacity: Optional[PositiveInt] = Field(250, env="GA4_BURST_CAPACITY")
    ga4_priority_reserve: float = Field(0.1, env="GA4_PRIORITY_RESERVE")
    
    # SerpAPI rate limits (plan dependent)
    serpapi_requests_per_minute: PositiveInt = Field(100, env="SERPAPI_REQUESTS_PER_MINUTE")
    serpapi_requests_per_month: PositiveInt = Field(100, env="SERPAPI_REQUESTS_PER_MONTH")
    serpapi_burst_capacity: Optional[PositiveInt] = Field(120, env="SERPAPI_BURST_CAPACITY")
    serpapi_priority_reserve: float = Field(0.05, env="SERPAPI_PRIORITY_RESERVE")
    
    @field_validator("algorithm")
    @classmethod
    def validate_algorithm(cls, v):
        """Validate rate limiting algorithm choice."""
        allowed_algorithms = ["sliding_window", "token_bucket"]
        if v not in allowed_algorithms:
            raise ValueError(f"Algorithm must be one of: {allowed_algorithms}")
        return v
    
    @field_validator("backoff_jitter_type") 
    @classmethod
    def validate_jitter_type(cls, v):
        """Validate jitter type choice."""
        allowed_jitter = ["none", "equal", "full", "decorrelated"] 
        if v not in allowed_jitter:
            raise ValueError(f"Jitter type must be one of: {allowed_jitter}")
        return v
    
    @field_validator("gsc_priority_reserve", "ga4_priority_reserve", "serpapi_priority_reserve")
    @classmethod
    def validate_priority_reserve(cls, v):
        """Validate priority reserve percentage."""
        if not 0 <= v <= 1:
            raise ValueError("Priority reserve must be between 0 and 1")
        return v
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class Settings(BaseSettings):
    """Main settings class that aggregates all configuration sections."""
    
    # Define the fields as class attributes  
    app: AppSettings
    database: DatabaseSettings
    redis: RedisSettings
    nats: NATSSettings
    external_apis: ExternalAPISettings
    security: SecuritySettings
    application: ApplicationSettings
    cms: CMSIntegrationSettings
    monitoring: MonitoringSettings
    development: DevelopmentSettings
    rate_limiter: RateLimiterSettings
    
    def __init__(self, **kwargs):
        """Initialize settings with cross-validation."""
        # Initialize individual setting sections first
        kwargs['app'] = AppSettings()
        kwargs['database'] = DatabaseSettings()
        kwargs['redis'] = RedisSettings()
        kwargs['nats'] = NATSSettings()
        kwargs['external_apis'] = ExternalAPISettings()
        kwargs['security'] = SecuritySettings()
        kwargs['application'] = ApplicationSettings()
        kwargs['cms'] = CMSIntegrationSettings()
        kwargs['monitoring'] = MonitoringSettings()
        kwargs['development'] = DevelopmentSettings()
        kwargs['rate_limiter'] = RateLimiterSettings()
        
        super().__init__(**kwargs)
        
        # Run cross-validation
        self._validate_production_safety()
        self._validate_development_constraints()
    
    def _validate_production_safety(self):
        """Ensure production environment has secure configuration."""
        if self.app.environment == Environment.PRODUCTION:
            # Ensure debug is disabled in production
            if self.app.debug:
                raise ValueError("DEBUG must be False in production environment")
            
            # Ensure approval gate is not skipped in production
            if self.development.skip_approval_gate:
                raise ValueError("DEV_SKIP_APPROVAL_GATE must be False in production environment")
            
            # Ensure strong passwords in production
            if self.database.password == "your_secure_postgres_password_here":
                raise ValueError("Must set real database password in production")
            
            # Ensure real API keys in production
            placeholder_keys = [
                "your_google_search_console_api_key_here",
                "your_ga4_api_key_here", 
                "your_serpapi_key_here"
            ]
            if any(key in placeholder_keys for key in [
                self.external_apis.gsc_api_key,
                self.external_apis.ga4_api_key,
                self.external_apis.serpapi_key
            ]):
                raise ValueError("Must set real API keys in production")
    
    def _validate_development_constraints(self):
        """Apply development-specific validation rules."""
        if self.app.environment == Environment.DEVELOPMENT:
            # Warn about insecure development settings but allow them
            pass
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }
        
    def model_dump_safe(self) -> Dict[str, Any]:
        """Export settings with sensitive values masked."""
        data = self.model_dump()
        
        # Mask sensitive values
        sensitive_fields = [
            ("database", "password"),
            ("redis", "password"),
            ("nats", "password"),
            ("external_apis", "gsc_api_key"),
            ("external_apis", "gsc_client_secret"),
            ("external_apis", "ga4_api_key"),
            ("external_apis", "ga4_client_secret"),
            ("external_apis", "serpapi_key"),
            ("security", "jwt_secret_key"),
            ("security", "encryption_key"),
            ("cms", "custom_cms_api_key"),
            ("cms", "custom_cms_webhook_secret")
        ]
        
        for section, field in sensitive_fields:
            if section in data and field in data[section] and data[section][field]:
                data[section][field] = "***MASKED***"
        
        return data


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    This function uses LRU cache to ensure settings are loaded only once
    and reused throughout the application lifecycle.
    
    Returns:
        Settings: Fully validated settings instance
        
    Raises:
        ValidationError: If any configuration validation fails
        ValueError: If environment-specific validation fails
    """
    return Settings()


def reload_settings() -> Settings:
    """
    Force reload settings by clearing the cache.
    
    This is useful for testing or when environment variables change at runtime.
    
    Returns:
        Settings: Fresh settings instance
    """
    get_settings.cache_clear()
    return get_settings()


# Convenience function for getting individual setting sections
def get_database_settings() -> DatabaseSettings:
    """Get database configuration section."""
    return get_settings().database


def get_redis_settings() -> RedisSettings:
    """Get Redis configuration section.""" 
    return get_settings().redis


def get_nats_settings() -> NATSSettings:
    """Get NATS configuration section."""
    return get_settings().nats


def get_external_api_settings() -> ExternalAPISettings:
    """Get external API configuration section."""
    return get_settings().external_apis


def get_security_settings() -> SecuritySettings:
    """Get security configuration section."""
    return get_settings().security
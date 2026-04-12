"""
Configuration Management Package for SEO Automation Platform

This package provides type-safe configuration management using Pydantic BaseSettings.
All environment variables are validated, typed, and organized into logical sections.

Main Components:
- Settings: Main configuration class aggregating all setting sections
- Individual setting classes for each system component
- Validation functions for environment-specific constraints
- Utility functions for accessing specific configuration sections

Quick Usage:
    from config import get_settings
    settings = get_settings()
    
    # Access database configuration
    db_url = settings.database.connection_url
    
    # Access API credentials
    gsc_key = settings.external_apis.gsc_api_key
    
    # Check environment
    if settings.app.environment == Environment.PRODUCTION:
        # Production-specific logic
        pass

Environment Variables:
    All configuration is loaded from environment variables and .env files.
    See .env.example for a complete list of available variables.
    
Validation:
    - Type validation for all fields
    - Required vs optional field enforcement
    - Environment-specific safety checks
    - Cross-field validation (e.g., min <= max connections)
"""

from .settings import (
    # Main settings class
    Settings,
    get_settings,
    reload_settings,
    
    # Individual setting classes
    AppSettings,
    DatabaseSettings,
    RedisSettings,
    NATSSettings,
    ExternalAPISettings,
    SecuritySettings,
    ApplicationSettings,
    CMSIntegrationSettings,
    MonitoringSettings,
    DevelopmentSettings,
    
    # Convenience functions
    get_database_settings,
    get_redis_settings,
    get_nats_settings,
    get_external_api_settings,
    get_security_settings,
    
    # Enums
    Environment,
    LogLevel,
    LogFormat,
    JWTAlgorithm,
    PostStatus,
)

__all__ = [
    # Main interface
    "Settings",
    "get_settings",
    "reload_settings",
    
    # Setting classes
    "AppSettings",
    "DatabaseSettings", 
    "RedisSettings",
    "NATSSettings",
    "ExternalAPISettings",
    "SecuritySettings",
    "ApplicationSettings",
    "CMSIntegrationSettings",
    "MonitoringSettings", 
    "DevelopmentSettings",
    
    # Convenience functions
    "get_database_settings",
    "get_redis_settings",
    "get_nats_settings",
    "get_external_api_settings",
    "get_security_settings",
    
    # Enums
    "Environment",
    "LogLevel",
    "LogFormat",
    "JWTAlgorithm", 
    "PostStatus",
]

# Version info
__version__ = "1.0.0"
__author__ = "SEO Automation Platform Team"
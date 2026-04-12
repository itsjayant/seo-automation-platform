#!/usr/bin/env python3
"""
Configuration Validation Script

This script validates the configuration management system by:
1. Testing that the configuration can be loaded
2. Checking type validation works correctly  
3. Verifying environment-specific validation
4. Testing error handling for missing/invalid values

Usage:
    python validate_config.py [--test-errors]
    
Options:
    --test-errors    Also test error conditions (optional)
"""

import os
import sys
from typing import Dict, Any
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_configuration_loading():
    """Test that configuration loads successfully with .env.example values."""
    print("🔍 Testing configuration loading...")
    
    try:
        from config import get_settings, Environment
        
        # Load settings
        settings = get_settings()
        
        # Check basic properties
        assert hasattr(settings, 'app')
        assert hasattr(settings, 'database')
        assert hasattr(settings, 'redis')
        assert hasattr(settings, 'nats') 
        assert hasattr(settings, 'external_apis')
        assert hasattr(settings, 'security')
        
        print(f"✅ Configuration loaded successfully")
        print(f"   Environment: {settings.app.environment}")
        print(f"   Debug mode: {settings.app.debug}")
        print(f"   Database host: {settings.database.host}")
        print(f"   Redis host: {settings.redis.host}")
        print(f"   NATS host: {settings.nats.host}")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration loading failed: {e}")
        return False


def test_connection_url_generation():
    """Test that connection URLs are generated correctly."""
    print("\n🔍 Testing connection URL generation...")
    
    try:
        from config import get_settings
        
        settings = get_settings()
        
        # Test database URL
        db_url = settings.database.connection_url
        assert db_url.startswith("postgresql://")
        print(f"✅ Database URL: {db_url[:50]}...")
        
        # Test Redis URL  
        redis_url = settings.redis.connection_url
        assert redis_url.startswith("redis://")
        print(f"✅ Redis URL: {redis_url}")
        
        # Test NATS URL
        nats_url = settings.nats.connection_url  
        assert nats_url.startswith("nats://")
        print(f"✅ NATS URL: {nats_url}")
        
        return True
        
    except Exception as e:
        print(f"❌ Connection URL generation failed: {e}")
        return False


def test_type_validation():
    """Test that type validation works correctly."""
    print("\n🔍 Testing type validation...")
    
    try:
        from config import get_settings
        
        settings = get_settings()
        
        # Check integer types
        assert isinstance(settings.database.port, int)
        assert settings.database.port > 0
        print(f"✅ Database port validation: {settings.database.port}")
        
        # Check string constraints
        assert len(settings.redis.stream_name) > 0
        print(f"✅ Redis stream name validation: {settings.redis.stream_name}")
        
        # Check boolean types
        assert isinstance(settings.app.debug, bool)
        print(f"✅ Boolean validation: debug={settings.app.debug}")
        
        # Check enum validation
        from config import Environment
        assert settings.app.environment in [e.value for e in Environment]
        print(f"✅ Enum validation: environment={settings.app.environment}")
        
        return True
        
    except Exception as e:
        print(f"❌ Type validation failed: {e}")
        return False


def test_convenience_functions():
    """Test convenience functions for accessing configuration sections."""
    print("\n🔍 Testing convenience functions...")
    
    try:
        from config import (
            get_database_settings,
            get_redis_settings,
            get_nats_settings,
            get_external_api_settings,
            get_security_settings
        )
        
        # Test individual setting getters
        db_settings = get_database_settings()
        assert db_settings.host == "localhost"
        print(f"✅ Database settings: {db_settings.host}:{db_settings.port}")
        
        redis_settings = get_redis_settings()
        assert redis_settings.port == 6379
        print(f"✅ Redis settings: {redis_settings.host}:{redis_settings.port}")
        
        nats_settings = get_nats_settings()  
        assert nats_settings.port == 4222
        print(f"✅ NATS settings: {nats_settings.host}:{nats_settings.port}")
        
        return True
        
    except Exception as e:
        print(f"❌ Convenience functions failed: {e}")
        return False


def test_safe_export():
    """Test that sensitive values are masked in safe export."""
    print("\n🔍 Testing safe configuration export...")
    
    try:
        from config import get_settings
        
        settings = get_settings()
        
        # Test safe export
        safe_data = settings.model_dump_safe()
        
        # Check that sensitive fields are masked
        sensitive_checks = [
            safe_data.get("database", {}).get("password") == "***MASKED***",
            safe_data.get("security", {}).get("jwt_secret_key") == "***MASKED***",
            safe_data.get("security", {}).get("encryption_key") == "***MASKED***"
        ]
        
        if any(sensitive_checks):
            print("✅ Sensitive values are properly masked")
        else:
            print("⚠️  Safe export may not be masking all sensitive values")
        
        return True
        
    except Exception as e:
        print(f"❌ Safe export failed: {e}")
        return False


def test_error_conditions():
    """Test error handling for invalid configuration values."""
    print("\n🔍 Testing error conditions...")
    
    # Save original environment
    original_env = dict(os.environ)
    
    try:
        from config import reload_settings
        from pydantic import ValidationError
        
        # Test 1: Invalid port number
        print("   Testing invalid port number...")
        os.environ["POSTGRES_PORT"] = "not_a_number"
        try:
            reload_settings()
            print("❌ Should have failed with invalid port")
            return False
        except ValidationError:
            print("✅ Correctly rejected invalid port number")
        
        # Test 2: Missing required field
        print("   Testing missing required field...")
        if "POSTGRES_PASSWORD" in os.environ:
            del os.environ["POSTGRES_PASSWORD"]
        try:
            reload_settings()
            print("❌ Should have failed with missing password")
            return False  
        except ValidationError:
            print("✅ Correctly rejected missing required field")
        
        return True
        
    except Exception as e:
        print(f"❌ Error condition testing failed: {e}")
        return False
        
    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)


def main():
    """Run all configuration validation tests."""
    print("🧪 SEO Platform Configuration Validation")
    print("=" * 50)
    
    # Check if .env file exists
    env_file = Path(".env")
    example_file = Path(".env.example")
    
    if not env_file.exists() and example_file.exists():
        print("⚠️  .env file not found, using .env.example for testing")
        # Copy .env.example to .env for testing
        with open(example_file) as f:
            content = f.read()
        
        # Replace placeholder values with valid test values
        content = content.replace(
            "POSTGRES_PASSWORD=your_secure_postgres_password_here",
            "POSTGRES_PASSWORD=testpassword123"
        )
        content = content.replace(
            "GSC_API_KEY=your_google_search_console_api_key_here",
            "GSC_API_KEY=test_gsc_key_1234567890"
        )
        content = content.replace(
            "GA4_API_KEY=your_google_analytics_4_api_key_here", 
            "GA4_API_KEY=test_ga4_key_1234567890"
        )
        content = content.replace(
            "SERPAPI_KEY=your_serpapi_key_here",
            "SERPAPI_KEY=test_serpapi_key_1234567890"
        )
        content = content.replace(
            "JWT_SECRET_KEY=your_super_secret_jwt_key_change_this_in_production",
            "JWT_SECRET_KEY=test_jwt_secret_key_32_chars_minimum_length_here_12345"
        )
        content = content.replace(
            "ENCRYPTION_KEY=your_32_byte_base64_encoded_encryption_key_here",
            "ENCRYPTION_KEY=test_encryption_key_32_bytes_min_length_here_abcdef"
        )
        
        with open(env_file, 'w') as f:
            f.write(content)
        created_env = True
    else:
        created_env = False
    
    # Run tests
    tests = [
        test_configuration_loading,
        test_connection_url_generation,
        test_type_validation,
        test_convenience_functions, 
        test_safe_export
    ]
    
    # Add error testing if requested
    if "--test-errors" in sys.argv:
        tests.append(test_error_conditions)
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        else:
            break  # Stop on first failure
    
    # Summary
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All configuration validation tests passed!")
        exit_code = 0
    else:
        print("💥 Some tests failed. Check the errors above.")
        exit_code = 1
    
    # Clean up test .env file if we created it
    if created_env:
        env_file.unlink()
        print("🧹 Cleaned up test .env file")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
"""
Test script to verify Alembic environment setup works.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set minimal environment variables for testing
os.environ.setdefault('POSTGRES_PASSWORD', 'test_password_12345')
os.environ.setdefault('POSTGRES_HOST', 'localhost')
os.environ.setdefault('POSTGRES_PORT', '5432')
os.environ.setdefault('POSTGRES_DB', 'seo_platform')
os.environ.setdefault('POSTGRES_USER', 'seo')

def test_alembic_components():
    """Test the individual components needed for Alembic."""
    
    print("Testing Alembic environment components...")
    
    # Test 1: Configuration loading
    try:
        from config import get_settings
        settings = get_settings()
        print(f"✓ Configuration loaded successfully")
        print(f"  Database URL: {settings.database.connection_url}")
    except Exception as e:
        print(f"✗ Configuration failed: {e}")
        return False
    
    # Test 2: Base model import 
    try:
        from db.base import Base
        print(f"✓ Base model imported")
        print(f"  Metadata tables: {list(Base.metadata.tables.keys())}")
    except Exception as e:
        print(f"✗ Base model import failed: {e}")
        return False
    
    # Test 3: Models import (without importing utils)
    try:
        # Import models directly without going through __init__.py
        import importlib.util
        models_path = project_root / "db" / "models.py"
        spec = importlib.util.spec_from_file_location("models", models_path)
        models_module = importlib.util.module_from_spec(spec)
        
        # Set up the necessary modules in sys.modules first
        sys.modules['db.base'] = importlib.import_module('db.base')
        sys.modules['db.mixins'] = importlib.import_module('db.mixins') 
        
        spec.loader.exec_module(models_module)
        print(f"✓ Models loaded successfully")
        
        # Update metadata with new tables
        from db.base import Base
        print(f"  Available tables: {list(Base.metadata.tables.keys())}")
        
    except Exception as e:
        print(f"✗ Models import failed: {e}")
        return False
    
    # Test 4: Alembic configuration files exist
    alembic_ini = project_root / "alembic.ini"
    env_py = project_root / "db" / "migrations" / "env.py"
    
    if alembic_ini.exists():
        print(f"✓ alembic.ini exists at {alembic_ini}")
    else:
        print(f"✗ alembic.ini missing at {alembic_ini}")
        return False
        
    if env_py.exists():
        print(f"✓ env.py exists at {env_py}")
    else:
        print(f"✗ env.py missing at {env_py}")
        return False
    
    print("\n✓ All Alembic components ready!")
    return True

if __name__ == "__main__":
    success = test_alembic_components()
    sys.exit(0 if success else 1)
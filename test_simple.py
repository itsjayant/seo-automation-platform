#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("Testing basic configuration loading...")

try:
    from config.settings import DatabaseSettings
    
    print("✅ Import successful")
    
    # Try to load database settings only
    db_settings = DatabaseSettings()
    print(f"✅ Database settings loaded: {db_settings.host}:{db_settings.port}")
    print(f"   Database name: {db_settings.database}")
    print(f"   Username: {db_settings.username}")
    print(f"   Password length: {len(db_settings.password)} chars")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
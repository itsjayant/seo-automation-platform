#!/usr/bin/env python3
"""
Validate the initial database migration.

This script performs basic validation of the migration file:
- Import and syntax checking
- Function signature verification
- SQL statement parsing
"""

import sys
import os
import importlib.util
from pathlib import Path

def validate_migration():
    """Validate the initial migration file."""
    
    # Add project root to path
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))
    
    migration_path = project_root / "db" / "migrations" / "versions" / "001_initial_schema.py"
    
    if not migration_path.exists():
        print(f"❌ Migration file not found: {migration_path}")
        return False
    
    try:
        # Test import
        spec = importlib.util.spec_from_file_location("migration", migration_path)
        migration_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration_module)
        
        print("✅ Migration file imports successfully")
        
        # Check required attributes
        required_attrs = ['revision', 'down_revision', 'upgrade', 'downgrade']
        missing_attrs = []
        
        for attr in required_attrs:
            if not hasattr(migration_module, attr):
                missing_attrs.append(attr)
        
        if missing_attrs:
            print(f"❌ Missing required attributes: {missing_attrs}")
            return False
        
        print("✅ All required attributes present")
        
        # Check function signatures
        if not callable(migration_module.upgrade):
            print("❌ upgrade() is not callable")
            return False
        
        if not callable(migration_module.downgrade):
            print("❌ downgrade() is not callable")
            return False
            
        print("✅ upgrade() and downgrade() functions are callable")
        
        # Check revision metadata
        if migration_module.revision != '001_initial':
            print(f"❌ Unexpected revision ID: {migration_module.revision}")
            return False
        
        if migration_module.down_revision is not None:
            print(f"❌ Initial migration should have down_revision=None, got: {migration_module.down_revision}")
            return False
        
        print("✅ Migration metadata is correct")
        
        print("\n🎉 Migration validation passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except SyntaxError as e:
        print(f"❌ Syntax error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def check_table_consistency():
    """Check that all expected tables are created in upgrade() and dropped in downgrade()."""
    
    expected_tables = {
        'sites',
        'keywords', 
        'rankings',
        'gsc_metrics',
        'ga4_metrics',
        'audit_log'
    }
    
    migration_path = Path(__file__).parent / "db" / "migrations" / "versions" / "001_initial_schema.py"
    
    with open(migration_path, 'r') as f:
        content = f.read()
    
    # Check upgrade function
    upgrade_creates = set()
    for table in expected_tables:
        if f"create_table('{table}'" in content or f'create_table(\n        \'{table}\'' in content:
            upgrade_creates.add(table)
    
    missing_creates = expected_tables - upgrade_creates
    if missing_creates:
        print(f"❌ Tables not created in upgrade(): {missing_creates}")
        return False
    
    print("✅ All expected tables are created in upgrade()")
    
    # Check downgrade function
    downgrade_drops = set()
    for table in expected_tables:
        if f"drop_table('{table}')" in content:
            downgrade_drops.add(table)
    
    missing_drops = expected_tables - downgrade_drops
    if missing_drops:
        print(f"❌ Tables not dropped in downgrade(): {missing_drops}")
        return False
    
    print("✅ All tables are dropped in downgrade()")
    
    return True

def check_timescaledb_features():
    """Check that TimescaleDB hypertables are properly configured."""
    
    migration_path = Path(__file__).parent / "db" / "migrations" / "versions" / "001_initial_schema.py"
    
    with open(migration_path, 'r') as f:
        content = f.read()
    
    # Check for TimescaleDB extension
    if "CREATE EXTENSION IF NOT EXISTS timescaledb" not in content:
        print("❌ TimescaleDB extension not enabled")
        return False
    
    print("✅ TimescaleDB extension is enabled")
    
    # Check for hypertable creation
    hypertables = ['rankings', 'gsc_metrics', 'ga4_metrics']
    
    for table in hypertables:
        if f"create_hypertable('{table}'" not in content:
            print(f"❌ Hypertable not created for {table}")
            return False
    
    print("✅ All time-series tables are converted to hypertables")
    
    return True

def check_pgvector_features():
    """Check that pgvector features are properly configured."""
    
    migration_path = Path(__file__).parent / "db" / "migrations" / "versions" / "001_initial_schema.py"
    
    with open(migration_path, 'r') as f:
        content = f.read()
    
    # Check for vector extension
    if "CREATE EXTENSION IF NOT EXISTS vector" not in content:
        print("❌ pgvector extension not enabled")
        return False
    
    print("✅ pgvector extension is enabled")
    
    # Check for Vector column type
    if "pgvector.sqlalchemy.Vector(1536)" not in content:
        print("❌ Vector column type not found")
        return False
    
    print("✅ Vector column type is properly configured")
    
    # Check for vector index
    if "ix_keywords_embedding_cosine" not in content:
        print("❌ Vector similarity index not created")
        return False
    
    print("✅ Vector similarity index is created")
    
    return True

def main():
    """Run all validation checks."""
    
    print("🔍 Validating initial database migration...\n")
    
    checks = [
        ("Basic migration validation", validate_migration),
        ("Table consistency check", check_table_consistency),
        ("TimescaleDB features check", check_timescaledb_features),
        ("pgvector features check", check_pgvector_features),
    ]
    
    all_passed = True
    
    for check_name, check_func in checks:
        print(f"\n📋 {check_name}")
        print("-" * 50)
        
        if not check_func():
            all_passed = False
    
    print("\n" + "=" * 60)
    
    if all_passed:
        print("🎉 All validation checks passed!")
        print("✅ Migration is ready for deployment")
        return 0
    else:
        print("❌ Some validation checks failed")
        print("🔧 Please fix the issues before proceeding")
        return 1

if __name__ == "__main__":
    sys.exit(main())
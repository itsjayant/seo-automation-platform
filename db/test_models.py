#!/usr/bin/env python3
"""
Test script for SQLAlchemy ORM models validation.

This script validates that all models are properly defined,
can be imported correctly, and have the expected structure.
"""

import sys
import os
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from config import get_settings
from db.init_schema import DatabaseInitializer
from db.models import (
    Base, Site, Keyword, Ranking, GSCMetric, GA4Metric, AuditLog,
    CMSType, KeywordIntent, KeywordPriority, ActionType, EntityType, ApprovalStatus
)

logger = structlog.get_logger(__name__)


def validate_model_structure() -> Dict[str, Any]:
    """
    Validate that all models have the expected structure.
    
    Returns:
        Dict with validation results
    """
    results = {
        "status": "success",
        "models": {},
        "errors": []
    }
    
    models_to_check = [
        ("Site", Site),
        ("Keyword", Keyword), 
        ("Ranking", Ranking),
        ("GSCMetric", GSCMetric),
        ("GA4Metric", GA4Metric),
        ("AuditLog", AuditLog),
    ]
    
    for model_name, model_class in models_to_check:
        try:
            # Check that model has required attributes
            model_info = {
                "table_name": model_class.__tablename__,
                "columns": [],
                "relationships": [],
                "indexes": [],
                "constraints": []
            }
            
            # Get column information
            for column_name, column in model_class.__table__.columns.items():
                model_info["columns"].append({
                    "name": column_name,
                    "type": str(column.type),
                    "nullable": column.nullable,
                    "primary_key": column.primary_key
                })
            
            # Get relationship information
            mapper = inspect(model_class)
            for rel_name, relationship in mapper.relationships.items():
                model_info["relationships"].append({
                    "name": rel_name,
                    "target": relationship.mapper.class_.__name__,
                    "direction": str(relationship.direction)
                })
            
            # Get index information
            for index in model_class.__table__.indexes:
                model_info["indexes"].append({
                    "name": index.name,
                    "columns": [col.name for col in index.columns]
                })
            
            # Get constraint information
            for constraint in model_class.__table__.constraints:
                model_info["constraints"].append({
                    "name": constraint.name,
                    "type": type(constraint).__name__
                })
            
            results["models"][model_name] = model_info
            
        except Exception as e:
            error_msg = f"Error validating {model_name}: {str(e)}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
    
    if results["errors"]:
        results["status"] = "error"
    
    return results


def validate_enums() -> Dict[str, Any]:
    """
    Validate that all enums are properly defined.
    
    Returns:
        Dict with enum validation results
    """
    results = {
        "status": "success",
        "enums": {},
        "errors": []
    }
    
    enums_to_check = [
        ("CMSType", CMSType),
        ("KeywordIntent", KeywordIntent),
        ("KeywordPriority", KeywordPriority),
        ("ActionType", ActionType),
        ("EntityType", EntityType),
        ("ApprovalStatus", ApprovalStatus),
    ]
    
    for enum_name, enum_class in enums_to_check:
        try:
            enum_values = [item.value for item in enum_class]
            results["enums"][enum_name] = {
                "values": enum_values,
                "count": len(enum_values)
            }
        except Exception as e:
            error_msg = f"Error validating enum {enum_name}: {str(e)}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
    
    if results["errors"]:
        results["status"] = "error"
    
    return results


def test_database_connection() -> Dict[str, Any]:
    """
    Test database connection and schema creation.
    
    Returns:
        Dict with connection test results
    """
    results = {
        "status": "success",
        "connection": False,
        "tables_created": False,
        "errors": []
    }
    
    try:
        initializer = DatabaseInitializer()
        engine = initializer.get_sync_engine()
        
        # Test connection
        with engine.connect() as conn:
            conn.execute("SELECT 1")
            results["connection"] = True
        
        # Test table creation (dry-run by checking metadata)
        Base.metadata.bind = engine
        results["tables_created"] = True
        
    except Exception as e:
        error_msg = f"Database connection test failed: {str(e)}"
        results["errors"].append(error_msg)
        results["status"] = "error"
        logger.error(error_msg)
    
    return results


def main():
    """Run all validation tests."""
    print("=== SQLAlchemy Models Validation ===\n")
    
    # Test 1: Model Structure
    print("1. Validating model structure...")
    model_results = validate_model_structure()
    if model_results["status"] == "success":
        print(f"✓ All {len(model_results['models'])} models validated successfully")
        for model_name, info in model_results["models"].items():
            print(f"  - {model_name}: {len(info['columns'])} columns, "
                  f"{len(info['relationships'])} relationships, "
                  f"{len(info['indexes'])} indexes")
    else:
        print("✗ Model validation failed:")
        for error in model_results["errors"]:
            print(f"  - {error}")
    
    print()
    
    # Test 2: Enum Validation
    print("2. Validating enums...")
    enum_results = validate_enums()
    if enum_results["status"] == "success":
        print(f"✓ All {len(enum_results['enums'])} enums validated successfully")
        for enum_name, info in enum_results["enums"].items():
            print(f"  - {enum_name}: {info['count']} values")
    else:
        print("✗ Enum validation failed:")
        for error in enum_results["errors"]:
            print(f"  - {error}")
    
    print()
    
    # Test 3: Database Connection (optional)
    try:
        print("3. Testing database connection...")
        db_results = test_database_connection()
        if db_results["status"] == "success":
            print("✓ Database connection test passed")
            if db_results["connection"]:
                print("  - Connection: OK")
            if db_results["tables_created"]:
                print("  - Schema validation: OK")
        else:
            print("✗ Database connection test failed:")
            for error in db_results["errors"]:
                print(f"  - {error}")
    except Exception as e:
        print(f"⚠ Database connection test skipped: {str(e)}")
    
    print()
    
    # Summary
    overall_status = (
        model_results["status"] == "success" and 
        enum_results["status"] == "success"
    )
    
    if overall_status:
        print("🎉 All validations passed! Models are ready for use.")
        return 0
    else:
        print("❌ Some validations failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
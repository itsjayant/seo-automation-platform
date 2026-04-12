#!/usr/bin/env python3
"""
Simple validation test for SQLAlchemy models.

Tests just the models without other dependencies.
"""

import sys
import os
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog
from sqlalchemy import inspect

# Import models directly without going through __init__.py
import importlib.util
import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Direct import of models file to avoid __init__.py issues
models_path = os.path.join(os.path.dirname(__file__), 'models.py')
spec = importlib.util.spec_from_file_location("models", models_path)
models_module = importlib.util.module_from_spec(spec)
sys.modules["models"] = models_module
spec.loader.exec_module(models_module)

# Import the classes
Base = models_module.Base
Site = models_module.Site
Keyword = models_module.Keyword
Ranking = models_module.Ranking
GSCMetric = models_module.GSCMetric
GA4Metric = models_module.GA4Metric
AuditLog = models_module.AuditLog
CMSType = models_module.CMSType
KeywordIntent = models_module.KeywordIntent
KeywordPriority = models_module.KeywordPriority
ActionType = models_module.ActionType
EntityType = models_module.EntityType
ApprovalStatus = models_module.ApprovalStatus

logger = structlog.get_logger(__name__)


def test_imports():
    """Test that all models can be imported successfully."""
    print("✓ All models imported successfully")
    return True


def test_enums():
    """Test that all enums work correctly."""
    try:
        # Test CMSType
        assert CMSType.WORDPRESS == "wordpress"
        assert CMSType.CUSTOM == "custom"
        
        # Test KeywordIntent
        assert KeywordIntent.INFORMATIONAL == "informational"
        assert KeywordIntent.NAVIGATIONAL == "navigational"
        assert KeywordIntent.TRANSACTIONAL == "transactional"
        
        # Test ActionType
        assert ActionType.KEYWORD_RESEARCH == "keyword_research"
        assert ActionType.CONTENT_GENERATION == "content_generation"
        
        print("✓ All enums working correctly")
        return True
    except Exception as e:
        print(f"✗ Enum test failed: {e}")
        return False


def test_model_structure():
    """Test model structure basics."""
    try:
        models_to_test = [Site, Keyword, Ranking, GSCMetric, GA4Metric, AuditLog]
        
        for model_class in models_to_test:
            # Check table name
            assert hasattr(model_class, '__tablename__')
            
            # Check it has columns
            assert hasattr(model_class, '__table__')
            assert len(model_class.__table__.columns) > 0
            
            # Check it can be inspected
            mapper = inspect(model_class)
            assert mapper is not None
        
        print(f"✓ {len(models_to_test)} models have correct structure")
        return True
    except Exception as e:
        print(f"✗ Model structure test failed: {e}")
        return False


def test_relationships():
    """Test model relationships."""
    try:
        # Test Site relationships
        site_mapper = inspect(Site)
        site_rels = site_mapper.relationships.keys()
        expected_site_rels = ['keywords', 'rankings', 'gsc_metrics', 'ga4_metrics']
        
        for rel in expected_site_rels:
            assert rel in site_rels
        
        # Test Keyword relationships
        keyword_mapper = inspect(Keyword)
        keyword_rels = keyword_mapper.relationships.keys()
        expected_keyword_rels = ['site', 'rankings']
        
        for rel in expected_keyword_rels:
            assert rel in keyword_rels
        
        print("✓ Model relationships defined correctly")
        return True
    except Exception as e:
        print(f"✗ Relationships test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=== Simple SQLAlchemy Models Test ===\n")
    
    tests = [
        ("Import test", test_imports),
        ("Enum test", test_enums),
        ("Model structure test", test_model_structure),
        ("Relationships test", test_relationships),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"Running {test_name}...")
        try:
            if test_func():
                passed += 1
            print()
        except Exception as e:
            print(f"✗ {test_name} crashed: {e}")
            print()
    
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All basic model tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
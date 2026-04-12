#!/usr/bin/env python3
"""
Simple test to validate NATS approval workflow infrastructure.

This test verifies that the notifications package imports correctly
and that the basic models can be instantiated without requiring
full database or NATS configuration.
"""

import sys
import os
import uuid
from datetime import datetime

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_notifications_imports():
    """Test that notifications package imports work correctly."""
    print("🔄 Testing notifications package imports...")
    
    try:
        from notifications.models import (
            ApprovalType,
            ApprovalPriority, 
            ApprovalOutcome,
            EntityReference,
            ApprovalRequest,
            ApprovalResponse
        )
        print("✅ Models imported successfully")
        
        from notifications.exceptions import (
            NATSConnectionError,
            ApprovalTimeoutError,
            ApprovalRejectedError,
            InvalidApprovalPayloadError
        )
        print("✅ Exceptions imported successfully")
        
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_approval_models():
    """Test that approval models can be created and validated."""
    print("\n🔄 Testing approval model creation...")
    
    try:
        # Test EntityReference
        entity = EntityReference(
            site_id=1,
            entity_type="post",
            entity_id=123
        )
        print("✅ EntityReference created successfully")
        
        # Test ApprovalRequest
        request = ApprovalRequest(
            approval_type=ApprovalType.CONTENT,
            priority=ApprovalPriority.MEDIUM,
            action="create_post",
            description="Create a new blog post about SEO automation",
            entity=entity,
            details={"word_count": 1500, "target_keywords": ["seo", "automation"]},
            risks=["potential duplicate content"],
            requested_by="content_generation_agent",
            timeout_seconds=300
        )
        print("✅ ApprovalRequest created successfully")
        print(f"   - Approval ID: {request.approval_id}")
        print(f"   - Action: {request.action}")
        print(f"   - Type: {request.approval_type.value}")
        
        # Test ApprovalResponse
        response = ApprovalResponse(
            approval_id=request.approval_id,
            outcome=ApprovalOutcome.APPROVED,
            reason="Content looks good, approved for publishing",
            reviewed_by="human_reviewer",
            reviewed_at=datetime.utcnow()
        )
        print("✅ ApprovalResponse created successfully")
        print(f"   - Outcome: {response.outcome.value}")
        print(f"   - Reviewed by: {response.reviewed_by}")
        
        return True
    except Exception as e:
        print(f"❌ Model creation error: {e}")
        return False

def test_model_validation():
    """Test model validation rules."""
    print("\n🔄 Testing model validation...")
    
    try:
        # Test invalid EntityReference
        try:
            EntityReference(site_id=1, entity_type="", entity_id=123)
            print("❌ Should have failed on empty entity_type")
            return False
        except Exception:
            print("✅ Empty entity_type validation works")
        
        # Test invalid ApprovalRequest
        try:
            ApprovalRequest(
                approval_type=ApprovalType.CONTENT,
                action="",  # Empty action should fail
                description="Test",
                entity=EntityReference(site_id=1, entity_type="post"),
                requested_by="test"
            )
            print("❌ Should have failed on empty action")
            return False
        except Exception:
            print("✅ Empty action validation works")
        
        # Test minimum timeout
        try:
            ApprovalRequest(
                approval_type=ApprovalType.CONTENT,
                action="test_action",
                description="Test description that is long enough",
                entity=EntityReference(site_id=1, entity_type="post"),
                requested_by="test_agent",
                timeout_seconds=10  # Too short, should fail
            )
            print("❌ Should have failed on timeout too short")
            return False
        except Exception:
            print("✅ Minimum timeout validation works")
        
        return True
    except Exception as e:
        print(f"❌ Validation test error: {e}")
        return False

def test_json_serialization():
    """Test that models can be serialized to JSON."""
    print("\n🔄 Testing JSON serialization...")
    
    try:
        entity = EntityReference(site_id=1, entity_type="post", entity_id=123)
        request = ApprovalRequest(
            approval_type=ApprovalType.CONTENT,
            action="create_post",
            description="Create a new blog post about SEO automation",
            entity=entity,
            requested_by="content_agent"
        )
        
        # Test serialization
        request_dict = request.model_dump(mode='json')
        print("✅ ApprovalRequest serialized to dict")
        
        # Test deserialization
        request_restored = ApprovalRequest.model_validate(request_dict)
        print("✅ ApprovalRequest restored from dict")
        
        # Verify data integrity
        assert request.approval_id == request_restored.approval_id
        assert request.action == request_restored.action
        assert request.entity.site_id == request_restored.entity.site_id
        print("✅ Data integrity verified")
        
        return True
    except Exception as e:
        print(f"❌ Serialization test error: {e}")
        return False

def main():
    """Run all tests."""
    print("NATS Approval Workflow Infrastructure - Basic Tests")
    print("=" * 60)
    
    tests = [
        test_notifications_imports,
        test_approval_models,
        test_model_validation,
        test_json_serialization
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} failed with exception: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! NATS approval workflow infrastructure is working.")
    else:
        print("❌ Some tests failed. Please check the implementation.")
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
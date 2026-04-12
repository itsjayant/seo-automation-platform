#!/usr/bin/env python3
"""
Minimal test for notifications package without full config dependencies.
"""

import sys
import os
from datetime import datetime

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_models_only():
    """Test just the models without any config dependencies."""
    print("🔄 Testing notifications models only...")
    
    try:
        # Import models directly
        from notifications.models import (
            ApprovalType,
            ApprovalPriority, 
            ApprovalOutcome,
            EntityReference,
            ApprovalRequest,
            ApprovalResponse
        )
        print("✅ Models imported successfully")
        
        # Test basic model creation
        entity = EntityReference(
            site_id=1,
            entity_type="post",
            entity_id=123
        )
        print("✅ EntityReference created")
        
        request = ApprovalRequest(
            approval_type=ApprovalType.CONTENT,
            action="create_post", 
            description="Test approval request for content creation",
            entity=entity,
            requested_by="test_agent"
        )
        print(f"✅ ApprovalRequest created with ID: {request.approval_id}")
        
        response = ApprovalResponse(
            approval_id=request.approval_id,
            outcome=ApprovalOutcome.APPROVED,
            reviewed_by="test_reviewer"
        )
        print(f"✅ ApprovalResponse created with outcome: {response.outcome.value}")
        
        # Test serialization
        request_dict = request.model_dump(mode='json')
        request_restored = ApprovalRequest.model_validate(request_dict)
        
        assert request.approval_id == request_restored.approval_id
        assert request.action == request_restored.action
        print("✅ Serialization and validation working")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_exceptions():
    """Test exception classes."""
    print("\n🔄 Testing exceptions...")
    
    try:
        from notifications.exceptions import (
            NATSConnectionError,
            ApprovalTimeoutError,
            ApprovalRejectedError
        )
        
        # Test exception creation
        error1 = NATSConnectionError("Test connection error")
        error2 = ApprovalTimeoutError("test-123", 300)
        error3 = ApprovalRejectedError("test-456", "reviewer", "Not good enough")
        
        print("✅ Exception classes work correctly")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("NATS Approval Workflow - Minimal Model Tests")
    print("=" * 50)
    
    success = True
    success &= test_models_only()
    success &= test_exceptions()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Minimal tests passed! Core models are working.")
    else:
        print("❌ Tests failed.")
    
    sys.exit(0 if success else 1)
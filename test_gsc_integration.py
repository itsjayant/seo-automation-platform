#!/usr/bin/env python3
"""
Unit tests for GSC integration components.

Tests GSC client, authentication, data transformation, and sync logic
with mock responses and error handling scenarios.
"""

import asyncio
import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4, UUID

import pytest
import httpx
import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from integrations.gsc import (
    GSCClient, GSCAuth, GSCSync, GSCTransformer,
    GSCConfig, GSCDimension, GSCMetricData, GSCSearchAnalyticsRequest,
    ServiceAccountConfig, GSCSyncConfig
)
from integrations.gsc.client import GSCAPIError, GSCQuotaExceededError
from integrations.gsc.auth import ServiceAccountAuthError
from integrations.gsc.transformers import GSCTransformationError
from integrations.gsc.sync import GSCSyncError


logger = structlog.get_logger(__name__)


class TestGSCAuth:
    """Test GSC service account authentication."""
    
    @pytest.fixture
    def mock_service_account_info(self):
        """Mock service account credentials."""
        return {
            "client_email": "test@test-project.iam.gserviceaccount.com",
            "client_id": "123456789",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC5...\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
            "project_id": "test-project"
        }
    
    @pytest.fixture
    def auth_config(self):
        """GSC authentication configuration."""
        return ServiceAccountConfig(
            service_account_info={
                "client_email": "test@test-project.iam.gserviceaccount.com",
                "client_id": "123456789", 
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEAuW...\n-----END RSA PRIVATE KEY-----\n",
                "token_uri": "https://oauth2.googleapis.com/token",
                "project_id": "test-project"
            }
        )
    
    def test_service_account_config_validation(self):
        """Test service account configuration validation."""
        # Valid config
        config = ServiceAccountConfig(
            service_account_info={
                "client_email": "test@example.com",
                "client_id": "123",
                "private_key": "key",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        )
        assert config.scopes == ["https://www.googleapis.com/auth/webmasters.readonly"]
        
        # Missing both path and info should be handled by validator
        with pytest.raises(ValueError, match="Either service_account_path or service_account_info must be provided"):
            ServiceAccountConfig()
    
    @patch('integrations.gsc.auth.json.load')
    @patch('builtins.open')
    @patch.object(Path, 'exists', return_value=True)
    def test_load_service_account_from_file(self, mock_exists, mock_open, mock_json_load, mock_service_account_info):
        """Test loading service account from file."""
        mock_json_load.return_value = mock_service_account_info
        
        config = ServiceAccountConfig(service_account_path="/path/to/service-account.json")
        auth = GSCAuth(config)
        
        assert auth._service_account_info == mock_service_account_info
        mock_open.assert_called_once_with(Path("/path/to/service-account.json"), 'r')
    
    def test_load_service_account_from_dict(self, mock_service_account_info):
        """Test loading service account from dictionary."""
        config = ServiceAccountConfig(service_account_info=mock_service_account_info)
        auth = GSCAuth(config)
        
        assert auth._service_account_info == mock_service_account_info
    
    def test_load_service_account_missing_fields(self):
        """Test service account validation with missing required fields."""
        incomplete_info = {
            "client_email": "test@example.com"
            # Missing private_key, token_uri, client_id
        }
        
        config = ServiceAccountConfig(service_account_info=incomplete_info)
        
        with pytest.raises(ServiceAccountAuthError, match="Missing required fields"):
            GSCAuth(config)


class TestGSCClient:
    """Test GSC API client functionality."""
    
    @pytest.fixture
    def gsc_config(self):
        """GSC client configuration."""
        return GSCConfig(
            service_account=ServiceAccountConfig(
                service_account_info={
                    "client_email": "test@test-project.iam.gserviceaccount.com",
                    "client_id": "123456789",
                    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEAuW...\n-----END RSA PRIVATE KEY-----\n",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "project_id": "test-project"
                }
            ),
            property_url="https://example.com"
        )
    
    @pytest.fixture
    def mock_gsc_client(self, gsc_config):
        """Mock GSC client with configuration."""
        with patch('integrations.gsc.client.GSCAuth') as mock_auth:
            mock_auth.return_value.get_auth_headers = AsyncMock(
                return_value={"Authorization": "Bearer test-token"}
            )
            
            with patch('integrations.gsc.client.HttpClient') as mock_http:
                mock_http_instance = AsyncMock()
                mock_http.return_value = mock_http_instance
                
                client = GSCClient(gsc_config)
                client._http_client = mock_http_instance
                
                return client, mock_http_instance
    
    @pytest.mark.asyncio
    async def test_verify_property_access_success(self, mock_gsc_client):
        """Test successful property access verification."""
        client, mock_http = mock_gsc_client
        
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "siteUrl": "https://example.com",
            "permissionLevel": "siteOwner"
        }
        
        mock_http.request = AsyncMock(return_value=mock_response)
        
        result = await client.verify_property_access("https://example.com")
        
        assert result is True
        mock_http.request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_verify_property_access_failure(self, mock_gsc_client):
        """Test property access verification failure."""
        client, mock_http = mock_gsc_client
        
        # Mock 404 response (no access)
        mock_response = Mock()
        mock_response.status_code = 404
        
        mock_http.request = AsyncMock(return_value=mock_response)
        
        result = await client.verify_property_access("https://example.com")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_fetch_search_analytics_success(self, mock_gsc_client):
        """Test successful search analytics data fetching."""
        client, mock_http = mock_gsc_client
        
        # Mock GSC API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "rows": [
                {
                    "keys": ["https://example.com/page1", "test query"],
                    "clicks": 100,
                    "impressions": 1000,
                    "ctr": 0.1,
                    "position": 5.5
                },
                {
                    "keys": ["https://example.com/page2", "another query"],
                    "clicks": 50,
                    "impressions": 500,
                    "ctr": 0.1,
                    "position": 8.2
                }
            ]
        }
        
        mock_http.request = AsyncMock(return_value=mock_response)
        
        site_id = uuid4()
        start_date = date.today() - timedelta(days=7)
        end_date = date.today() - timedelta(days=3)
        
        # Collect all yielded results
        results = []
        async for metric_data in client.fetch_search_analytics(
            site_id=site_id,
            site_url="https://example.com",
            start_date=start_date,
            end_date=end_date
        ):
            results.append(metric_data)
        
        assert len(results) == 2
        assert results[0].clicks == 100
        assert results[0].impressions == 1000
        assert results[1].clicks == 50
    
    @pytest.mark.asyncio
    async def test_quota_exceeded_error(self, mock_gsc_client):
        """Test handling of quota exceeded errors."""
        client, mock_http = mock_gsc_client
        
        # Mock 429 response (quota exceeded)
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "3600"}
        
        mock_http.request = AsyncMock(return_value=mock_response)
        
        with pytest.raises(GSCQuotaExceededError, match="quota exceeded"):
            await client.verify_property_access("https://example.com")


class TestGSCTransformer:
    """Test GSC data transformation functionality."""
    
    @pytest.fixture
    def transformer(self):
        """GSC data transformer."""
        return GSCTransformer(validate_data=True)
    
    @pytest.fixture
    def sample_metric_data(self):
        """Sample GSC metric data."""
        return GSCMetricData(
            clicks=100,
            impressions=1000,
            ctr=Decimal('0.1000'),
            position=Decimal('5.50')
        )
    
    def test_transform_to_gsc_metric_success(self, transformer, sample_metric_data):
        """Test successful metric data transformation."""
        site_id = uuid4()
        test_date = date.today() - timedelta(days=3)
        
        gsc_metric = transformer.transform_to_gsc_metric(
            metric_data=sample_metric_data,
            site_id=site_id,
            date=test_date,
            url="https://example.com/page",
            query="test query",
            country="US",
            device="desktop"
        )
        
        assert gsc_metric.site_id == site_id
        assert gsc_metric.date == test_date
        assert gsc_metric.url == "https://example.com/page"
        assert gsc_metric.query == "test query"
        assert gsc_metric.country == "US"
        assert gsc_metric.device == "desktop"
        assert gsc_metric.clicks == 100
        assert gsc_metric.impressions == 1000
        assert gsc_metric.ctr == Decimal('0.1000')
        assert gsc_metric.position == Decimal('5.50')
    
    def test_data_cleaning_negative_values(self, transformer):
        """Test data cleaning for negative values."""
        bad_data = GSCMetricData(
            clicks=-5,  # Invalid
            impressions=-10,  # Invalid
            ctr=Decimal('-0.1'),  # Invalid
            position=Decimal('-2.0')  # Invalid
        )
        
        site_id = uuid4()
        test_date = date.today() - timedelta(days=3)
        
        gsc_metric = transformer.transform_to_gsc_metric(
            metric_data=bad_data,
            site_id=site_id,
            date=test_date,
            url="https://example.com/page"
        )
        
        # Should be cleaned to valid values
        assert gsc_metric.clicks == 0
        assert gsc_metric.impressions == 0  
        assert gsc_metric.ctr == Decimal('0')
        assert gsc_metric.position == Decimal('0')
    
    def test_data_cleaning_ctr_too_high(self, transformer):
        """Test data cleaning for CTR > 1."""
        bad_data = GSCMetricData(
            clicks=1500,
            impressions=1000,
            ctr=Decimal('1.5'),  # Invalid (> 1.0)
            position=Decimal('3.0')
        )
        
        site_id = uuid4()
        test_date = date.today() - timedelta(days=3)
        
        gsc_metric = transformer.transform_to_gsc_metric(
            metric_data=bad_data,
            site_id=site_id,
            date=test_date,
            url="https://example.com/page"
        )
        
        # CTR should be capped at 1.0
        assert gsc_metric.ctr == Decimal('1')
    
    def test_url_cleaning_too_long(self, transformer, sample_metric_data):
        """Test URL cleaning for overly long URLs."""
        long_url = "https://example.com/" + "x" * 500  # > 500 chars
        
        gsc_metric = transformer.transform_to_gsc_metric(
            metric_data=sample_metric_data,
            site_id=uuid4(),
            date=date.today() - timedelta(days=3),
            url=long_url
        )
        
        # Should be truncated to 500 chars
        assert len(gsc_metric.url) == 500
        assert gsc_metric.url.startswith("https://example.com/")
    
    def test_country_code_validation(self, transformer, sample_metric_data):
        """Test country code validation and cleaning."""
        site_id = uuid4()
        test_date = date.today() - timedelta(days=3)
        
        # Valid country code
        gsc_metric = transformer.transform_to_gsc_metric(
            metric_data=sample_metric_data,
            site_id=site_id,
            date=test_date,
            url="https://example.com/page",
            country="us"  # Should be normalized to uppercase
        )
        assert gsc_metric.country == "US"
        
        # Invalid country code
        gsc_metric = transformer.transform_to_gsc_metric(
            metric_data=sample_metric_data,
            site_id=site_id,
            date=test_date,
            url="https://example.com/page",
            country="USA"  # Invalid (too long)
        )
        assert gsc_metric.country is None
    
    def test_device_normalization(self, transformer, sample_metric_data):
        """Test device type normalization."""
        site_id = uuid4()
        test_date = date.today() - timedelta(days=3)
        
        test_cases = [
            ("DESKTOP", "desktop"),
            ("mobile", "mobile"),
            ("TABLET", "tablet"),
            ("unknown_device", "unknown_dev")  # Truncated and lowercased
        ]
        
        for input_device, expected_device in test_cases:
            gsc_metric = transformer.transform_to_gsc_metric(
                metric_data=sample_metric_data,
                site_id=site_id,
                date=test_date,
                url="https://example.com/page",
                device=input_device
            )
            assert gsc_metric.device == expected_device


class TestGSCDimension:
    """Test GSC dimension enums and validation."""
    
    def test_dimension_values(self):
        """Test GSC dimension enum values."""
        assert GSCDimension.PAGE.value == "page"
        assert GSCDimension.QUERY.value == "query"
        assert GSCDimension.COUNTRY.value == "country"
        assert GSCDimension.DEVICE.value == "device"
        assert GSCDimension.DATE.value == "date"
    
    def test_search_analytics_request_validation(self):
        """Test GSC search analytics request validation."""
        start_date = date.today() - timedelta(days=7)
        end_date = date.today() - timedelta(days=3)
        
        # Valid request
        request = GSCSearchAnalyticsRequest(
            start_date=start_date,
            end_date=end_date,
            dimensions=[GSCDimension.PAGE, GSCDimension.QUERY]
        )
        
        assert request.start_date == start_date
        assert request.end_date == end_date
        assert len(request.dimensions) == 2
        
        # Invalid date range
        with pytest.raises(ValueError, match="end_date must be >= start_date"):
            GSCSearchAnalyticsRequest(
                start_date=end_date,
                end_date=start_date  # Invalid: end before start
            )


def test_gsc_config_validation():
    """Test GSC configuration validation."""
    # Valid config
    config = GSCConfig(
        service_account=ServiceAccountConfig(
            service_account_info={
                "client_email": "test@example.com",
                "client_id": "123",
                "private_key": "key",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        ),
        property_url="https://example.com"
    )
    
    assert config.property_url == "https://example.com"
    assert config.requests_per_day == 200
    
    # Invalid property URL
    with pytest.raises(ValueError, match="property_url must start with http"):
        GSCConfig(
            service_account=ServiceAccountConfig(
                service_account_info={
                    "client_email": "test@example.com",
                    "client_id": "123",
                    "private_key": "key", 
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            ),
            property_url="example.com"  # Missing protocol
        )


async def run_tests():
    """Run all GSC integration tests."""
    logger.info("Starting GSC integration tests")
    
    # This is a simple test runner - in practice you'd use pytest
    test_classes = [
        TestGSCAuth(),
        TestGSCClient(), 
        TestGSCTransformer(),
        TestGSCDimension()
    ]
    
    total_tests = 0
    passed_tests = 0
    
    for test_class in test_classes:
        class_name = test_class.__class__.__name__
        logger.info(f"Running tests for {class_name}")
        
        # Get all test methods
        test_methods = [method for method in dir(test_class) 
                       if method.startswith('test_')]
        
        for method_name in test_methods:
            total_tests += 1
            try:
                test_method = getattr(test_class, method_name)
                
                # Handle async tests
                if asyncio.iscoroutinefunction(test_method):
                    await test_method()
                else:
                    test_method()
                
                passed_tests += 1
                logger.debug(f"✓ {class_name}.{method_name}")
                
            except Exception as e:
                logger.error(f"✗ {class_name}.{method_name}: {e}")
    
    logger.info(f"GSC tests completed: {passed_tests}/{total_tests} passed")
    return passed_tests == total_tests


if __name__ == "__main__":
    # Run tests
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
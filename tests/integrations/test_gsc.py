"""
Integration tests for Google Search Console (GSC) API integration.

Tests GSC client functionality with mocked API responses,
authentication, error handling, and data processing.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import HTTPStatusError, Response, Request

from integrations.gsc.client import GSCClient
from integrations.gsc.models import (
    GSCDimension, GSCDevice, GSCSearchType, 
    SearchAnalyticsRequest, SearchAnalyticsResponse,
    GSCFilterOperator
)
from integrations.utils.rate_limiter import RateLimitExceeded


@pytest.mark.integration
@pytest.mark.gsc
class TestGSCClient:
    """Test cases for GSC API client."""
    
    @pytest.fixture
    async def gsc_client(self):
        """Create GSC client with mock credentials."""
        client = GSCClient(
            credentials_file="mock_credentials.json",
            property_url="sc-domain:example.com"
        )
        # Mock authentication
        client._authenticated = True
        return client
    
    async def test_gsc_client_initialization(self, gsc_client):
        """Test GSC client initialization."""
        assert gsc_client.property_url == "sc-domain:example.com"
        assert gsc_client._authenticated is True
    
    async def test_search_analytics_request(self, gsc_client, httpx_mock, gsc_mock_responses):
        """Test search analytics API request with mocked response."""
        # Mock the GSC search analytics API endpoint
        httpx_mock.add_response(
            method="POST",
            url="https://searchconsole.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com/searchAnalytics/query",
            json=gsc_mock_responses["search_analytics"],
            status_code=200
        )
        
        # Create search request
        request = SearchAnalyticsRequest(
            start_date=date(2024, 4, 1),
            end_date=date(2024, 4, 30),
            dimensions=[GSCDimension.QUERY],
            row_limit=25000
        )
        
        # Execute request
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["search_analytics"]
            
            response = await gsc_client.get_search_analytics(request)
            
            assert response is not None
            assert len(response.rows) == 3
            assert response.rows[0].keys[0] == "seo best practices"
            assert response.rows[0].clicks == 150.0
            assert response.rows[0].impressions == 2500.0
    
    async def test_search_analytics_with_dimensions(self, gsc_client, gsc_mock_responses):
        """Test search analytics with multiple dimensions."""
        # Mock response with dimensions
        mock_response = gsc_mock_responses["search_analytics_with_dimensions"]
        
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = mock_response
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 1),
                dimensions=[GSCDimension.QUERY, GSCDimension.DATE, GSCDimension.DEVICE],
                row_limit=1000
            )
            
            response = await gsc_client.get_search_analytics(request)
            
            assert len(response.rows) == 2
            
            # First row: desktop
            desktop_row = response.rows[0]
            assert desktop_row.keys[0] == "seo best practices"  # query
            assert desktop_row.keys[1] == "2024-04-01"  # date
            assert desktop_row.keys[2] == "DESKTOP"  # device
            assert desktop_row.clicks == 100.0
            
            # Second row: mobile
            mobile_row = response.rows[1] 
            assert mobile_row.keys[2] == "MOBILE"
            assert mobile_row.clicks == 50.0
    
    async def test_search_analytics_with_filters(self, gsc_client, gsc_mock_responses):
        """Test search analytics with dimension filters.""" 
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["search_analytics"]
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 30),
                dimensions=[GSCDimension.QUERY, GSCDimension.PAGE],
                dimension_filters=[
                    {
                        "dimension": GSCDimension.DEVICE.value,
                        "operator": GSCFilterOperator.EQUALS.value,
                        "expression": "DESKTOP"
                    },
                    {
                        "dimension": GSCDimension.COUNTRY.value,
                        "operator": GSCFilterOperator.EQUALS.value,  
                        "expression": "USA"
                    }
                ],
                row_limit=1000
            )
            
            response = await gsc_client.get_search_analytics(request)
            
            # Verify request was made with filters
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            request_data = call_args[1]["json"]
            
            assert "dimensionFilterGroups" in request_data
            assert len(request_data["dimensionFilterGroups"][0]["filters"]) == 2


@pytest.mark.integration
@pytest.mark.gsc
class TestGSCAuthentication:
    """Test cases for GSC authentication."""
    
    async def test_authentication_flow(self):
        """Test GSC OAuth authentication flow."""
        client = GSCClient(
            credentials_file="mock_credentials.json",
            property_url="sc-domain:example.com"
        )
        
        # Mock successful authentication
        with patch.object(client, '_authenticate') as mock_auth:
            mock_auth.return_value = True
            
            success = await client.authenticate()
            assert success is True
            assert client._authenticated is True
    
    async def test_authentication_failure(self):
        """Test GSC authentication failure handling."""
        client = GSCClient(
            credentials_file="invalid_credentials.json",
            property_url="sc-domain:example.com"
        )
        
        # Mock authentication failure
        with patch.object(client, '_authenticate', side_effect=Exception("Invalid credentials")):
            with pytest.raises(Exception, match="Invalid credentials"):
                await client.authenticate()
    
    async def test_token_refresh(self, gsc_client):
        """Test OAuth token refresh mechanism.""" 
        # Mock expired token scenario
        with patch.object(gsc_client, '_token_expired', return_value=True):
            with patch.object(gsc_client, '_refresh_token') as mock_refresh:
                mock_refresh.return_value = True
                
                # Should trigger token refresh
                await gsc_client._ensure_authenticated()
                mock_refresh.assert_called_once()


@pytest.mark.integration
@pytest.mark.gsc
class TestGSCErrorHandling:
    """Test cases for GSC API error handling."""
    
    async def test_rate_limit_handling(self, gsc_client, api_error_responses):
        """Test GSC rate limit error handling."""
        # Mock rate limit response
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.side_effect = HTTPStatusError(
                message="Rate limit exceeded",
                request=Request("POST", "https://test.com"),
                response=Response(429, json=api_error_responses["rate_limit"])
            )
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 30),
                dimensions=[GSCDimension.QUERY]
            )
            
            with pytest.raises(RateLimitExceeded):
                await gsc_client.get_search_analytics(request)
    
    async def test_authentication_error_handling(self, gsc_client, api_error_responses):
        """Test GSC authentication error handling."""
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.side_effect = HTTPStatusError(
                message="Unauthorized",
                request=Request("POST", "https://test.com"),
                response=Response(401, json=api_error_responses["auth_error"])
            )
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 30),
                dimensions=[GSCDimension.QUERY]
            )
            
            with pytest.raises(HTTPStatusError):
                await gsc_client.get_search_analytics(request)
    
    async def test_server_error_handling(self, gsc_client, api_error_responses):
        """Test GSC server error handling."""
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.side_effect = HTTPStatusError(
                message="Internal Server Error",
                request=Request("POST", "https://test.com"),
                response=Response(500, json=api_error_responses["server_error"])
            )
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 30),
                dimensions=[GSCDimension.QUERY]
            )
            
            with pytest.raises(HTTPStatusError):
                await gsc_client.get_search_analytics(request)
    
    async def test_property_not_found_error(self, gsc_mock_responses):
        """Test GSC property not found error.""" 
        client = GSCClient(
            credentials_file="mock_credentials.json",
            property_url="sc-domain:nonexistent.com"
        )
        
        with patch.object(client, '_make_authenticated_request') as mock_request:
            mock_request.side_effect = HTTPStatusError(
                message="Property not found",
                request=Request("GET", "https://test.com"),
                response=Response(404, json=gsc_mock_responses["errors"]["not_found"])
            )
            
            with pytest.raises(HTTPStatusError):
                await client.list_sites()


@pytest.mark.integration  
@pytest.mark.gsc
class TestGSCDataProcessing:
    """Test cases for GSC data processing and transformation."""
    
    async def test_search_analytics_data_transformation(self, gsc_client, gsc_mock_responses):
        """Test transformation of GSC data to internal models."""
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["search_analytics"]
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 30),
                dimensions=[GSCDimension.QUERY]
            )
            
            response = await gsc_client.get_search_analytics(request)
            
            # Test data type conversion
            for row in response.rows:
                assert isinstance(row.clicks, float)
                assert isinstance(row.impressions, float)  
                assert isinstance(row.ctr, float)
                assert isinstance(row.position, float)
    
    async def test_search_analytics_aggregation(self, gsc_client, gsc_mock_responses):
        """Test GSC data aggregation calculations."""
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["search_analytics"]
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 30),
                dimensions=[GSCDimension.QUERY]
            )
            
            response = await gsc_client.get_search_analytics(request)
            
            # Calculate totals
            total_clicks = sum(row.clicks for row in response.rows)
            total_impressions = sum(row.impressions for row in response.rows)
            
            assert total_clicks == 315.0  # 150 + 75 + 90
            assert total_impressions == 5500.0  # 2500 + 1200 + 1800
            
            # Calculate average CTR
            avg_ctr = total_clicks / total_impressions
            assert abs(avg_ctr - 0.0573) < 0.001  # Approximately 5.73%
    
    async def test_date_range_validation(self, gsc_client):
        """Test GSC date range validation."""
        # Test future date rejection
        future_date = date(2025, 12, 31)
        
        request = SearchAnalyticsRequest(
            start_date=future_date,
            end_date=future_date,
            dimensions=[GSCDimension.QUERY] 
        )
        
        # In a real implementation, this should raise a validation error
        with patch.object(gsc_client, '_validate_date_range') as mock_validate:
            mock_validate.side_effect = ValueError("Future dates not allowed")
            
            with pytest.raises(ValueError, match="Future dates not allowed"):
                await gsc_client.get_search_analytics(request)
    
    async def test_dimension_validation(self, gsc_client):
        """Test GSC dimension validation."""
        # Test invalid dimension combination (if any restrictions exist)
        request = SearchAnalyticsRequest(
            start_date=date(2024, 4, 1),
            end_date=date(2024, 4, 30),
            dimensions=[GSCDimension.QUERY, GSCDimension.PAGE, GSCDimension.COUNTRY, GSCDimension.DEVICE]
        )
        
        # Mock validation - GSC allows up to 3 dimensions in some endpoints
        with patch.object(gsc_client, '_validate_dimensions') as mock_validate:
            if len(request.dimensions) > 3:
                mock_validate.side_effect = ValueError("Too many dimensions")
                
                with pytest.raises(ValueError, match="Too many dimensions"):
                    await gsc_client.get_search_analytics(request)


@pytest.mark.integration
@pytest.mark.gsc
class TestGSCSiteManagement:
    """Test cases for GSC site management operations."""
    
    async def test_list_sites(self, gsc_client, gsc_mock_responses):
        """Test listing GSC sites."""
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["sites"]
            
            sites = await gsc_client.list_sites()
            
            assert len(sites) == 2
            assert sites[0]["siteUrl"] == "sc-domain:example.com"
            assert sites[0]["permissionLevel"] == "siteOwner"
            assert sites[1]["siteUrl"] == "https://blog.example.com/"
            assert sites[1]["permissionLevel"] == "siteFullUser"
    
    async def test_verify_site_ownership(self, gsc_client, gsc_mock_responses):
        """Test site ownership verification."""
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["site_verification"]
            
            verification = await gsc_client.verify_site_ownership("sc-domain:example.com")
            
            assert verification["id"] == "sc-domain:example.com"
            assert verification["owners"][0]["verified"] is True
            assert verification["owners"][0]["permission"] == "siteOwner"


@pytest.mark.integration
@pytest.mark.gsc
@pytest.mark.slow
class TestGSCPerformance:
    """Test cases for GSC client performance and optimization."""
    
    async def test_batch_request_performance(self, gsc_client, gsc_mock_responses):
        """Test performance of batch GSC requests."""
        import time
        
        # Mock multiple requests
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["search_analytics"]
            
            start_time = time.time()
            
            # Simulate multiple concurrent requests
            requests = []
            for i in range(5):
                request = SearchAnalyticsRequest(
                    start_date=date(2024, 4, i+1),
                    end_date=date(2024, 4, i+1),
                    dimensions=[GSCDimension.QUERY]
                )
                requests.append(gsc_client.get_search_analytics(request))
            
            # Execute requests concurrently
            import asyncio
            results = await asyncio.gather(*requests)
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Verify all requests completed
            assert len(results) == 5
            
            # Performance check - should complete in reasonable time
            assert execution_time < 5.0  # Adjust threshold as needed
    
    async def test_request_caching(self, gsc_client, gsc_mock_responses):
        """Test GSC response caching functionality."""
        with patch.object(gsc_client, '_make_authenticated_request') as mock_request:
            mock_request.return_value = gsc_mock_responses["search_analytics"]
            
            request = SearchAnalyticsRequest(
                start_date=date(2024, 4, 1),
                end_date=date(2024, 4, 30),
                dimensions=[GSCDimension.QUERY]
            )
            
            # First request
            response1 = await gsc_client.get_search_analytics(request)
            
            # Second identical request (should use cache if implemented)
            response2 = await gsc_client.get_search_analytics(request)
            
            # Verify responses are identical
            assert len(response1.rows) == len(response2.rows)
            assert response1.rows[0].clicks == response2.rows[0].clicks
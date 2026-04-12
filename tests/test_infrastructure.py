"""
Basic validation tests to ensure test infrastructure is working.

These tests validate that the pytest foundation is correctly configured
and that all fixtures and mocking capabilities are functional.
"""

import pytest
import json
from uuid import uuid4
from pathlib import Path


@pytest.mark.unit
class TestTestInfrastructure:
    """Test the test infrastructure itself."""
    
    def test_pytest_markers_work(self):
        """Test that pytest markers are configured correctly."""
        # This test should run with the 'unit' marker
        assert True
    
    def test_uuid_generation(self):
        """Test UUID generation for test data."""
        test_id = uuid4()
        assert test_id is not None
        assert len(str(test_id)) == 36
    
    def test_mock_fixtures_load(self, gsc_mock_responses, ga4_mock_responses, serpapi_mock_responses):
        """Test that all mock fixture files load correctly."""
        # GSC fixtures
        assert "search_analytics" in gsc_mock_responses
        assert len(gsc_mock_responses["search_analytics"]["rows"]) > 0
        
        # GA4 fixtures  
        assert "reports" in ga4_mock_responses
        assert len(ga4_mock_responses["reports"]) > 0
        
        # SerpAPI fixtures
        assert "organic_search_results" in serpapi_mock_responses
        assert "search_metadata" in serpapi_mock_responses["organic_search_results"]
    
    def test_fixture_files_exist(self):
        """Test that all fixture files exist and are valid JSON."""
        fixture_dir = Path(__file__).parent / "fixtures"
        
        required_files = [
            "gsc_responses.json",
            "ga4_responses.json", 
            "serp_responses.json"
        ]
        
        for filename in required_files:
            file_path = fixture_dir / filename
            assert file_path.exists(), f"Fixture file {filename} does not exist"
            
            # Validate JSON structure
            with open(file_path) as f:
                data = json.load(f)
                assert isinstance(data, dict), f"Fixture file {filename} should contain a JSON object"
    
    def test_settings_override(self, test_settings):
        """Test that test settings override production settings."""
        assert test_settings["app"].environment == "testing"
        assert test_settings["app"].debug is True
        assert test_settings["database"].database == "seo_platform_test"
        assert test_settings["redis"].database == 15  # Test Redis DB
    
    async def test_async_test_support(self):
        """Test that async tests work correctly."""
        import asyncio
        
        # Simple async operation
        await asyncio.sleep(0.01)
        assert True
    
    def test_error_responses_fixture(self, api_error_responses):
        """Test API error response fixtures."""
        assert "rate_limit" in api_error_responses
        assert "server_error" in api_error_responses
        assert "auth_error" in api_error_responses
        
        # Validate error structure
        rate_limit_error = api_error_responses["rate_limit"]
        assert "error" in rate_limit_error
        assert rate_limit_error["error"]["code"] == 429


@pytest.mark.unit
@pytest.mark.database
class TestDatabaseFixtures:
    """Test database-related fixtures."""
    
    async def test_db_session_fixture(self, db_session):
        """Test that database session fixture works.""" 
        assert db_session is not None
        # Test session should be in a transaction
        assert hasattr(db_session, 'begin')
    
    async def test_populated_db_fixture(self, populated_db):
        """Test that populated database fixture works."""
        assert "site" in populated_db
        assert "keywords" in populated_db
        
        site = populated_db["site"]
        keywords = populated_db["keywords"]
        
        assert site.domain == "example.com"
        assert len(keywords) == 2
        assert keywords[0].site_id == site.id


@pytest.mark.unit
class TestMockingCapabilities:
    """Test HTTP mocking and async client fixtures."""
    
    async def test_httpx_mock_fixture(self, httpx_mock):
        """Test that HTTP mocking works."""
        # Mock a simple HTTP response
        httpx_mock.add_response(
            method="GET",
            url="https://api.example.com/test",
            json={"status": "success", "message": "Test response"},
            status_code=200
        )
        
        # Test that mock is properly configured
        assert httpx_mock is not None
    
    async def test_http_client_fixture(self, http_client):
        """Test that HTTP client fixture works."""
        assert http_client is not None
        # Async HTTP client should be available
        assert hasattr(http_client, 'get')
        assert hasattr(http_client, 'post')


@pytest.mark.unit
class TestUtilityFixtures:
    """Test utility fixtures and helpers."""
    
    def test_sample_uuid_fixture(self, sample_uuid):
        """Test sample UUID fixture."""
        assert sample_uuid is not None
        assert len(str(sample_uuid)) == 36
    
    def test_sample_date_fixture(self, sample_date):
        """Test sample date fixture."""
        from datetime import date
        assert isinstance(sample_date, date)
        assert sample_date.year == 2024
        assert sample_date.month == 4
        assert sample_date.day == 1
    
    def test_clean_env_fixture(self, clean_env):
        """Test clean environment fixture."""
        import os
        
        # Test environment variables should be set
        assert os.getenv("ENVIRONMENT") == "testing"
        assert os.getenv("DEBUG") == "true"
        assert os.getenv("LOG_LEVEL") == "DEBUG"


@pytest.mark.integration  
class TestServiceFixtures:
    """Test service connection fixtures (Redis, NATS)."""
    
    def test_redis_client_fixture(self, redis_client):
        """Test Redis client fixture."""
        assert redis_client is not None
        # Should be configured for test database
        assert hasattr(redis_client, 'ping')
    
    async def test_async_redis_client_fixture(self, async_redis_client):
        """Test async Redis client fixture."""
        assert async_redis_client is not None
        assert hasattr(async_redis_client, 'ping')
    
    async def test_nats_client_fixture(self, nats_client):
        """Test NATS client fixture (may be mocked)."""
        assert nats_client is not None
        # May be a mock if NATS is not available
        assert hasattr(nats_client, 'publish') or hasattr(nats_client, '_mock_name')


@pytest.mark.unit
class TestTestMarkers:
    """Test that test markers are working correctly."""
    
    @pytest.mark.slow
    def test_slow_marker(self):
        """Test that slow marker works.""" 
        import time
        # Simulate slow operation
        time.sleep(0.01)
        assert True
    
    @pytest.mark.api
    def test_api_marker(self):
        """Test that API marker works."""
        assert True
    
    @pytest.mark.rate_limit
    def test_rate_limit_marker(self):
        """Test that rate_limit marker works."""
        assert True
    
    @pytest.mark.retry  
    def test_retry_marker(self):
        """Test that retry marker works."""
        assert True
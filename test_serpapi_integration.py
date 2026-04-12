"""
SerpAPI Integration Tests

Test suite for SerpAPI integration functionality including models,
transformers, client behavior, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, date
from uuid import uuid4

from integrations.serp.models import (
    SearchParams, LocationTarget, DeviceType, SerpResult,
    OrganicResult, SerpFeatures, RankingData, QuotaInfo
)
from integrations.serp.transformers import (
    ResultTransformer, PositionExtractor, SerpFeatureDetector
)
from integrations.serp.client import (
    SerpAPIClient, SerpAPIError, SerpAPIQuotaError, SerpAPIAuthError
)
from integrations.serp.scheduler import (
    RankScheduler, TrackingJob, JobStatus, TrackingMode
)
from integrations.serp.cache import ResultCache, CachePolicy, CacheStrategy


class TestSerpAPIModels:
    """Test SerpAPI data models."""
    
    def test_location_target_validation(self):
        """Test LocationTarget validation."""
        # Valid country code
        location = LocationTarget(country="US")
        assert location.country == "US"
        
        # Invalid country code should be corrected
        location = LocationTarget(country="us")
        assert location.country == "US"
        
        # Invalid length should raise error
        with pytest.raises(ValueError, match="Country code must be 2 characters"):
            LocationTarget(country="USA")
    
    def test_search_params_conversion(self):
        """Test SearchParams to SerpAPI conversion."""
        params = SearchParams(
            query="python seo",
            location=LocationTarget(country="US"),
            device=DeviceType.MOBILE,
            num_results=50
        )
        
        api_params = params.to_serpapi_params()
        
        assert api_params["q"] == "python seo"
        assert api_params["engine"] == "google"
        assert api_params["device"] == "mobile"
        assert api_params["num"] == 50
    
    def test_organic_result_domain_extraction(self):
        """Test automatic domain extraction from URLs."""
        result = OrganicResult(
            position=1,
            title="Test Result",
            link="https://www.example.com/path/to/page",
            displayed_link="example.com"
        )
        
        assert result.domain == "example.com"
        assert result.path == "/path/to/page"
    
    def test_ranking_data_properties(self):
        """Test RankingData computed properties."""
        ranking = RankingData(
            site_id=uuid4(),
            keyword_id=uuid4(),
            keyword="test keyword",
            date=date.today(),
            location="US",
            device=DeviceType.DESKTOP,
            position=5
        )
        
        assert ranking.is_ranking is True
        assert ranking.is_top_10 is True
        assert ranking.is_page_one is True
        
        # Test not ranking
        ranking.position = None
        assert ranking.is_ranking is False
        assert ranking.is_top_10 is False
        assert ranking.is_page_one is False
        
        # Test position 15
        ranking.position = 15
        assert ranking.is_ranking is True
        assert ranking.is_top_10 is False
        assert ranking.is_page_one is False


class TestPositionExtractor:
    """Test position extraction utilities."""
    
    def test_domain_normalization(self):
        """Test domain normalization."""
        extractor = PositionExtractor()
        
        # Test various URL formats
        assert extractor.normalize_domain("https://www.example.com/path") == "example.com"
        assert extractor.normalize_domain("http://example.com") == "example.com"
        assert extractor.normalize_domain("www.example.com") == "example.com"
        assert extractor.normalize_domain("example.com") == "example.com"
        assert extractor.normalize_domain("EXAMPLE.COM") == "example.com"
    
    def test_find_domain_positions(self):
        """Test finding all positions for a domain."""
        organic_results = [
            OrganicResult(
                position=1, title="Test 1", link="https://example.com/page1",
                displayed_link="example.com"
            ),
            OrganicResult(
                position=3, title="Test 2", link="https://other.com/page",
                displayed_link="other.com"  
            ),
            OrganicResult(
                position=7, title="Test 3", link="https://www.example.com/page2",
                displayed_link="example.com"
            )
        ]
        
        extractor = PositionExtractor()
        positions = extractor.find_domain_positions(organic_results, "example.com")
        
        assert positions == [1, 7]  # Should find both positions
    
    def test_get_best_position(self):
        """Test getting best position for domain."""
        organic_results = [
            OrganicResult(
                position=5, title="Test", link="https://example.com/page1",
                displayed_link="example.com"
            ),
            OrganicResult(
                position=2, title="Test", link="https://example.com/page2", 
                displayed_link="example.com"
            )
        ]
        
        extractor = PositionExtractor()
        best_position = extractor.get_best_position(organic_results, "example.com")
        
        assert best_position == 2  # Should return the best (lowest) position


class TestSerpFeatureDetector:
    """Test SERP feature detection."""
    
    def test_feature_detection(self):
        """Test SERP feature detection from API response."""
        detector = SerpFeatureDetector()
        
        # Mock SerpAPI response with features
        response_data = {
            "answer_box": {"snippet": "Test featured snippet"},
            "related_questions": [
                {"question": "What is SEO?"},
                {"question": "How does SEO work?"}
            ],
            "images_results": [
                {"title": "Image 1", "link": "https://example.com/image1.jpg"}
            ],
            "local_results": [
                {"title": "Local Business", "address": "123 Main St"}
            ],
            "knowledge_graph": {
                "title": "SEO",
                "type": "Topic"
            }
        }
        
        features = detector.detect_features(response_data)
        
        assert features.featured_snippet is True
        assert features.people_also_ask is True
        assert features.image_pack is True
        assert features.local_pack is True
        assert features.knowledge_panel is True
        assert features.video_results is False  # Not in response
        assert features.shopping_results is False  # Not in response


class TestResultTransformer:
    """Test result transformation."""
    
    @pytest.fixture
    def transformer(self):
        return ResultTransformer()
    
    @pytest.fixture
    def sample_serpapi_response(self):
        return {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Python SEO Tools - GitHub",
                    "link": "https://github.com/python-seo/tools",
                    "displayed_link": "github.com",
                    "snippet": "Comprehensive Python tools for SEO automation"
                },
                {
                    "position": 2, 
                    "title": "SEO Python Tutorial",
                    "link": "https://example.com/python-seo-tutorial",
                    "displayed_link": "example.com",
                    "snippet": "Learn Python for SEO automation"
                }
            ],
            "search_information": {
                "total_results": 1450000,
                "time_taken_displayed": 0.34
            },
            "answer_box": {
                "snippet": "Python is a programming language..."
            },
            "related_questions": [
                {"question": "What is Python SEO?"}
            ]
        }
    
    @pytest.mark.asyncio
    async def test_transform_response(self, transformer, sample_serpapi_response):
        """Test transforming SerpAPI response to SerpResult."""
        search_params = SearchParams(
            query="python seo",
            location=LocationTarget(country="US"),
            device=DeviceType.DESKTOP
        )
        
        result = await transformer.transform_response(
            sample_serpapi_response, search_params, datetime.utcnow()
        )
        
        assert isinstance(result, SerpResult)
        assert len(result.organic_results) == 2
        assert result.total_results == 1450000
        assert result.time_taken == 0.34
        assert result.serp_features.featured_snippet is True
        assert result.serp_features.people_also_ask is True
    
    @pytest.mark.asyncio
    async def test_extract_ranking_data(self, transformer, sample_serpapi_response):
        """Test extracting ranking data for specific domain."""
        search_params = SearchParams(
            query="python seo",
            location=LocationTarget(country="US")
        )
        
        # First transform the response
        serp_result = await transformer.transform_response(
            sample_serpapi_response, search_params, datetime.utcnow()
        )
        
        # Extract ranking for github.com
        ranking_data = await transformer.extract_ranking_data(
            serp_result, "github.com", uuid4(), uuid4()
        )
        
        assert ranking_data.keyword == "python seo"
        assert ranking_data.position == 1
        assert ranking_data.is_ranking is True
        assert len(ranking_data.competitor_urls) > 0
        assert "https://example.com/python-seo-tutorial" in ranking_data.competitor_urls


class TestSerpAPIClient:
    """Test SerpAPI client functionality."""
    
    @pytest.fixture
    def mock_http_client(self):
        """Mock HTTP client for testing."""
        http_client = AsyncMock()
        
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Test Result",
                    "link": "https://example.com",
                    "displayed_link": "example.com", 
                    "snippet": "Test snippet"
                }
            ],
            "search_information": {
                "total_results": 1000000,
                "time_taken_displayed": 0.25
            }
        }
        
        http_client.request.return_value = mock_response
        return http_client
    
    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """Test client initialization and validation."""
        # Test with missing API key
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(SerpAPIAuthError, match="SERPAPI_KEY environment variable not set"):
                SerpAPIClient()
        
        # Test with valid API key
        with patch.dict('os.environ', {'SERPAPI_KEY': 'test_key'}):
            client = SerpAPIClient()
            assert client.api_key == "test_key"
    
    @pytest.mark.asyncio 
    async def test_quota_checking(self):
        """Test quota limit enforcement."""
        with patch.dict('os.environ', {'SERPAPI_KEY': 'test_key'}):
            client = SerpAPIClient(daily_quota_limit=2)
            
            # Simulate quota usage
            client._daily_credits_used = 2
            
            # Should raise quota error
            with pytest.raises(SerpAPIQuotaError):
                await client._check_quota_limits()
    
    @pytest.mark.asyncio
    async def test_search_with_cache(self):
        """Test search with caching enabled."""
        with patch.dict('os.environ', {'SERPAPI_KEY': 'test_key'}):
            client = SerpAPIClient()
            
            # Mock the HTTP request
            with patch.object(client, '_make_request') as mock_request:
                mock_request.return_value = {
                    "organic_results": [],
                    "search_information": {"total_results": 0}
                }
                
                search_params = SearchParams(
                    query="test",
                    location=LocationTarget(country="US")
                )
                
                result = await client.search(search_params, use_cache=True)
                
                assert isinstance(result, SerpResult)
                mock_request.assert_called_once()


class TestRankScheduler:
    """Test rank tracking scheduler."""
    
    @pytest.fixture
    def scheduler(self):
        return RankScheduler(daily_quota_budget=5)
    
    def test_scheduler_initialization(self, scheduler):
        """Test scheduler initialization."""
        assert scheduler.daily_quota_budget == 5
        assert scheduler.tracking_mode == TrackingMode.PRIORITY
        assert len(scheduler._pending_jobs) == 0
        assert len(scheduler._running_jobs) == 0
    
    def test_tracking_job_properties(self):
        """Test TrackingJob properties."""
        job = TrackingJob(
            site_id=uuid4(),
            keyword_ids=[uuid4(), uuid4(), uuid4()],
            scheduled_date=date.today()
        )
        
        assert job.estimated_credits == 3
        assert job.status == JobStatus.PENDING
    
    def test_quota_status(self, scheduler):
        """Test quota status reporting."""
        scheduler._daily_credits_used = 2
        
        status = scheduler.get_daily_quota_status()
        
        assert status['budget'] == 5
        assert status['used'] == 2
        assert status['remaining'] == 3
        assert status['usage_percentage'] == 40.0


class TestResultCache:
    """Test result caching functionality."""
    
    @pytest.fixture
    def cache_policy(self):
        return CachePolicy(
            default_ttl=3600,
            strategy=CacheStrategy.JSON
        )
    
    @pytest.fixture
    def cache(self, cache_policy):
        # Use in-memory mock for testing
        cache = ResultCache(policy=cache_policy)
        cache._redis = AsyncMock()
        cache._connected = True
        return cache
    
    def test_cache_key_generation(self, cache):
        """Test cache key generation."""
        key = cache.generate_key(
            "/search",
            {"q": "test query", "location": "US", "device": "desktop"}
        )
        
        assert key.startswith("serp_cache:search:")
        assert len(key) > 20  # Should include hash
    
    @pytest.mark.asyncio
    async def test_cache_operations(self, cache):
        """Test basic cache operations."""
        # Mock Redis operations
        cache._redis.get.return_value = None
        cache._redis.setex.return_value = True
        cache._redis.delete.return_value = 1
        
        test_data = {"test": "data"}
        
        # Test set
        success = await cache.set("test_key", test_data, ttl=300)
        assert success is True
        
        # Test delete
        deleted = await cache.delete("test_key")
        assert deleted is True
    
    def test_serialization(self, cache):
        """Test data serialization."""
        test_data = {"key": "value", "number": 42}
        
        # Test JSON serialization
        serialized = cache._serialize_data(test_data)
        assert isinstance(serialized, bytes)
        
        # Test deserialization
        deserialized = cache._deserialize_data(serialized)
        assert deserialized == test_data


@pytest.mark.asyncio
async def test_integration_workflow():
    """Test complete integration workflow."""
    with patch.dict('os.environ', {'SERPAPI_KEY': 'test_key'}):
        # Mock all external dependencies
        with patch('integrations.serp.client.HttpClient') as mock_http:
            mock_response = Mock()
            mock_response.json.return_value = {
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Test Result",
                        "link": "https://github.com/test",
                        "displayed_link": "github.com",
                        "snippet": "Test"
                    }
                ],
                "search_information": {"total_results": 1000}
            }
            
            mock_http_instance = AsyncMock()
            mock_http_instance.request.return_value = mock_response
            mock_http.return_value.__aenter__.return_value = mock_http_instance
            
            # Test the workflow
            client = SerpAPIClient()
            
            rankings = await client.track_keywords(
                keywords=["test keyword"],
                site_domain="github.com",
                location="US"
            )
            
            assert len(rankings) == 1
            assert rankings[0].keyword == "test keyword"
            assert rankings[0].position == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
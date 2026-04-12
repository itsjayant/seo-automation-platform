"""
SerpAPI Client for Rank Tracking

Production-grade SerpAPI client with comprehensive quota management,
rate limiting, circuit breaker protection, and optimized batch processing
for cost-effective rank tracking within tight API constraints.
"""

import os
import asyncio
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Union, AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urljoin

import structlog
from pydantic import ValidationError

from ..utils.http_client import HttpClient, HttpMethod, RetryConfig, TimeoutConfig
from ..utils.rate_limiter import RateLimiter, RateLimitConfig, RateLimitExceededError
from .models import (
    SerpResult, SearchParams, RankingData, QuotaInfo, 
    OrganicResult, SerpFeatures, DeviceType, LocationTarget
)
from .transformers import ResultTransformer
from .cache import ResultCache, CachePolicy

logger = structlog.get_logger(__name__)


class SerpAPIError(Exception):
    """Base SerpAPI integration error."""
    pass


class SerpAPIAuthError(SerpAPIError):
    """SerpAPI authentication error."""
    pass


class SerpAPIQuotaError(SerpAPIError):
    """SerpAPI quota exceeded error."""
    
    def __init__(self, message: str, used_credits: int, total_credits: int):
        super().__init__(message)
        self.used_credits = used_credits
        self.total_credits = total_credits


class SerpAPIRateLimitError(SerpAPIError):
    """SerpAPI rate limit exceeded."""
    
    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class SerpAPIClient:
    """
    SerpAPI client with comprehensive quota management and optimization.
    
    Features:
    - API key authentication with validation
    - Quota tracking and protection (micro plan: ~100 searches/month)
    - Rate limiting (5 requests/second max)
    - Response caching to minimize API calls  
    - Batch processing for efficiency
    - Circuit breaker for API reliability
    - Detailed error handling and recovery
    """
    
    BASE_URL = "https://serpapi.com"
    DEFAULT_ENGINE = "google"
    
    # Rate limits (SerpAPI: 5 requests/second max)
    RATE_LIMIT_CONFIG = RateLimitConfig(
        requests=5,
        window=1,  # 1 second
        key_prefix="serpapi",
        circuit_breaker_enabled=True,
        failure_threshold=3,
        recovery_timeout=30
    )
    
    # Conservative timeout for SerpAPI
    TIMEOUT_CONFIG = TimeoutConfig(
        connect=15.0,
        read=60.0,
        write=30.0,
        pool=30.0
    )
    
    # Retry configuration
    RETRY_CONFIG = RetryConfig(
        max_retries=3,
        backoff_factor=2.0,
        initial_delay=1.0,
        max_delay=30.0,
        retryable_status_codes=(429, 500, 502, 503, 504)
    )
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_policy: Optional[CachePolicy] = None,
        daily_quota_limit: int = 3,  # Conservative daily limit for micro plan
        enable_monitoring: bool = True
    ):
        """
        Initialize SerpAPI client.
        
        Args:
            api_key: SerpAPI key (defaults to SERPAPI_KEY env var)
            cache_policy: Response caching policy
            daily_quota_limit: Max searches per day (default: 3 for micro plan)
            enable_monitoring: Enable quota and performance monitoring
        """
        self.api_key = api_key or os.getenv("SERPAPI_KEY")
        if not self.api_key:
            raise SerpAPIAuthError("SERPAPI_KEY environment variable not set")
            
        self.daily_quota_limit = daily_quota_limit
        self.enable_monitoring = enable_monitoring
        
        # Initialize components
        self._http_client: Optional[HttpClient] = None
        self._cache = ResultCache(policy=cache_policy or CachePolicy())
        self._transformer = ResultTransformer()
        self._quota_info = QuotaInfo()
        
        # Session tracking
        self._session_usage = 0
        self._last_request_time: Optional[datetime] = None
        
        logger.info(
            "SerpAPI client initialized",
            daily_quota_limit=daily_quota_limit,
            cache_enabled=cache_policy is not None
        )
    
    @asynccontextmanager
    async def _get_http_client(self) -> AsyncIterator[HttpClient]:
        """Get or create HTTP client with proper resource management."""
        if self._http_client is None:
            # Create RateLimiter from config
            rate_limiter = RateLimiter(configs={"serpapi": self.RATE_LIMIT_CONFIG})
            
            # Create HttpClientConfig with proper structure
            from integrations.utils.http_client import HttpClientConfig
            client_config = HttpClientConfig(
                timeout=self.TIMEOUT_CONFIG,
                retry=self.RETRY_CONFIG
            )
            
            self._http_client = HttpClient(
                config=client_config,
                rate_limiter=rate_limiter
            )
        
        try:
            yield self._http_client
        finally:
            # Keep client alive for session reuse
            pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def close(self):
        """Clean up resources."""
        if self._http_client:
            await self._http_client.close()
            self._http_client = None
        await self._cache.close()
        logger.info("SerpAPI client closed")
    
    async def _check_quota_limits(self) -> None:
        """Check if we're within quota limits before making requests."""
        today = date.today()
        daily_usage = self._quota_info.daily_usage.get(today.isoformat(), 0)
        
        if daily_usage >= self.daily_quota_limit:
            raise SerpAPIQuotaError(
                f"Daily quota limit reached: {daily_usage}/{self.daily_quota_limit}",
                used_credits=daily_usage,
                total_credits=self.daily_quota_limit
            )
        
        # Check session limits (additional protection)
        if self._session_usage >= self.daily_quota_limit:
            raise SerpAPIQuotaError(
                f"Session quota limit reached: {self._session_usage}",
                used_credits=self._session_usage,
                total_credits=self.daily_quota_limit
            )
    
    async def _update_usage_tracking(self, credits_used: int = 1):
        """Update quota and usage tracking."""
        today = date.today().isoformat()
        current_usage = self._quota_info.daily_usage.get(today, 0)
        self._quota_info.daily_usage[today] = current_usage + credits_used
        self._quota_info.used_credits += credits_used
        self._session_usage += credits_used
        self._last_request_time = datetime.utcnow()
        
        if self.enable_monitoring:
            logger.info(
                "SerpAPI usage updated",
                daily_usage=self._quota_info.daily_usage[today],
                daily_limit=self.daily_quota_limit,
                session_usage=self._session_usage,
                credits_used=credits_used
            )
    
    async def _make_request(
        self, 
        endpoint: str, 
        params: Dict[str, any],
        use_cache: bool = True
    ) -> Dict[str, any]:
        """
        Make authenticated request to SerpAPI.
        
        Args:
            endpoint: API endpoint path
            params: Request parameters  
            use_cache: Whether to use response caching
            
        Returns:
            API response data
            
        Raises:
            SerpAPIError: For API errors
            SerpAPIQuotaError: When quota exceeded
        """
        # Add API key to parameters
        params = params.copy()
        params["api_key"] = self.api_key
        
        # Check cache first
        cache_key = None
        if use_cache:
            cache_key = self._cache.generate_key(endpoint, params)
            cached_response = await self._cache.get(cache_key)
            if cached_response:
                logger.debug("Using cached SerpAPI response", cache_key=cache_key)
                return cached_response
        
        # Check quota before making request
        await self._check_quota_limits()
        
        url = urljoin(self.BASE_URL, endpoint)
        
        try:
            async with self._get_http_client() as client:
                response = await client.request(
                    method=HttpMethod.GET,
                    url=url,
                    params=params
                )
            
            # Update usage tracking
            await self._update_usage_tracking(credits_used=1)
            
            # Parse response
            data = response.json()
            
            # Check for API errors
            if "error" in data:
                error_msg = data["error"]
                if "quota" in error_msg.lower() or "limit" in error_msg.lower():
                    raise SerpAPIQuotaError(error_msg, self._session_usage, self.daily_quota_limit)
                else:
                    raise SerpAPIError(f"SerpAPI error: {error_msg}")
            
            # Cache successful response
            if use_cache and cache_key:
                await self._cache.set(cache_key, data)
            
            return data
            
        except Exception as e:
            if isinstance(e, (SerpAPIError, SerpAPIQuotaError)):
                raise
            
            logger.error("SerpAPI request failed", error=str(e), endpoint=endpoint)
            raise SerpAPIError(f"Request failed: {str(e)}")
    
    async def search(
        self, 
        params: Union[SearchParams, Dict[str, any]],
        use_cache: bool = True
    ) -> SerpResult:
        """
        Perform a single search via SerpAPI.
        
        Args:
            params: Search parameters (SearchParams object or dict)
            use_cache: Whether to use response caching
            
        Returns:
            Parsed search result
            
        Raises:
            SerpAPIError: For API or parsing errors
            SerpAPIQuotaError: When quota exceeded
        """
        if isinstance(params, dict):
            params = SearchParams(**params)
        
        start_time = datetime.utcnow()
        
        try:
            # Convert to SerpAPI parameters
            api_params = params.to_serpapi_params()
            
            logger.info(
                "Starting SerpAPI search",
                query=params.query,
                location=params.location.country,
                device=params.device.value,
                num_results=params.num_results
            )
            
            # Make API request
            response_data = await self._make_request("/search", api_params, use_cache)
            
            # Transform response to our models
            serp_result = await self._transformer.transform_response(
                response_data, params, start_time
            )
            
            logger.info(
                "SerpAPI search completed",
                query=params.query,
                results_found=len(serp_result.organic_results),
                credits_used=serp_result.credits_used,
                response_time=serp_result.time_taken
            )
            
            return serp_result
            
        except Exception as e:
            logger.error(
                "SerpAPI search failed",
                query=params.query if hasattr(params, 'query') else 'unknown',
                error=str(e)
            )
            raise
    
    async def track_keywords(
        self,
        keywords: List[str],
        site_domain: str,
        location: Union[LocationTarget, str] = "US",
        device: DeviceType = DeviceType.DESKTOP,
        num_results: int = 100,
        use_cache: bool = True
    ) -> List[RankingData]:
        """
        Track rankings for multiple keywords efficiently.
        
        Args:
            keywords: List of keywords to track
            site_domain: Domain to track (e.g., 'example.com')
            location: Geographic location (LocationTarget or country code)
            device: Device type for search
            num_results: Number of results to analyze
            use_cache: Whether to use response caching
            
        Returns:
            List of ranking data for each keyword
            
        Raises:
            SerpAPIQuotaError: When quota would be exceeded
        """
        if isinstance(location, str):
            location = LocationTarget(country=location)
        
        # Check if we have quota for all keywords
        needed_credits = len(keywords)
        today = date.today()
        daily_usage = self._quota_info.daily_usage.get(today.isoformat(), 0)
        
        if daily_usage + needed_credits > self.daily_quota_limit:
            available_credits = self.daily_quota_limit - daily_usage
            raise SerpAPIQuotaError(
                f"Insufficient quota for {needed_credits} searches. "
                f"Available: {available_credits}, Daily limit: {self.daily_quota_limit}",
                used_credits=daily_usage,
                total_credits=self.daily_quota_limit
            )
        
        results = []
        
        for keyword in keywords:
            try:
                # Create search parameters
                search_params = SearchParams(
                    query=keyword,
                    location=location,
                    device=device,
                    num_results=num_results
                )
                
                # Perform search
                serp_result = await self.search(search_params, use_cache=use_cache)
                
                # Transform to ranking data
                ranking_data = await self._transformer.extract_ranking_data(
                    serp_result, site_domain
                )
                
                results.append(ranking_data)
                
                # Add delay between requests (rate limiting backup)
                if len(results) < len(keywords):  # Not the last request
                    await asyncio.sleep(0.5)  # 500ms delay between requests
                
            except Exception as e:
                logger.error(
                    "Failed to track keyword",
                    keyword=keyword,
                    domain=site_domain,
                    error=str(e)
                )
                # Continue with other keywords, but log the failure
                continue
        
        logger.info(
            "Keyword tracking completed",
            keywords_tracked=len(results),
            total_keywords=len(keywords),
            domain=site_domain,
            location=location.country,
            device=device.value
        )
        
        return results
    
    async def get_quota_info(self) -> QuotaInfo:
        """Get current quota usage information."""
        return self._quota_info.copy()
    
    async def validate_api_key(self) -> bool:
        """
        Validate API key with a minimal test request.
        
        Returns:
            True if API key is valid
            
        Raises:
            SerpAPIAuthError: If API key is invalid
        """
        try:
            test_params = SearchParams(
                query="test",
                location=LocationTarget(country="US"),
                num_results=10
            )
            
            api_params = test_params.to_serpapi_params()
            api_params["no_cache"] = True  # Don't cache test requests
            
            await self._make_request("/search", api_params, use_cache=False)
            
            logger.info("SerpAPI key validation successful")
            return True
            
        except SerpAPIError as e:
            if "invalid" in str(e).lower() or "unauthorized" in str(e).lower():
                raise SerpAPIAuthError(f"Invalid API key: {str(e)}")
            # Other errors might be temporary
            logger.warning("API key validation inconclusive", error=str(e))
            return False
    
    def get_search_cost_estimate(self, num_keywords: int) -> int:
        """
        Estimate API credits needed for keyword tracking.
        
        Args:
            num_keywords: Number of keywords to track
            
        Returns:
            Estimated credits needed
        """
        # Each keyword = 1 search = 1 credit
        return num_keywords
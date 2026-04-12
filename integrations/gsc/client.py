"""
Google Search Console API Client.

Main client for interacting with the Google Search Console API,
including search analytics data fetching, site verification,
and property management with rate limiting and error handling.
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional, AsyncGenerator
from uuid import UUID
from urllib.parse import urljoin, quote

import httpx
import structlog
from pydantic import ValidationError

from integrations.utils.http_client import HttpClient, HttpMethod, HttpClientError
from integrations.utils.rate_limiter import RateLimiter, RateLimitConfig, RateLimitExceededError
from integrations.utils.circuit_breaker import CircuitBreakerError

from .auth import GSCAuth, ServiceAccountAuthError
from .models import (
    GSCConfig, GSCDimension, GSCFilter, GSCSearchAnalyticsRequest,
    GSCSearchAnalyticsResponse, GSCRowData, GSCMetricData
)

logger = structlog.get_logger(__name__)


class GSCAPIError(Exception):
    """GSC API specific errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class GSCQuotaExceededError(GSCAPIError):
    """GSC API quota exceeded error."""
    pass


class GSCClient:
    """
    Google Search Console API client with rate limiting and error handling.
    
    Provides methods for fetching search analytics data, managing properties,
    and handling GSC API rate limits and authentication.
    """
    
    def __init__(
        self,
        config: GSCConfig,
        http_client: Optional[HttpClient] = None,
        rate_limiter: Optional[RateLimiter] = None
    ):
        self.config = config
        self._auth = GSCAuth(config.service_account)
        self._http_client = http_client or self._create_default_http_client()
        self._rate_limiter = rate_limiter or self._create_rate_limiter()
        
        # API endpoints
        self._base_url = config.base_url.rstrip('/')
        self._sites_url = f"{self._base_url}/sites"
    
    def _create_default_http_client(self) -> HttpClient:
        """Create default HTTP client with GSC-specific configuration."""
        from integrations.utils.http_client import HttpClientConfig, TimeoutConfig, RetryConfig
        
        # Create proper timeout configuration
        timeout_config = TimeoutConfig(
            connect=10.0,
            read=60.0,  # GSC can be slow
            write=30.0,
            pool=30.0
        )
        
        # Create proper retry configuration
        retry_config = RetryConfig(
            max_retries=3,
            initial_delay=2.0,
            backoff_factor=2.0,
            retryable_status_codes=(429, 500, 502, 503, 504)
        )
        
        client_config = HttpClientConfig(
            base_url=self.config.base_url,
            timeout=timeout_config,
            retry=retry_config,
            user_agent="SEO-Automation-Platform/1.0 GSC-Integration"
        )
        
        return HttpClient(config=client_config)
    
    def _create_rate_limiter(self) -> RateLimiter:
        """Create rate limiter for GSC API quotas."""
        # GSC free tier: 200 queries/day
        daily_config = RateLimitConfig(
            requests=self.config.requests_per_day,
            window=86400,  # 24 hours
            key_prefix="gsc_daily",
            circuit_breaker_enabled=True,
            failure_threshold=3,
            recovery_timeout=300  # 5 minutes
        )
        
        # Additional per-minute limiting for burst control
        minute_config = RateLimitConfig(
            requests=self.config.requests_per_minute,
            window=60,  # 1 minute
            key_prefix="gsc_minute"
        )
        
        configs = {
            "gsc_daily": daily_config,
            "gsc_minute": minute_config
        }
        
        return RateLimiter(configs=configs)
    
    async def _make_authenticated_request(
        self,
        method: HttpMethod,
        url: str,
        **kwargs
    ) -> httpx.Response:
        """
        Make authenticated request to GSC API with rate limiting.
        
        Args:
            method: HTTP method
            url: Request URL
            **kwargs: Additional request parameters
            
        Returns:
            HTTP response
            
        Raises:
            GSCAPIError: On API errors
            GSCQuotaExceededError: On quota exceeded
            RateLimitExceededError: On rate limit exceeded
        """
        # Apply rate limiting
        try:
            await self._rate_limiter.acquire("gsc_api_request")
        except RateLimitExceededError as e:
            logger.warning(
                "GSC API rate limit exceeded",
                retry_after=e.retry_after,
                current_usage=e.current_usage,
                limit=e.limit
            )
            raise GSCQuotaExceededError(
                f"Rate limit exceeded. Retry after {e.retry_after} seconds"
            ) from e
        
        try:
            # Get authentication headers
            auth_headers = await self._auth.get_auth_headers()
            
            # Merge headers
            headers = kwargs.pop('headers', {})
            headers.update(auth_headers)
            
            # Make the request
            response = await self._http_client.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            )
            
            # Check for GSC-specific errors
            if response.status_code == 429:
                # Rate limit exceeded
                retry_after = int(response.headers.get('Retry-After', 3600))
                raise GSCQuotaExceededError(
                    f"GSC API quota exceeded. Retry after {retry_after} seconds"
                )
            elif response.status_code == 403:
                # Permission denied or quota exceeded
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    pass
                
                error_msg = error_data.get('error', {}).get('message', 'Permission denied')
                if 'quota' in error_msg.lower() or 'limit' in error_msg.lower():
                    raise GSCQuotaExceededError(f"GSC API quota error: {error_msg}")
                else:
                    raise GSCAPIError(f"GSC API permission error: {error_msg}", 403)
            elif response.status_code >= 400:
                # Other client/server errors
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    pass
                
                error_msg = error_data.get('error', {}).get('message', response.text[:200])
                raise GSCAPIError(
                    f"GSC API error: {error_msg}",
                    response.status_code,
                    error_data.get('error', {}).get('code')
                )
            
            return response
            
        except (ServiceAccountAuthError, CircuitBreakerError) as e:
            logger.error(
                "GSC authentication or circuit breaker error",
                error=str(e),
                url=url
            )
            raise GSCAPIError(f"Authentication/Circuit breaker error: {e}")
        except HttpClientError as e:
            logger.error(
                "HTTP client error for GSC request",
                error=str(e),
                url=url,
                method=method
            )
            raise GSCAPIError(f"HTTP request failed: {e}")
    
    async def verify_property_access(self, property_url: str) -> bool:
        """
        Verify that the service account has access to the GSC property.
        
        Args:
            property_url: The GSC property URL
            
        Returns:
            True if access is verified, False otherwise
            
        Raises:
            GSCAPIError: On API errors
        """
        logger.info("Verifying GSC property access", property_url=property_url)
        
        try:
            encoded_url = quote(property_url, safe='')
            url = f"{self._sites_url}/{encoded_url}"
            
            response = await self._make_authenticated_request(
                HttpMethod.GET,
                url
            )
            
            if response.status_code == 200:
                site_data = response.json()
                logger.info(
                    "GSC property access verified",
                    property_url=property_url,
                    permission_level=site_data.get('permissionLevel'),
                    site_url=site_data.get('siteUrl')
                )
                return True
            else:
                logger.warning(
                    "GSC property access failed",
                    property_url=property_url,
                    status_code=response.status_code
                )
                return False
                
        except GSCAPIError as e:
            if e.status_code == 404:
                logger.warning(
                    "GSC property not found or no access",
                    property_url=property_url
                )
                return False
            raise
    
    async def list_properties(self) -> List[Dict[str, Any]]:
        """
        List all GSC properties accessible to the service account.
        
        Returns:
            List of GSC property information
            
        Raises:
            GSCAPIError: On API errors
        """
        logger.info("Listing GSC properties")
        
        response = await self._make_authenticated_request(
            HttpMethod.GET,
            self._sites_url
        )
        
        data = response.json()
        properties = data.get('siteEntry', [])
        
        logger.info(
            "Retrieved GSC properties",
            count=len(properties),
            properties=[p.get('siteUrl') for p in properties]
        )
        
        return properties
    
    async def fetch_search_analytics(
        self,
        site_id: UUID,
        site_url: str,
        start_date: date,
        end_date: date,
        dimensions: Optional[List[GSCDimension]] = None,
        filters: Optional[List[List[GSCFilter]]] = None,
        max_rows: Optional[int] = None
    ) -> AsyncGenerator[GSCMetricData, None]:
        """
        Fetch search analytics data from GSC API with pagination.
        
        Args:
            site_id: Internal site UUID
            site_url: GSC property URL  
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            dimensions: Grouping dimensions
            filters: Dimension filters
            max_rows: Maximum total rows to fetch
            
        Yields:
            GSCMetricData objects with site_id and date information
            
        Raises:
            GSCAPIError: On API errors
            GSCQuotaExceededError: On quota exceeded
        """
        if dimensions is None:
            dimensions = self.config.default_dimensions
        
        if max_rows is None:
            max_rows = self.config.max_rows_per_request * 10  # Allow pagination
        
        logger.info(
            "Fetching GSC search analytics data",
            site_id=site_id,
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=[d.value for d in dimensions],
            max_rows=max_rows
        )
        
        # Prepare API request
        request_payload = GSCSearchAnalyticsRequest(
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            dimension_filter_groups=filters,
            row_limit=min(self.config.max_rows_per_request, max_rows),
            start_row=0
        )
        
        # Build request URL
        encoded_site_url = quote(site_url, safe='')
        url = f"{self._sites_url}/{encoded_site_url}/searchAnalytics/query"
        
        total_fetched = 0
        start_row = 0
        
        while total_fetched < max_rows:
            # Update pagination
            request_payload.start_row = start_row
            remaining_rows = max_rows - total_fetched
            request_payload.row_limit = min(
                self.config.max_rows_per_request,
                remaining_rows
            )
            
            logger.debug(
                "Fetching GSC data batch",
                start_row=start_row,
                row_limit=request_payload.row_limit,
                total_fetched=total_fetched
            )
            
            try:
                # Make API request
                response = await self._make_authenticated_request(
                    HttpMethod.POST,
                    url,
                    json=request_payload.model_dump(mode='json', exclude_none=True)
                )
                
                # Parse response
                response_data = GSCSearchAnalyticsResponse.model_validate(response.json())
                
                if not response_data.rows:
                    logger.debug("No more GSC data rows available")
                    break
                
                # Process rows
                batch_count = 0
                for row in response_data.rows:
                    # Create metric data with dimension mapping
                    metric_data = self._map_row_to_metric_data(
                        row=row,
                        dimensions=dimensions,
                        site_id=site_id,
                        date=start_date if GSCDimension.DATE not in dimensions else None
                    )
                    
                    yield metric_data
                    batch_count += 1
                
                total_fetched += batch_count
                start_row += batch_count
                
                logger.debug(
                    "Processed GSC data batch",
                    batch_size=batch_count,
                    total_fetched=total_fetched
                )
                
                # Check if we got fewer rows than requested (end of data)
                if len(response_data.rows) < request_payload.row_limit:
                    logger.debug("Reached end of GSC data")
                    break
                
            except ValidationError as e:
                logger.error(
                    "GSC API response validation error",
                    error=str(e),
                    site_url=site_url,
                    start_date=start_date,
                    end_date=end_date
                )
                raise GSCAPIError(f"Invalid GSC API response: {e}")
        
        logger.info(
            "Completed GSC search analytics fetch",
            site_id=site_id,
            total_rows=total_fetched,
            start_date=start_date,
            end_date=end_date
        )
    
    def _map_row_to_metric_data(
        self,
        row: GSCRowData,
        dimensions: List[GSCDimension],
        site_id: UUID,
        date: Optional[date] = None
    ) -> GSCMetricData:
        """
        Map GSC API row data to GSCMetricData with dimension values.
        
        Args:
            row: GSC API row data
            dimensions: Ordered list of dimensions
            site_id: Internal site UUID
            date: Fixed date if DATE not in dimensions
            
        Returns:
            GSCMetricData with extracted dimension values
        """
        # Extract dimension values
        dimension_values = dict(zip([d.value for d in dimensions], row.keys))
        
        # Extract standard metric data
        metric_data = row.to_metric_data()
        
        # Add metadata
        metric_data_dict = metric_data.model_dump()
        metric_data_dict.update({
            'site_id': site_id,
            'date': date or dimension_values.get('date'),
            'url': dimension_values.get('page'),
            'query': dimension_values.get('query'),
            'country': dimension_values.get('country'),
            'device': dimension_values.get('device')
        })
        
        return GSCMetricData(**metric_data_dict)
    
    async def get_quota_usage(self) -> Dict[str, Any]:
        """
        Get current GSC API quota usage information.
        
        Returns:
            Dictionary with quota usage details
        """
        quota_info = {}
        
        # Get rate limiter status
        for limit_name in ["daily", "minute"]:
            try:
                status = await self._rate_limiter.get_limit_status(f"gsc_{limit_name}")
                quota_info[f"{limit_name}_limit"] = status
            except Exception as e:
                logger.warning(f"Failed to get {limit_name} quota status", error=str(e))
        
        return quota_info
    
    async def close(self):
        """Close the GSC client and cleanup resources."""
        if self._http_client:
            await self._http_client.close()
        
        logger.info("GSC client closed")
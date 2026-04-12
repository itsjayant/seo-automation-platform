"""
Google Analytics 4 API Client.

Main client for interacting with the Google Analytics 4 Data API,
including organic traffic data fetching, batch reporting,
and property management with rate limiting and error handling.
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional, AsyncGenerator
from uuid import UUID
from urllib.parse import urljoin, quote
from decimal import Decimal

import httpx
import structlog
from pydantic import ValidationError

from integrations.utils.http_client import HttpClient, HttpMethod
from integrations.utils.rate_limiter import RateLimiter, RateLimitConfig, RateLimitExceededError
from integrations.utils.circuit_breaker import CircuitBreakerError

from .auth import GA4Auth, ServiceAccountAuthError
from .models import (
    GA4Config, GA4Dimension, GA4Metric, GA4ChannelGroup, GA4Filter,
    GA4FilterOperator, GA4DateRange, GA4DimensionSpec, GA4MetricSpec,
    GA4RunReportRequest, GA4RunReportResponse, GA4MetricData, GA4SyncConfig
)

logger = structlog.get_logger(__name__)


class GA4APIError(Exception):
    """GA4 API specific errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class GA4QuotaExceededError(GA4APIError):
    """GA4 API quota exceeded error."""
    pass


class GA4PropertyAccessError(GA4APIError):
    """GA4 property access denied error."""
    pass


class GA4Client:
    """
    Google Analytics 4 Data API client with rate limiting and error handling.
    
    Provides methods for fetching organic traffic analytics data, managing properties,
    and handling GA4 API rate limits and authentication.
    """
    
    def __init__(
        self,
        config: GA4Config,
        http_client: Optional[HttpClient] = None,
        rate_limiter: Optional[RateLimiter] = None
    ):
        self.config = config
        self._auth = GA4Auth(config.service_account)
        self._http_client = http_client or self._create_default_http_client()
        self._rate_limiter = rate_limiter or self._create_rate_limiter()
        
        # API endpoints
        self._base_url = config.base_url.rstrip('/')
        self._run_report_url = f"{self._base_url}/v1beta/properties"
    
    def _create_default_http_client(self) -> HttpClient:
        """Create default HTTP client with GA4-specific configuration."""
        from integrations.utils.http_client import HttpClientConfig
        
        client_config = HttpClientConfig(
            base_url=self.config.base_url,
            timeout=self.config.default_timeout,
            follow_redirects=True,
            max_redirects=3,
            
            # Retry configuration  
            retry_attempts=self.config.max_retries,
            retry_delay=2.0,
            retry_backoff=self.config.backoff_factor,
            retry_on_status=[429, 500, 502, 503, 504],
            
            # Default headers
            default_headers={
                "User-Agent": "SEO-Automation-Platform/1.0 GA4-Integration",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
        )
        
        return HttpClient(client_config)
    
    def _create_rate_limiter(self) -> RateLimiter:
        """Create rate limiter for GA4 API quotas."""
        # GA4 API: 200 requests/minute, 25,000 requests/day
        minute_config = RateLimitConfig(
            requests=self.config.requests_per_minute,
            window=60,  # 1 minute
            strategy="sliding_window"
        )
        
        daily_config = RateLimitConfig(
            requests=self.config.requests_per_day,
            window=86400,  # 24 hours
            strategy="fixed_window"
        )
        
        configs = {
            "ga4_minute": minute_config,
            "ga4_daily": daily_config
        }
        
        return RateLimiter(configs=configs)
    
    async def fetch_organic_sessions(
        self,
        property_id: str,
        site_id: UUID,
        start_date: date,
        end_date: date
    ) -> List[GA4MetricData]:
        """
        Fetch organic session metrics per page for date range.
        
        Args:
            property_id: GA4 property ID (numeric string)
            site_id: Internal site UUID
            start_date: Start date for data collection
            end_date: End date for data collection
            
        Returns:
            List of GA4MetricData with organic traffic metrics
            
        Raises:
            GA4APIError: If API request fails
            GA4QuotaExceededError: If quota exceeded
            GA4PropertyAccessError: If property access denied
        """
        logger.info("Fetching GA4 organic sessions",
                  property_id=property_id, site_id=str(site_id),
                  start_date=start_date, end_date=end_date)
        
        try:
            # Build request for organic traffic data
            request = self._build_organic_traffic_request(
                property_id, start_date, end_date
            )
            
            # Execute API request with paginated results
            all_rows = []
            offset = 0
            batch_size = self.config.default_limit
            
            while True:
                request.offset = offset
                request.limit = batch_size
                
                response = await self._run_report(request)
                
                if not response.rows:
                    break
                
                all_rows.extend(response.rows)
                
                # Check if we have more data
                if len(response.rows) < batch_size:
                    break
                
                offset += batch_size
                
                # Avoid excessive pagination
                if offset >= 100000:  # GA4 API limit
                    logger.warning("Reached GA4 pagination limit",
                                 property_id=property_id, offset=offset)
                    break
            
            logger.info("Retrieved GA4 data rows",
                      property_id=property_id, total_rows=len(all_rows))
            
            # Transform API response to metric data
            return await self._transform_to_metric_data(
                all_rows, response.dimension_headers, response.metric_headers,
                site_id, property_id
            )
        
        except GA4APIError:
            raise
        except Exception as e:
            logger.error("Failed to fetch GA4 organic sessions",
                       property_id=property_id, error=str(e))
            raise GA4APIError(f"Failed to fetch organic sessions: {e}")
    
    def _build_organic_traffic_request(
        self,
        property_id: str,
        start_date: date,
        end_date: date
    ) -> GA4RunReportRequest:
        """Build GA4 API request for organic traffic data."""
        
        # Format property ID
        formatted_property = f"properties/{property_id}"
        
        # Date range
        date_range = GA4DateRange(
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )
        
        # Dimensions we need
        dimensions = [
            GA4DimensionSpec(name=GA4Dimension.PAGE_PATH),
            GA4DimensionSpec(name=GA4Dimension.SOURCE_MEDIUM),
            GA4DimensionSpec(name=GA4Dimension.SESSION_DEFAULT_CHANNEL_GROUP),
            GA4DimensionSpec(name=GA4Dimension.COUNTRY),
            GA4DimensionSpec(name=GA4Dimension.DEVICE_CATEGORY),
            GA4DimensionSpec(name=GA4Dimension.DATE)
        ]
        
        # Metrics we want
        metrics = [
            GA4MetricSpec(name=GA4Metric.SESSIONS),
            GA4MetricSpec(name=GA4Metric.SCREEN_PAGE_VIEWS),
            GA4MetricSpec(name=GA4Metric.BOUNCE_RATE),
            GA4MetricSpec(name=GA4Metric.AVG_SESSION_DURATION),
            GA4MetricSpec(name=GA4Metric.NEW_USERS)
        ]
        
        # Filter for organic search traffic only
        organic_filter = GA4Filter(
            field_name=GA4Dimension.SESSION_DEFAULT_CHANNEL_GROUP,
            operator=GA4FilterOperator.EXACT,
            value=GA4ChannelGroup.ORGANIC_SEARCH.value
        )
        
        return GA4RunReportRequest(
            property=formatted_property,
            date_ranges=[date_range],
            dimensions=dimensions,
            metrics=metrics,
            dimension_filter=organic_filter,
            limit=self.config.default_limit
        )
    
    async def _run_report(self, request: GA4RunReportRequest) -> GA4RunReportResponse:
        """Execute GA4 Run Report API request."""
        
        # Parse property ID from request
        property_id = request.property.split('/')[-1]
        url = f"{self._run_report_url}/{property_id}:runReport"
        
        try:
            # Rate limiting
            await self._rate_limiter.acquire()
            
            # Get authentication token
            token = await self._auth.get_access_token()
            
            # Prepare request payload
            payload = request.model_dump(exclude_none=True, by_alias=True)
            
            # Make API request
            headers = {
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json"
            }
            
            response = await self._http_client.request(
                method=HttpMethod.POST,
                url=url,
                json=payload,
                headers=headers
            )
            
            # Parse response
            response_data = response.json()
            
            return GA4RunReportResponse(**response_data)
        
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            # Handle specific GA4 API errors
            status_code = getattr(e, 'response', {}).status_code if hasattr(e, 'response') else None
            
            if status_code == 429:
                raise GA4QuotaExceededError("GA4 API quota exceeded") from e
            elif status_code == 403:
                raise GA4PropertyAccessError("GA4 property access denied") from e
            elif status_code in [401, 403]:
                raise GA4APIError("GA4 authentication failed") from e
            else:
                raise GA4APIError(f"GA4 API error: {e}") from e
        
        except ValidationError as e:
            logger.error("Invalid GA4 API response format", error=str(e))
            raise GA4APIError(f"Invalid API response format: {e}")
        
        except Exception as e:
            logger.error("Unexpected GA4 API error", error=str(e))
            raise GA4APIError(f"Unexpected API error: {e}")
    
    async def _transform_to_metric_data(
        self,
        rows: List[Any],
        dimension_headers: List[Any],
        metric_headers: List[Any],
        site_id: UUID,
        property_id: str
    ) -> List[GA4MetricData]:
        """Transform GA4 API response rows to GA4MetricData objects."""
        
        metric_data = []
        
        # Create dimension and metric name mappings
        dimension_names = [header.api_name for header in dimension_headers]
        metric_names = [header.api_name for header in metric_headers]
        
        for row in rows:
            try:
                # Extract dimension values
                dimensions = {}
                for i, value in enumerate(row.dimension_values):
                    if i < len(dimension_names):
                        dimensions[dimension_names[i]] = value.value or ""
                
                # Extract metric values
                metrics = {}
                for i, value in enumerate(row.metric_values):
                    if i < len(metric_names):
                        raw_value = value.value or "0"
                        metrics[metric_names[i]] = raw_value
                
                # Parse date
                row_date = datetime.strptime(dimensions.get('date', ''), '%Y%m%d').date()
                
                # Create metric data object
                metric_item = GA4MetricData(
                    site_id=site_id,
                    date=row_date,
                    property_id=property_id,
                    page_path=dimensions.get('pagePath', '/'),
                    source_medium=dimensions.get('sourceMedium'),
                    channel_group=dimensions.get('sessionDefaultChannelGroup'),
                    country=dimensions.get('country'),
                    device_category=dimensions.get('deviceCategory'),
                    sessions=int(float(metrics.get('sessions', '0'))),
                    page_views=int(float(metrics.get('screenPageViews', '0'))),
                    unique_page_views=0,  # Not directly available in GA4
                    bounce_rate=self._safe_decimal(metrics.get('bounceRate')),
                    avg_session_duration=self._safe_int(metrics.get('averageSessionDuration')),
                    new_users=int(float(metrics.get('newUsers', '0'))),
                    conversions=0,  # Would need to be configured separately
                    revenue=None
                )
                
                metric_data.append(metric_item)
                
            except Exception as e:
                logger.warning("Failed to parse GA4 row data",
                             error=str(e), row_data=row)
                continue
        
        logger.info("Transformed GA4 data to metric objects",
                  total_metrics=len(metric_data))
        
        return metric_data
    
    def _safe_decimal(self, value: Optional[str]) -> Optional[Decimal]:
        """Safely convert string to Decimal."""
        if not value:
            return None
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return None
    
    def _safe_int(self, value: Optional[str]) -> Optional[int]:
        """Safely convert string to int."""
        if not value:
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    
    async def test_connection(self, property_id: Optional[str] = None) -> bool:
        """
        Test connection to GA4 API and property access.
        
        Args:
            property_id: Property ID to test, or use default
            
        Returns:
            True if connection and auth work, False otherwise
        """
        try:
            test_property_id = property_id or self.config.default_property_id
            
            if not test_property_id:
                raise GA4APIError("No property ID provided for connection test")
            
            # Try a simple query for yesterday's data
            yesterday = date.today() - timedelta(days=1)
            
            request = GA4RunReportRequest(
                property=f"properties/{test_property_id}",
                date_ranges=[GA4DateRange(
                    start_date=yesterday.strftime('%Y-%m-%d'),
                    end_date=yesterday.strftime('%Y-%m-%d')
                )],
                dimensions=[GA4DimensionSpec(name=GA4Dimension.DATE)],
                metrics=[GA4MetricSpec(name=GA4Metric.SESSIONS)],
                limit=1
            )
            
            response = await self._run_report(request)
            
            logger.info("GA4 connection test successful",
                      property_id=test_property_id)
            return True
        
        except Exception as e:
            logger.error("GA4 connection test failed",
                       property_id=property_id, error=str(e))
            return False
    
    async def get_property_metadata(self, property_id: str) -> Dict[str, Any]:
        """
        Get metadata about a GA4 property.
        
        Args:
            property_id: GA4 property ID
            
        Returns:
            Property metadata dict
            
        Note:
            This uses the GA4 Management API which is available but limited.
            For full metadata, you'd need the Google Analytics Admin API.
        """
        logger.info("Getting GA4 property metadata", property_id=property_id)
        
        try:
            # For now, return basic info from a test query
            yesterday = date.today() - timedelta(days=1)
            
            request = GA4RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[GA4DateRange(
                    start_date=yesterday.strftime('%Y-%m-%d'),
                    end_date=yesterday.strftime('%Y-%m-%d')
                )],
                dimensions=[],
                metrics=[GA4MetricSpec(name=GA4Metric.SESSIONS)],
                limit=1
            )
            
            response = await self._run_report(request)
            
            return {
                "property_id": property_id,
                "accessible": True,
                "metric_headers": [h.model_dump() for h in response.metric_headers],
                "dimension_headers": [h.model_dump() for h in response.dimension_headers]
            }
        
        except Exception as e:
            logger.error("Failed to get GA4 property metadata",
                       property_id=property_id, error=str(e))
            return {
                "property_id": property_id,
                "accessible": False,
                "error": str(e)
            }
    
    async def close(self) -> None:
        """Clean up client resources."""
        if self._http_client:
            await self._http_client.close()
        
        logger.info("GA4 client closed")
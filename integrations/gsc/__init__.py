"""
Google Search Console Integration

Provides Google Search Console API integration with OAuth 2.0 service account
authentication, rate limiting, and data transformation to SQLAlchemy models.

Main Components:
    - GSCClient: Main API client for Search Console data
    - GSCAuth: Service account authentication handling
    - GSCSync: Incremental data synchronization logic
    - GSCTransformer: Data transformation utilities

Usage:
    >>> from integrations.gsc import GSCClient, GSCConfig
    >>> from integrations.gsc.models import GSCDimension
    >>> 
    >>> config = GSCConfig(
    ...     service_account_path="/path/to/service-account.json",
    ...     property_url="https://example.com"
    ... )
    >>> client = GSCClient(config)
    >>> 
    >>> # Fetch search analytics data
    >>> from datetime import date, timedelta
    >>> end_date = date.today() - timedelta(days=3)  # GSC data has 2-3 day delay
    >>> start_date = end_date - timedelta(days=7)
    >>> 
    >>> data = await client.fetch_search_analytics(
    ...     site_id=site_uuid,
    ...     site_url="https://example.com", 
    ...     start_date=start_date,
    ...     end_date=end_date,
    ...     dimensions=[GSCDimension.PAGE, GSCDimension.QUERY]
    ... )
"""

from .client import GSCClient
from .auth import GSCAuth, ServiceAccountConfig
from .models import (
    GSCConfig, GSCDimension, GSCFilter, GSCMetricData,
    GSCSearchAnalyticsRequest, GSCSearchAnalyticsResponse
)
from .sync import GSCSync, GSCSyncConfig 
from .transformers import GSCTransformer

__all__ = [
    "GSCClient",
    "GSCAuth", 
    "ServiceAccountConfig",
    "GSCConfig",
    "GSCDimension",
    "GSCFilter", 
    "GSCMetricData",
    "GSCSearchAnalyticsRequest",
    "GSCSearchAnalyticsResponse",
    "GSCSync",
    "GSCSyncConfig",
    "GSCTransformer",
]
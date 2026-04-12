"""
Google Analytics 4 Integration Package.

This package provides comprehensive GA4 Data API integration for SEO analytics,
including authentication, data fetching, transformation, and synchronization.

Main Components:
    - GA4Client: Main API client for data retrieval
    - GA4Auth: Service account authentication
    - GA4Sync: Incremental data synchronization 
    - GA4DataTransformer: Data transformation utilities
    - Models: Pydantic models for API requests/responses

Example Usage:
    ```python
    from integrations.ga4 import GA4Client, GA4Config, ServiceAccountConfig
    
    # Configure client
    config = GA4Config(
        service_account=ServiceAccountConfig(
            json_file_path="/path/to/service-account.json"
        ),
        default_property_id="123456789"
    )
    
    # Create client and fetch data
    client = GA4Client(config)
    metrics = await client.fetch_organic_sessions(
        property_id="123456789",
        site_id=site_uuid,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31)
    )
    ```
"""

from .auth import GA4Auth, ServiceAccountAuthError
from .client import GA4Client, GA4APIError, GA4QuotaExceededError, GA4PropertyAccessError
from .models import (
    # Configuration models
    GA4Config, ServiceAccountConfig, GA4SyncConfig,
    
    # API models
    GA4Dimension, GA4Metric, GA4ChannelGroup, GA4DeviceCategory,
    GA4Filter, GA4FilterOperator, GA4DateRange,
    GA4DimensionSpec, GA4MetricSpec,
    GA4RunReportRequest, GA4RunReportResponse,
    
    # Data models
    GA4MetricData, GA4Row, GA4DimensionValue, GA4MetricValue,
    GA4DimensionMetadata, GA4MetricMetadata
)
from .sync import GA4Sync, GA4SyncError
from .transformers import GA4DataTransformer

__all__ = [
    # Main classes
    "GA4Client",
    "GA4Auth", 
    "GA4Sync",
    "GA4DataTransformer",
    
    # Configuration
    "GA4Config",
    "ServiceAccountConfig", 
    "GA4SyncConfig",
    
    # API enums and models
    "GA4Dimension",
    "GA4Metric", 
    "GA4ChannelGroup",
    "GA4DeviceCategory",
    "GA4Filter",
    "GA4FilterOperator",
    "GA4DateRange",
    "GA4DimensionSpec",
    "GA4MetricSpec",
    "GA4RunReportRequest",
    "GA4RunReportResponse",
    
    # Data models
    "GA4MetricData",
    "GA4Row",
    "GA4DimensionValue",
    "GA4MetricValue", 
    "GA4DimensionMetadata",
    "GA4MetricMetadata",
    
    # Exceptions
    "GA4APIError",
    "GA4QuotaExceededError",
    "GA4PropertyAccessError",
    "ServiceAccountAuthError",
    "GA4SyncError"
]

# Package metadata
__version__ = "1.0.0"
__author__ = "SEO Automation Platform"
__description__ = "Google Analytics 4 integration for organic traffic analytics"
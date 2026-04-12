"""
Google Search Console data models and configurations.

This module defines Pydantic models for GSC API requests, responses,
and configuration classes used throughout the GSC integration.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, validator


class GSCDimension(str, Enum):
    """GSC Search Analytics API dimensions."""
    
    PAGE = "page"
    QUERY = "query"  
    COUNTRY = "country"
    DEVICE = "device"
    SEARCH_APPEARANCE = "searchAppearance"
    DATE = "date"


class GSCDevice(str, Enum):
    """GSC device types."""
    
    DESKTOP = "DESKTOP"
    MOBILE = "MOBILE" 
    TABLET = "TABLET"


class GSCSearchType(str, Enum):
    """GSC search types."""
    
    WEB = "web"
    IMAGE = "image"
    VIDEO = "video"
    NEWS = "news"


class GSCFilterOperator(str, Enum):
    """GSC filter operators."""
    
    EQUALS = "equals"
    NOT_EQUALS = "notEquals" 
    CONTAINS = "contains"
    NOT_CONTAINS = "notContains"
    INCLUDING_REGEX = "includingRegex"
    EXCLUDING_REGEX = "excludingRegex"


class GSCFilter(BaseModel):
    """GSC API filter specification."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    dimension: GSCDimension
    operator: GSCFilterOperator
    expression: str
    
    @validator('expression')
    def expression_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Filter expression cannot be empty')
        return v


class GSCSearchAnalyticsRequest(BaseModel):
    """GSC Search Analytics API request payload."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    # Date range (required)
    start_date: date = Field(..., description="Start date (inclusive)")
    end_date: date = Field(..., description="End date (inclusive)")
    
    # Dimensions (optional, max 7)
    dimensions: List[GSCDimension] = Field(
        default=[GSCDimension.PAGE],
        max_length=7,
        description="Grouping dimensions"
    )
    
    # Filters (optional, max 25)
    dimension_filter_groups: Optional[List[List[GSCFilter]]] = Field(
        default=None,
        max_length=25,
        description="Filter groups (AND within group, OR between groups)"
    )
    
    # Search type (optional)
    search_type: GSCSearchType = Field(
        default=GSCSearchType.WEB,
        description="Type of search result"
    )
    
    # Data state (optional)
    data_state: Optional[str] = Field(
        default="final",
        description="Data freshness: 'final' or 'fresh'"
    )
    
    # Aggregation type (optional)
    aggregation_type: Optional[str] = Field(
        default="auto",
        description="How data is aggregated across rows"
    )
    
    # Result limits
    start_row: int = Field(default=0, ge=0, le=25000, description="Starting row (0-based)")
    row_limit: int = Field(default=1000, ge=1, le=25000, description="Maximum rows to return")
    
    @validator('dimensions')
    def validate_dimensions(cls, v):
        if len(v) == 0:
            raise ValueError('At least one dimension is required')
        if len(set(v)) != len(v):
            raise ValueError('Duplicate dimensions not allowed')
        return v
    
    @validator('end_date')
    def date_range_valid(cls, v, values):
        if 'start_date' in values and v < values['start_date']:
            raise ValueError('end_date must be >= start_date')
        return v


class GSCMetricData(BaseModel):
    """GSC metrics data from API response."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    clicks: int = Field(default=0, ge=0, description="Number of clicks")
    impressions: int = Field(default=0, ge=0, description="Number of impressions")
    ctr: Decimal = Field(default=Decimal('0'), ge=0, le=1, description="Click-through rate")
    position: Decimal = Field(default=Decimal('0'), ge=0, description="Average position")
    
    @validator('ctr', 'position', pre=True)
    def convert_to_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v


class GSCRowData(BaseModel):
    """Single row of GSC search analytics data."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    keys: List[str] = Field(..., description="Dimension values for this row")
    clicks: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    ctr: float = Field(default=0.0, ge=0, le=1)
    position: float = Field(default=0.0, ge=0)
    
    def to_metric_data(self) -> GSCMetricData:
        """Convert to GSCMetricData with proper decimal conversion."""
        return GSCMetricData(
            clicks=self.clicks,
            impressions=self.impressions,
            ctr=Decimal(str(self.ctr)),
            position=Decimal(str(self.position))
        )


class GSCSearchAnalyticsResponse(BaseModel):
    """GSC Search Analytics API response."""
    
    model_config = ConfigDict(use_enum_values=True)
    
    rows: Optional[List[GSCRowData]] = Field(
        default=None,
        description="Data rows (None if no data)"
    )
    
    response_aggregation_type: Optional[str] = Field(
        default=None,
        description="How data was aggregated"
    )


class ServiceAccountConfig(BaseModel):
    """Service account authentication configuration."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    # Service account credentials
    service_account_path: Optional[str] = Field(
        default=None,
        description="Path to service account JSON file"
    )
    service_account_info: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Service account info as dict (alternative to file)"
    )
    
    # OAuth scopes
    scopes: List[str] = Field(
        default=["https://www.googleapis.com/auth/webmasters.readonly"],
        description="OAuth 2.0 scopes"
    )
    
    # Token management
    token_cache_key: str = Field(
        default="gsc_service_account_token",
        description="Redis cache key for token storage"
    )
    
    @validator('service_account_path', 'service_account_info')
    def at_least_one_auth_method(cls, v, values):
        if not v and not values.get('service_account_info'):
            if not values.get('service_account_path'):
                raise ValueError(
                    'Either service_account_path or service_account_info must be provided'
                )
        return v


class GSCConfig(BaseModel):
    """Main GSC integration configuration."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    # Authentication
    service_account: ServiceAccountConfig
    
    # Site configuration
    property_url: str = Field(..., description="GSC property URL (e.g., https://example.com)")
    
    # API configuration
    base_url: str = Field(
        default="https://www.googleapis.com/webmasters/v3",
        description="GSC API base URL"
    )
    
    # Rate limiting (GSC free tier: 200 queries/day)
    requests_per_day: int = Field(default=200, description="Daily quota limit")
    requests_per_minute: int = Field(default=10, description="Per-minute rate limit")
    
    # Data fetch configuration
    max_rows_per_request: int = Field(
        default=1000,
        ge=1,
        le=25000,
        description="Maximum rows per API request"
    )
    
    default_dimensions: List[GSCDimension] = Field(
        default=[GSCDimension.PAGE, GSCDimension.QUERY],
        description="Default dimensions for search analytics requests"
    )
    
    # Data retention (GSC has ~16 months of data)
    max_historical_days: int = Field(
        default=450,  # ~15 months to be safe
        description="Maximum days of historical data to fetch"
    )
    
    # Sync configuration
    data_delay_days: int = Field(
        default=3,
        description="Days to wait for data freshness (GSC has 2-3 day delay)"
    )
    
    batch_size_days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Number of days to fetch per batch request"
    )
    
    @validator('property_url')
    def validate_property_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('property_url must start with http:// or https://')
        return v.rstrip('/')


class GSCSyncConfig(BaseModel):
    """Configuration for GSC data synchronization."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    # Sync behavior
    incremental_sync: bool = Field(
        default=True,
        description="Enable incremental sync (only fetch new data)"
    )
    
    backfill_days: int = Field(
        default=7,
        ge=1,
        description="Days to overlap in incremental sync for data updates"
    )
    
    # Error handling
    max_retries: int = Field(default=3, ge=0, description="Max retries for failed requests")
    retry_delay_seconds: int = Field(default=60, ge=1, description="Base retry delay")
    
    # Batch processing
    concurrent_requests: int = Field(
        default=2,
        ge=1,
        le=5, 
        description="Max concurrent API requests"
    )
    
    batch_insert_size: int = Field(
        default=1000,
        ge=100,
        description="Database batch insert size"
    )
    
    # Data validation
    skip_invalid_rows: bool = Field(
        default=True,
        description="Skip rows that fail validation instead of failing sync"
    )
    
    validate_metrics: bool = Field(
        default=True,
        description="Validate metric values (clicks >= 0, ctr <= 1, etc.)"
    )
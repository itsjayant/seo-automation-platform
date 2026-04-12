"""
Google Analytics 4 data models and configurations.

This module defines Pydantic models for GA4 API requests, responses,
and configuration classes used throughout the GA4 integration.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, validator


class GA4Dimension(str, Enum):
    """GA4 Data API dimensions for organic traffic analysis."""
    
    PAGE_PATH = "pagePath"
    PAGE_TITLE = "pageTitle"
    LANDING_PAGE = "landingPage"
    SOURCE_MEDIUM = "sourceMedium"
    SESSION_DEFAULT_CHANNEL_GROUP = "sessionDefaultChannelGroup"
    COUNTRY = "country"
    DEVICE_CATEGORY = "deviceCategory"
    DATE = "date"


class GA4Metric(str, Enum):
    """GA4 Data API metrics for organic traffic tracking."""
    
    SESSIONS = "sessions"
    SCREEN_PAGE_VIEWS = "screenPageViews"
    BOUNCE_RATE = "bounceRate"
    AVG_SESSION_DURATION = "averageSessionDuration"
    NEW_USERS = "newUsers"
    CONVERSIONS = "conversions"
    TOTAL_REVENUE = "totalRevenue"


class GA4ChannelGroup(str, Enum):
    """GA4 default channel grouping values."""
    
    ORGANIC_SEARCH = "Organic Search"
    DIRECT = "Direct"
    PAID_SEARCH = "Paid Search"
    SOCIAL = "Organic Social"
    EMAIL = "Email"
    REFERRAL = "Referral"
    DISPLAY = "Display"
    AFFILIATE = "Affiliates"
    VIDEO = "Organic Video"
    OTHER = "Unassigned"


class GA4DeviceCategory(str, Enum):
    """GA4 device categories."""
    
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"


class GA4FilterOperator(str, Enum):
    """GA4 filter operators for dimension filtering."""
    
    EXACT = "EXACT"
    BEGINS_WITH = "BEGINS_WITH"
    ENDS_WITH = "ENDS_WITH"
    CONTAINS = "CONTAINS"
    REGEX_MATCH = "FULL_REGEXP"
    REGEX_PARTIAL = "PARTIAL_REGEXP"
    NUMERIC_EQUAL = "NUMERIC_EQUAL"
    NUMERIC_GREATER = "NUMERIC_GREATER_THAN"
    NUMERIC_LESS = "NUMERIC_LESS_THAN"
    NUMERIC_BETWEEN = "NUMERIC_BETWEEN"
    IN_LIST = "IN_LIST"


class GA4Filter(BaseModel):
    """GA4 API dimension filter specification."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    field_name: GA4Dimension
    operator: GA4FilterOperator
    value: Union[str, List[str], Dict[str, Any]]
    
    @validator('value')
    def validate_value_not_empty(cls, v, values):
        if isinstance(v, str) and not v.strip():
            raise ValueError('String filter value cannot be empty')
        elif isinstance(v, list) and not v:
            raise ValueError('List filter value cannot be empty')
        return v


class GA4DateRange(BaseModel):
    """GA4 date range specification."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format or relative like 'yesterday'")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format or relative like 'today'")
    
    @validator('start_date', 'end_date')
    def validate_date_format(cls, v):
        # Allow relative dates or YYYY-MM-DD format
        relative_dates = {'today', 'yesterday', '7daysAgo', '30daysAgo', '90daysAgo'}
        if v in relative_dates:
            return v
        
        # Validate YYYY-MM-DD format
        try:
            from datetime import datetime
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError(f'Date must be YYYY-MM-DD format or relative date, got: {v}')


class GA4DimensionSpec(BaseModel):
    """GA4 dimension specification for API requests."""
    
    model_config = ConfigDict(use_enum_values=True)
    
    name: GA4Dimension


class GA4MetricSpec(BaseModel):
    """GA4 metric specification for API requests."""
    
    model_config = ConfigDict(use_enum_values=True)
    
    name: GA4Metric


class GA4RunReportRequest(BaseModel):
    """GA4 Run Report API request payload."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    property: str = Field(..., description="GA4 property ID (e.g., 'properties/123456789')")
    date_ranges: List[GA4DateRange] = Field(..., min_items=1, max_items=4)
    dimensions: List[GA4DimensionSpec] = Field(default_factory=list, max_items=9)
    metrics: List[GA4MetricSpec] = Field(..., min_items=1, max_items=10)
    dimension_filter: Optional[GA4Filter] = Field(None, description="Filter to apply to dimensions")
    metric_filter: Optional[GA4Filter] = Field(None, description="Filter to apply to metrics")
    offset: int = Field(0, ge=0, description="Number of rows to skip")
    limit: int = Field(10000, ge=1, le=100000, description="Maximum rows to return")
    order_bys: Optional[List[Dict[str, Any]]] = Field(None, description="Ordering specifications")


class GA4DimensionValue(BaseModel):
    """GA4 dimension value in API response."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    value: Optional[str] = None
    one_value: Optional[str] = None


class GA4MetricValue(BaseModel):
    """GA4 metric value in API response."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    value: Optional[str] = None
    one_value: Optional[str] = None


class GA4Row(BaseModel):
    """GA4 data row in API response."""
    
    model_config = ConfigDict()
    
    dimension_values: List[GA4DimensionValue] = Field(default_factory=list)
    metric_values: List[GA4MetricValue] = Field(default_factory=list)


class GA4DimensionMetadata(BaseModel):
    """GA4 dimension metadata in API response."""
    
    model_config = ConfigDict()
    
    api_name: str
    ui_name: Optional[str] = None
    description: Optional[str] = None


class GA4MetricMetadata(BaseModel):
    """GA4 metric metadata in API response."""
    
    model_config = ConfigDict()
    
    api_name: str
    ui_name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None


class GA4RunReportResponse(BaseModel):
    """GA4 Run Report API response."""
    
    model_config = ConfigDict()
    
    dimension_headers: List[GA4DimensionMetadata] = Field(default_factory=list)
    metric_headers: List[GA4MetricMetadata] = Field(default_factory=list)
    rows: List[GA4Row] = Field(default_factory=list)
    row_count: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class ServiceAccountConfig(BaseModel):
    """Service account configuration for GA4 authentication."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    # Either provide the JSON file path or the credential fields directly
    json_file_path: Optional[str] = Field(None, description="Path to service account JSON file")
    
    # Or provide individual fields
    type: str = Field("service_account", description="Service account type")
    project_id: Optional[str] = Field(None, description="Google Cloud project ID")
    private_key_id: Optional[str] = Field(None, description="Private key ID")
    private_key: Optional[str] = Field(None, description="Private key in PEM format")
    client_email: Optional[str] = Field(None, description="Service account email")
    client_id: Optional[str] = Field(None, description="Client ID")
    auth_uri: str = Field("https://accounts.google.com/o/oauth2/auth", description="Auth URI")
    token_uri: str = Field("https://oauth2.googleapis.com/token", description="Token URI")
    auth_provider_x509_cert_url: str = Field(
        "https://www.googleapis.com/oauth2/v1/certs",
        description="Auth provider certificate URL"
    )
    client_x509_cert_url: Optional[str] = Field(None, description="Client certificate URL")
    
    @validator('project_id', 'client_email', 'private_key')
    def required_fields_when_no_json_file(cls, v, values):
        if not values.get('json_file_path') and not v:
            raise ValueError('Required when json_file_path is not provided')
        return v


class GA4Config(BaseModel):
    """GA4 client configuration."""
    
    model_config = ConfigDict(str_strip_whitespace=True)
    
    # Authentication
    service_account: ServiceAccountConfig
    
    # API configuration
    base_url: str = Field(
        "https://analyticsdata.googleapis.com",
        description="GA4 Data API base URL"
    )
    
    # Default property ID (can be overridden per request)
    default_property_id: Optional[str] = Field(
        None,
        description="Default GA4 property ID (e.g., '123456789')"
    )
    
    # Rate limiting
    requests_per_minute: int = Field(200, ge=1, le=500, description="Requests per minute")
    requests_per_day: int = Field(25000, ge=1, description="Requests per day")
    
    # Retry configuration
    max_retries: int = Field(3, ge=0, le=10)
    backoff_factor: float = Field(2.0, ge=1.0, le=10.0)
    
    # Request defaults
    default_limit: int = Field(10000, ge=1, le=100000)
    default_timeout: float = Field(30.0, ge=5.0, le=300.0)
    
    @validator('default_property_id')
    def validate_property_id_format(cls, v):
        if v is not None and not v.isdigit():
            raise ValueError('Property ID must be numeric string')
        return v


class GA4MetricData(BaseModel):
    """Processed GA4 metric data for database storage."""
    
    model_config = ConfigDict()
    
    # Metadata
    site_id: UUID
    date: date
    property_id: str
    
    # Dimensions
    page_path: str
    landing_page: Optional[str] = None
    source_medium: Optional[str] = None
    channel_group: Optional[str] = None
    country: Optional[str] = None
    device_category: Optional[str] = None
    
    # Metrics
    sessions: int = 0
    page_views: int = 0
    unique_page_views: int = 0
    bounce_rate: Optional[Decimal] = None
    avg_session_duration: Optional[int] = None  # seconds
    new_users: int = 0
    conversions: int = 0
    revenue: Optional[Decimal] = None
    
    @validator('bounce_rate')
    def validate_bounce_rate_range(cls, v):
        if v is not None and (v < 0 or v > 1):
            raise ValueError('Bounce rate must be between 0 and 1')
        return v
    
    @validator('page_path')
    def validate_page_path_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Page path cannot be empty')
        return v.strip()


class GA4SyncConfig(BaseModel):
    """Configuration for GA4 data synchronization."""
    
    model_config = ConfigDict()
    
    property_id: str
    site_id: UUID
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    
    # Sync options
    include_bounce_rate: bool = True
    include_session_duration: bool = True
    include_conversions: bool = True
    include_revenue: bool = False
    
    # Filtering
    organic_only: bool = True
    min_sessions: int = 0
    
    # Batch processing
    batch_size: int = Field(1000, ge=100, le=10000)
    max_concurrent_requests: int = Field(3, ge=1, le=10)
"""
SerpAPI Response Models and Data Structures

Pydantic models for SerpAPI responses, search parameters, and internal
data structures for rank tracking and SERP feature detection.
"""

from datetime import date as Date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Union, Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, validator, ConfigDict


class DeviceType(str, Enum):
    """Device types for search targeting."""
    DESKTOP = "desktop"
    MOBILE = "mobile"  
    TABLET = "tablet"


class LocationTarget(BaseModel):
    """Geographic location targeting for searches."""
    
    country: str = Field(..., description="Country code (ISO 3166-1 alpha-2)")
    state: Optional[str] = Field(None, description="State/province code")
    city: Optional[str] = Field(None, description="City name") 
    
    # SerpAPI location format
    google_domain: Optional[str] = Field(None, description="Google domain (e.g., google.com)")
    gl_country: Optional[str] = Field(None, description="Geographic location country")
    hl_language: Optional[str] = Field(None, description="Host language")
    
    @validator('country')
    def validate_country_code(cls, v):
        """Ensure country code is 2 characters."""
        if len(v) != 2:
            raise ValueError('Country code must be 2 characters (ISO 3166-1 alpha-2)')
        return v.upper()


class SearchParams(BaseModel):
    """Parameters for SerpAPI search requests."""
    
    # Core search parameters
    query: str = Field(..., description="Search query/keyword")
    location: LocationTarget = Field(..., description="Geographic targeting")
    device: DeviceType = Field(default=DeviceType.DESKTOP, description="Device type")
    language: str = Field(default="en", description="Search language")
    
    # Result configuration
    num_results: int = Field(default=100, ge=10, le=100, description="Number of results to fetch")
    safe_search: bool = Field(default=False, description="Enable safe search")
    
    # Advanced parameters
    start_page: int = Field(default=0, ge=0, description="Starting page (0-based)")
    no_cache: bool = Field(default=False, description="Bypass SerpAPI cache")
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    def to_serpapi_params(self) -> Dict[str, Any]:
        """Convert to SerpAPI request parameters."""
        params = {
            "q": self.query,
            "engine": "google",
            "num": self.num_results,
            "device": self.device.value,
            "hl": self.language,
            "safe": "active" if self.safe_search else "off",
            "start": self.start_page * self.num_results,
            "no_cache": self.no_cache,
        }
        
        # Add location parameters
        if self.location.google_domain:
            params["google_domain"] = self.location.google_domain
        if self.location.gl_country:
            params["gl"] = self.location.gl_country
        if self.location.hl_language:
            params["hl"] = self.location.hl_language
            
        return params


class SerpFeatures(BaseModel):
    """SERP feature flags for rich results."""
    
    featured_snippet: bool = Field(default=False, description="Featured snippet present")
    people_also_ask: bool = Field(default=False, description="People Also Ask box present")
    image_pack: bool = Field(default=False, description="Image pack results present")
    video_results: bool = Field(default=False, description="Video results present")
    local_pack: bool = Field(default=False, description="Local pack results present")
    knowledge_panel: bool = Field(default=False, description="Knowledge panel present")
    shopping_results: bool = Field(default=False, description="Shopping results present")
    news_results: bool = Field(default=False, description="News results present")
    
    model_config = ConfigDict(validate_assignment=True)


class OrganicResult(BaseModel):
    """Individual organic search result."""
    
    position: int = Field(..., ge=1, le=100, description="Position in results (1-indexed)")
    title: str = Field(..., description="Result title")
    link: HttpUrl = Field(..., description="Result URL")
    displayed_link: str = Field(..., description="Displayed URL in SERP")
    snippet: Optional[str] = Field(None, description="Result snippet/description")
    
    # Rich result indicators
    sitelinks: bool = Field(default=False, description="Has sitelinks")
    cached_page_link: Optional[HttpUrl] = Field(None, description="Cached page URL")
    
    # Additional metadata
    domain: Optional[str] = Field(None, description="Domain extracted from URL")
    path: Optional[str] = Field(None, description="Path extracted from URL")
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    @validator('domain', always=True)
    def extract_domain(cls, v, values):
        """Extract domain from link if not provided."""
        if v is None and 'link' in values:
            from urllib.parse import urlparse
            parsed = urlparse(str(values['link']))
            return parsed.netloc
        return v
    
    @validator('path', always=True)  
    def extract_path(cls, v, values):
        """Extract path from link if not provided."""
        if v is None and 'link' in values:
            from urllib.parse import urlparse
            parsed = urlparse(str(values['link']))
            return parsed.path
        return v


class SerpResult(BaseModel):
    """Complete SerpAPI search result."""
    
    # Request metadata
    search_params: SearchParams = Field(..., description="Original search parameters")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Result timestamp")
    
    # SerpAPI metadata  
    search_id: Optional[str] = Field(None, description="SerpAPI search ID")
    credits_used: Optional[int] = Field(None, description="API credits consumed")
    credits_remaining: Optional[int] = Field(None, description="Remaining API credits")
    
    # Search metadata
    total_results: Optional[int] = Field(None, description="Total estimated results")
    time_taken: Optional[float] = Field(None, description="Search execution time")
    
    # Results
    organic_results: List[OrganicResult] = Field(default_factory=list, description="Organic search results")
    serp_features: SerpFeatures = Field(default_factory=SerpFeatures, description="SERP features detected")
    
    # Additional result types
    featured_snippet_result: Optional[Dict[str, Any]] = Field(None, description="Featured snippet data")
    people_also_ask: List[Dict[str, Any]] = Field(default_factory=list, description="People Also Ask questions")
    local_results: List[Dict[str, Any]] = Field(default_factory=list, description="Local pack results")
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        arbitrary_types_allowed=True
    )
    
    @property
    def has_results(self) -> bool:
        """Check if search returned organic results."""
        return len(self.organic_results) > 0
    
    def get_position_for_domain(self, domain: str) -> Optional[int]:
        """Find the highest ranking position for a domain."""
        domain_results = [r for r in self.organic_results if r.domain == domain]
        if not domain_results:
            return None
        return min(r.position for r in domain_results)
    
    def get_positions_for_domain(self, domain: str) -> List[int]:
        """Get all positions for a domain."""
        return [r.position for r in self.organic_results if r.domain == domain]


class RankingData(BaseModel):
    """Processed ranking data for database storage."""
    
    # Identifiers
    site_id: UUID = Field(..., description="Site identifier")
    keyword_id: UUID = Field(..., description="Keyword identifier")
    keyword: str = Field(..., description="Search keyword")
    
    # Tracking date and search parameters
    date: Date = Field(..., description="Tracking date")
    location: str = Field(..., description="Search location")
    device: DeviceType = Field(..., description="Device type")
    
    # Ranking results
    position: Optional[int] = Field(None, ge=1, le=100, description="Best position found")
    url: Optional[HttpUrl] = Field(None, description="Ranking URL")
    all_positions: List[int] = Field(default_factory=list, description="All positions for domain")
    
    # SERP features
    serp_features: SerpFeatures = Field(default_factory=SerpFeatures, description="SERP features present")
    
    # Competitor data (top 10)
    competitor_urls: List[str] = Field(default_factory=list, description="Top 10 competitor URLs")
    
    # Search metadata
    total_results: Optional[int] = Field(None, description="Total search results")
    credits_used: int = Field(default=1, description="API credits consumed")
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    @property
    def is_ranking(self) -> bool:
        """Check if keyword is ranking."""
        return self.position is not None
    
    @property
    def is_top_10(self) -> bool:
        """Check if ranking in top 10."""
        return self.position is not None and self.position <= 10
    
    @property
    def is_page_one(self) -> bool:
        """Check if ranking on page 1."""
        return self.position is not None and self.position <= 10


class QuotaInfo(BaseModel):
    """API quota and usage information."""
    
    total_credits: Optional[int] = Field(None, description="Total monthly credits")
    used_credits: int = Field(default=0, description="Credits used this period")
    remaining_credits: Optional[int] = Field(None, description="Credits remaining")
    
    # Usage tracking
    daily_usage: Dict[str, int] = Field(default_factory=dict, description="Daily usage history")
    last_reset: Optional[datetime] = Field(None, description="Last quota reset")
    
    model_config = ConfigDict(validate_assignment=True)
    
    @property
    def usage_percentage(self) -> Optional[float]:
        """Calculate usage percentage."""
        if self.total_credits is None:
            return None
        return (self.used_credits / self.total_credits) * 100
    
    @property
    def is_quota_exceeded(self) -> bool:
        """Check if quota is exceeded."""
        if self.total_credits is None:
            return False
        return self.used_credits >= self.total_credits
    
    @property
    def is_quota_warning(self, threshold: float = 0.8) -> bool:
        """Check if approaching quota limit."""
        usage_pct = self.usage_percentage
        return usage_pct is not None and usage_pct >= (threshold * 100)
"""API Key Authentication for HTTP Client

Provides API key authentication methods for various services
including header-based, query parameter-based, and custom authentication.
"""

from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
from enum import Enum
import httpx
import structlog

logger = structlog.get_logger(__name__)


class ApiKeyLocation(str, Enum):
    """Location where API key should be sent."""
    HEADER = "header"
    QUERY = "query"
    COOKIE = "cookie"
    BODY = "body"


@dataclass
class ApiKeyConfig:
    """Configuration for API key authentication."""
    
    api_key: str
    location: ApiKeyLocation = ApiKeyLocation.HEADER
    key_name: str = "X-API-Key"
    prefix: Optional[str] = None  # e.g., "Bearer", "Token"
    
    def __post_init__(self):
        """Validate configuration."""
        if not self.api_key:
            raise ValueError("api_key cannot be empty")
        if not self.key_name:
            raise ValueError("key_name cannot be empty")


class ApiKeyAuth(httpx.Auth):
    """API key authentication for httpx client.
    
    Supports multiple API key formats:
    - Header-based: Authorization, X-API-Key, etc.
    - Query parameter-based: api_key, key, etc.
    - Cookie-based: session tokens, etc.
    - Body-based: for form submissions
    """
    
    def __init__(self, config: ApiKeyConfig):
        """Initialize API key authentication.
        
        Args:
            config: API key configuration
        """
        self.config = config
        
        logger.debug(
            "API key auth initialized",
            location=config.location.value,
            key_name=config.key_name,
            has_prefix=bool(config.prefix)
        )
    
    def auth_flow(self, request: httpx.Request):
        """Apply API key authentication to request.
        
        Args:
            request: HTTP request to authenticate
            
        Yields:
            Modified request with authentication
        """
        # Format API key value
        api_key_value = self.config.api_key
        if self.config.prefix:
            api_key_value = f"{self.config.prefix} {api_key_value}"
        
        # Apply based on location
        if self.config.location == ApiKeyLocation.HEADER:
            request.headers[self.config.key_name] = api_key_value
            
        elif self.config.location == ApiKeyLocation.QUERY:
            # Parse existing query parameters
            from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
            
            parsed_url = urlparse(str(request.url))
            query_params = parse_qs(parsed_url.query, keep_blank_values=True)
            
            # Add API key parameter
            query_params[self.config.key_name] = [self.config.api_key]
            
            # Reconstruct URL
            new_query = urlencode(query_params, doseq=True)
            new_parsed = parsed_url._replace(query=new_query)
            new_url = urlunparse(new_parsed)
            
            request.url = httpx.URL(new_url)
            
        elif self.config.location == ApiKeyLocation.COOKIE:
            # Add to cookies
            if not hasattr(request, 'cookies') or request.cookies is None:
                request.cookies = {}
            request.cookies[self.config.key_name] = self.config.api_key
            
        elif self.config.location == ApiKeyLocation.BODY:
            # Add to form body (only for POST/PUT/PATCH with form data)
            content_type = request.headers.get("content-type", "")
            
            if "application/x-www-form-urlencoded" in content_type:
                # Parse existing form data
                from urllib.parse import parse_qs, urlencode
                
                body_str = request.content.decode() if request.content else ""
                form_data = parse_qs(body_str, keep_blank_values=True)
                
                # Add API key
                form_data[self.config.key_name] = [self.config.api_key]
                
                # Update request body
                new_body = urlencode(form_data, doseq=True)
                request.content = new_body.encode()
                
            elif "multipart/form-data" in content_type:
                logger.warning(
                    "API key in multipart form body not supported",
                    content_type=content_type
                )
        
        yield request


# Factory functions for common API key services

def create_bearer_token_auth(token: str) -> ApiKeyAuth:
    """Create Bearer token authentication.
    
    Args:
        token: Bearer token
        
    Returns:
        Configured ApiKeyAuth for Bearer tokens
    """
    config = ApiKeyConfig(
        api_key=token,
        location=ApiKeyLocation.HEADER,
        key_name="Authorization",
        prefix="Bearer"
    )
    return ApiKeyAuth(config)


def create_api_key_header_auth(api_key: str, header_name: str = "X-API-Key") -> ApiKeyAuth:
    """Create header-based API key authentication.
    
    Args:
        api_key: API key value
        header_name: Header name for the API key
        
    Returns:
        Configured ApiKeyAuth for header-based authentication
    """
    config = ApiKeyConfig(
        api_key=api_key,
        location=ApiKeyLocation.HEADER,
        key_name=header_name
    )
    return ApiKeyAuth(config)


def create_query_param_auth(api_key: str, param_name: str = "api_key") -> ApiKeyAuth:
    """Create query parameter-based API key authentication.
    
    Args:
        api_key: API key value
        param_name: Query parameter name for the API key
        
    Returns:
        Configured ApiKeyAuth for query parameter authentication
    """
    config = ApiKeyConfig(
        api_key=api_key,
        location=ApiKeyLocation.QUERY,
        key_name=param_name
    )
    return ApiKeyAuth(config)


# Service-specific authentication factories

def create_google_api_auth(api_key: str) -> ApiKeyAuth:
    """Create authentication for Google APIs.
    
    Args:
        api_key: Google API key
        
    Returns:
        Configured GoogleAPI authentication
    """
    return create_query_param_auth(api_key, "key")


def create_serpapi_auth(api_key: str) -> ApiKeyAuth:
    """Create authentication for SerpAPI.
    
    Args:
        api_key: SerpAPI key
        
    Returns:
        Configured SerpAPI authentication
    """
    return create_query_param_auth(api_key, "api_key")
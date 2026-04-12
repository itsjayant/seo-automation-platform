"""Authentication helpers for HTTP client integrations."""

from .api_key import (
    ApiKeyAuth, ApiKeyConfig, ApiKeyLocation,
    create_bearer_token_auth, create_api_key_header_auth,
    create_query_param_auth, create_google_api_auth, create_serpapi_auth
)
from .oauth import (
    OAuth2Client, OAuth2Config, OAuth2Token, OAuth2Error,
    create_google_oauth_config, create_google_search_console_oauth,
    create_google_analytics_oauth
)

__all__ = [
    # API Key Auth
    "ApiKeyAuth",
    "ApiKeyConfig", 
    "ApiKeyLocation",
    "create_bearer_token_auth",
    "create_api_key_header_auth",
    "create_query_param_auth",
    "create_google_api_auth",
    "create_serpapi_auth",
    
    # OAuth2
    "OAuth2Client", 
    "OAuth2Config",
    "OAuth2Token",
    "OAuth2Error",
    "create_google_oauth_config",
    "create_google_search_console_oauth",
    "create_google_analytics_oauth"
]
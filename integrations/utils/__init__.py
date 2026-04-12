"""Integration utilities for external API management.

Provides rate limiting, circuit breaking, HTTP client with retry policies,
and reliability patterns for GSC, GA4, SerpAPI and other external services.
"""

from .rate_limiter import RateLimiter, RateLimitConfig, RateLimitExceededError
from .circuit_breaker import CircuitBreaker, CircuitBreakerState, CircuitBreakerError
from .backoff import ExponentialBackoff, BackoffConfig
from .http_client import (
    HttpClient, HttpClientConfig, HttpRequest, HttpResponse,
    RetryConfig, TimeoutConfig, ConnectionConfig, HttpMethod,
    create_api_client, create_web_scraper_client
)
from .interceptors import (
    InterceptorChain, RequestInterceptor, ResponseInterceptor, ErrorInterceptor,
    LoggingInterceptor, MetricsInterceptor, TracingInterceptor,
    AuthenticationInterceptor, CachingInterceptor
)
from .user_agents import (
    UserAgentManager, UserAgentType, UserAgentInfo,
    create_api_user_agent_manager, create_scraper_user_agent_manager,
    create_browser_user_agent_manager
)
from .auth import (
    ApiKeyAuth, OAuth2Client, OAuth2Config, OAuth2Token,
    create_bearer_token_auth, create_api_key_header_auth,
    create_query_param_auth, create_google_api_auth, create_serpapi_auth,
    create_google_oauth_config, create_google_search_console_oauth,
    create_google_analytics_oauth
)

__all__ = [
    # Rate limiting
    "RateLimiter",
    "RateLimitConfig", 
    "RateLimitExceededError",
    
    # Circuit breaker
    "CircuitBreaker", 
    "CircuitBreakerState",
    "CircuitBreakerError",
    
    # Backoff
    "ExponentialBackoff",
    "BackoffConfig",
    
    # HTTP client
    "HttpClient",
    "HttpClientConfig", 
    "HttpRequest",
    "HttpResponse",
    "RetryConfig",
    "TimeoutConfig",
    "ConnectionConfig",
    "HttpMethod",
    "create_api_client",
    "create_web_scraper_client",
    
    # Interceptors
    "InterceptorChain",
    "RequestInterceptor",
    "ResponseInterceptor", 
    "ErrorInterceptor",
    "LoggingInterceptor",
    "MetricsInterceptor",
    "TracingInterceptor",
    "AuthenticationInterceptor",
    "CachingInterceptor",
    
    # User agents
    "UserAgentManager",
    "UserAgentType",
    "UserAgentInfo", 
    "create_api_user_agent_manager",
    "create_scraper_user_agent_manager",
    "create_browser_user_agent_manager",
    
    # Authentication
    "ApiKeyAuth",
    "OAuth2Client",
    "OAuth2Config",
    "OAuth2Token",
    "create_bearer_token_auth",
    "create_api_key_header_auth", 
    "create_query_param_auth",
    "create_google_api_auth",
    "create_serpapi_auth",
    "create_google_oauth_config",
    "create_google_search_console_oauth",
    "create_google_analytics_oauth"
]
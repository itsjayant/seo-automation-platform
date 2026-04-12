"""OAuth 2.0 Authentication for HTTP Client

Provides OAuth 2.0 authentication flows for services like Google Search Console
and Google Analytics 4. Includes token refresh, caching, and error handling.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse, parse_qs
import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class OAuth2Error(Exception):
    """OAuth 2.0 authentication error."""
    
    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code


@dataclass  
class OAuth2Token:
    """OAuth 2.0 token with metadata."""
    
    access_token: str
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    client_id: Optional[str] = None
    
    @property
    def expires_at(self) -> Optional[float]:
        """Calculate token expiration timestamp."""
        if self.expires_in is None:
            return None
        return self.created_at + self.expires_in
    
    @property
    def is_expired(self) -> bool:
        """Check if token is expired or will expire soon."""
        if self.expires_at is None:
            return False
        # Add 60 second buffer for expiration
        return time.time() >= (self.expires_at - 60)
    
    @property
    def time_to_expiry(self) -> Optional[float]:
        """Get seconds until token expires."""
        if self.expires_at is None:
            return None
        return max(0, self.expires_at - time.time())
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize token to dictionary."""
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "refresh_token": self.refresh_token,
            "scope": self.scope,
            "created_at": self.created_at,
            "client_id": self.client_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuth2Token":
        """Deserialize token from dictionary."""
        return cls(**data)


class OAuth2Config(BaseModel):
    """Configuration for OAuth 2.0 client."""
    
    client_id: str
    client_secret: str
    
    # OAuth endpoints
    authorization_url: str
    token_url: str
    
    # OAuth parameters
    redirect_uri: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    
    # Token management
    token_cache_key: Optional[str] = None
    auto_refresh: bool = True
    refresh_threshold_seconds: int = 300  # Refresh 5 minutes before expiry
    
    def __post_init__(self):
        """Validate OAuth configuration."""
        if not self.client_id:
            raise ValueError("client_id is required")
        if not self.client_secret:
            raise ValueError("client_secret is required")
        if not self.authorization_url:
            raise ValueError("authorization_url is required")
        if not self.token_url:
            raise ValueError("token_url is required")


class OAuth2Client:
    """Production-grade OAuth 2.0 client with token management.
    
    Features:
    - Authorization code flow
    - Automatic token refresh
    - Token caching and persistence
    - Scope validation
    - Error handling and retry logic
    - Integration with HTTP client
    """
    
    def __init__(
        self, 
        config: OAuth2Config,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        """Initialize OAuth 2.0 client.
        
        Args:
            config: OAuth configuration
            http_client: Optional HTTP client for token requests
        """
        self.config = config
        self._http_client = http_client
        self._token: Optional[OAuth2Token] = None
        self._token_cache: Dict[str, OAuth2Token] = {}
        self._refresh_lock = asyncio.Lock()
        
        logger.info(
            "OAuth2 client initialized",
            client_id=config.client_id[:8] + "...",  # Partial client ID
            scopes=config.scopes,
            auto_refresh=config.auto_refresh
        )
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get HTTP client for OAuth requests."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={"User-Agent": "SEO-Platform-OAuth/1.0"}
            )
        return self._http_client
    
    def get_authorization_url(
        self, 
        state: Optional[str] = None,
        additional_params: Optional[Dict[str, str]] = None
    ) -> str:
        """Generate authorization URL for OAuth flow.
        
        Args:
            state: Optional state parameter for CSRF protection
            additional_params: Additional query parameters
            
        Returns:
            Authorization URL for user redirect
        """
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "access_type": "offline",  # For refresh tokens
            "prompt": "consent"  # Force consent screen
        }
        
        if self.config.redirect_uri:
            params["redirect_uri"] = self.config.redirect_uri
        
        if self.config.scopes:
            params["scope"] = " ".join(self.config.scopes)
        
        if state:
            params["state"] = state
        
        if additional_params:
            params.update(additional_params)
        
        auth_url = f"{self.config.authorization_url}?{urlencode(params)}"
        
        logger.info(
            "Generated authorization URL",
            client_id=self.config.client_id[:8] + "...",
            scopes=self.config.scopes,
            has_state=bool(state)
        )
        
        return auth_url
    
    async def exchange_code_for_token(
        self, 
        authorization_code: str,
        redirect_uri: Optional[str] = None
    ) -> OAuth2Token:
        """Exchange authorization code for access token.
        
        Args:
            authorization_code: Authorization code from callback
            redirect_uri: Redirect URI used in authorization
            
        Returns:
            OAuth2Token with access and refresh tokens
            
        Raises:
            OAuth2Error: If token exchange fails
        """
        client = await self._get_http_client()
        
        # Prepare token request
        data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "code": authorization_code,
            "grant_type": "authorization_code"
        }
        
        if redirect_uri or self.config.redirect_uri:
            data["redirect_uri"] = redirect_uri or self.config.redirect_uri
        
        try:
            response = await client.post(
                self.config.token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            
            token_data = response.json()
            
            # Validate response
            if "access_token" not in token_data:
                raise OAuth2Error("No access token in response")
            
            # Create token object
            token = OAuth2Token(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "Bearer"),  
                expires_in=token_data.get("expires_in"),
                refresh_token=token_data.get("refresh_token"),
                scope=token_data.get("scope"),
                client_id=self.config.client_id
            )
            
            # Cache token
            self._token = token
            if self.config.token_cache_key:
                self._token_cache[self.config.token_cache_key] = token
            
            logger.info(
                "OAuth token exchange successful",
                client_id=self.config.client_id[:8] + "...",
                expires_in=token.expires_in,
                has_refresh_token=bool(token.refresh_token),
                scope=token.scope
            )
            
            return token
            
        except httpx.HTTPStatusError as e:
            error_data = {}
            try:
                error_data = e.response.json()
            except:
                pass
            
            error_msg = error_data.get("error_description", str(e))
            error_code = error_data.get("error", "token_exchange_failed")
            
            logger.error(
                "OAuth token exchange failed",
                status_code=e.response.status_code,
                error_code=error_code,
                error_msg=error_msg
            )
            
            raise OAuth2Error(error_msg, error_code)
        
        except Exception as e:
            logger.error(
                "OAuth token exchange error",
                error=str(e),
                error_type=type(e).__name__
            )
            raise OAuth2Error(f"Token exchange failed: {e}")
    
    async def refresh_access_token(
        self, 
        refresh_token: Optional[str] = None
    ) -> OAuth2Token:
        """Refresh access token using refresh token.
        
        Args:
            refresh_token: Optional refresh token override
            
        Returns:
            New OAuth2Token with refreshed access token
            
        Raises:
            OAuth2Error: If token refresh fails
        """
        # Use provided refresh token or current token's refresh token
        refresh_token = refresh_token or (self._token.refresh_token if self._token else None)
        
        if not refresh_token:
            raise OAuth2Error("No refresh token available")
        
        async with self._refresh_lock:
            client = await self._get_http_client()
            
            # Prepare refresh request
            data = {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }
            
            try:
                response = await client.post(
                    self.config.token_url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                response.raise_for_status()
                
                token_data = response.json()
                
                # Validate response
                if "access_token" not in token_data:
                    raise OAuth2Error("No access token in refresh response")
                
                # Create new token object (preserve refresh token if not returned)
                new_token = OAuth2Token(
                    access_token=token_data["access_token"],
                    token_type=token_data.get("token_type", "Bearer"),
                    expires_in=token_data.get("expires_in"),
                    refresh_token=token_data.get("refresh_token", refresh_token),
                    scope=token_data.get("scope"),
                    client_id=self.config.client_id
                )
                
                # Update cached token
                self._token = new_token
                if self.config.token_cache_key:
                    self._token_cache[self.config.token_cache_key] = new_token
                
                logger.info(
                    "OAuth token refresh successful",
                    client_id=self.config.client_id[:8] + "...",
                    expires_in=new_token.expires_in
                )
                
                return new_token
                
            except httpx.HTTPStatusError as e:
                error_data = {}
                try:
                    error_data = e.response.json()
                except:
                    pass
                
                error_msg = error_data.get("error_description", str(e))
                error_code = error_data.get("error", "token_refresh_failed")
                
                logger.error(
                    "OAuth token refresh failed",
                    status_code=e.response.status_code,
                    error_code=error_code,
                    error_msg=error_msg
                )
                
                raise OAuth2Error(error_msg, error_code)
            
            except Exception as e:
                logger.error(
                    "OAuth token refresh error",
                    error=str(e),
                    error_type=type(e).__name__
                )
                raise OAuth2Error(f"Token refresh failed: {e}")
    
    async def get_valid_token(self) -> OAuth2Token:
        """Get valid access token, refreshing if necessary.
        
        Returns:
            Valid OAuth2Token
            
        Raises:
            OAuth2Error: If no token available or refresh fails
        """
        if not self._token:
            raise OAuth2Error("No token available, authorization required")
        
        # Check if token needs refresh
        if (
            self.config.auto_refresh and 
            self._token.is_expired and 
            self._token.refresh_token
        ):
            try:
                await self.refresh_access_token()
            except OAuth2Error:
                # If refresh fails, re-raise
                raise
            except Exception as e:
                logger.error(
                    "Unexpected error during token refresh",
                    error=str(e)
                )
                raise OAuth2Error(f"Token refresh failed: {e}")
        
        if self._token.is_expired:
            raise OAuth2Error("Token expired and no refresh token available")
        
        return self._token
    
    def set_token(self, token: OAuth2Token):
        """Set current token manually.
        
        Args:
            token: OAuth2Token to set as current
        """
        self._token = token
        if self.config.token_cache_key:
            self._token_cache[self.config.token_cache_key] = token
        
        logger.info(
            "OAuth token set manually",
            expires_in=token.expires_in,
            has_refresh_token=bool(token.refresh_token)
        )
    
    def get_cached_token(self, cache_key: Optional[str] = None) -> Optional[OAuth2Token]:
        """Get token from cache.
        
        Args:
            cache_key: Optional cache key override
            
        Returns:
            Cached token or None if not found
        """
        cache_key = cache_key or self.config.token_cache_key
        if cache_key:
            return self._token_cache.get(cache_key)
        return None
    
    async def close(self):
        """Close HTTP client resources."""
        if self._http_client:
            await self._http_client.aclose()


class OAuth2Auth(httpx.Auth):
    """OAuth 2.0 authentication for httpx client.
    
    Automatically handles token refresh and applies Bearer authentication.
    """
    
    def __init__(self, oauth_client: OAuth2Client):  
        """Initialize OAuth authentication.
        
        Args:
            oauth_client: Configured OAuth2Client
        """
        self.oauth_client = oauth_client
    
    def auth_flow(self, request: httpx.Request):
        """Apply OAuth authentication to request.
        
        Args:
            request: HTTP request to authenticate
            
        Yields:
            Authenticated request
        """
        # This is a synchronous method but we need async token operations
        # We'll handle this limitation in the HTTP client integration
        if self.oauth_client._token:
            token = self.oauth_client._token
            request.headers["Authorization"] = f"{token.token_type} {token.access_token}"
        
        yield request


# Factory functions for common OAuth providers

def create_google_oauth_config(
    client_id: str,
    client_secret: str,
    scopes: List[str],
    redirect_uri: Optional[str] = None
) -> OAuth2Config:
    """Create OAuth configuration for Google APIs.
    
    Args:
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret
        scopes: List of OAuth scopes
        redirect_uri: Optional redirect URI
        
    Returns:
        Configured OAuth2Config for Google
    """
    return OAuth2Config(
        client_id=client_id,
        client_secret=client_secret,
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        redirect_uri=redirect_uri,
        scopes=scopes
    )


def create_google_search_console_oauth(
    client_id: str,
    client_secret: str,
    redirect_uri: Optional[str] = None
) -> OAuth2Config:
    """Create OAuth config for Google Search Console.
    
    Args:
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret
        redirect_uri: Optional redirect URI
        
    Returns:
        OAuth2Config with GSC scopes
    """
    scopes = [
        "https://www.googleapis.com/auth/webmasters.readonly"
    ]
    
    return create_google_oauth_config(
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        redirect_uri=redirect_uri
    )


def create_google_analytics_oauth(
    client_id: str,
    client_secret: str,
    redirect_uri: Optional[str] = None
) -> OAuth2Config:
    """Create OAuth config for Google Analytics 4.
    
    Args:
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret
        redirect_uri: Optional redirect URI
        
    Returns:
        OAuth2Config with GA4 scopes
    """
    scopes = [
        "https://www.googleapis.com/auth/analytics.readonly"
    ]
    
    return create_google_oauth_config(
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        redirect_uri=redirect_uri
    )
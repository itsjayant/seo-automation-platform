"""
Tests for authentication components.

Tests API key authentication, OAuth 2.0 client, and integration
with HTTP client for various authentication scenarios.
"""

import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch
import pytest
import httpx

from integrations.utils.auth import (
    ApiKeyAuth, ApiKeyConfig, ApiKeyLocation,
    OAuth2Client, OAuth2Config, OAuth2Token, OAuth2Error,
    create_bearer_token_auth, create_api_key_header_auth,
    create_query_param_auth, create_google_api_auth, create_serpapi_auth,
    create_google_oauth_config, create_google_search_console_oauth,
    create_google_analytics_oauth
)


class TestApiKeyAuth:
    """Test API key authentication for various scenarios."""
    
    def test_api_key_config_validation(self):
        """Test API key configuration validation."""
        # Valid config
        config = ApiKeyConfig(
            api_key="test-key",
            location=ApiKeyLocation.HEADER,
            key_name="X-API-Key"
        )
        assert config.api_key == "test-key"
        
        # Empty API key should raise error
        with pytest.raises(ValueError, match="api_key cannot be empty"):
            ApiKeyConfig(api_key="", key_name="X-API-Key")
        
        # Empty key name should raise error
        with pytest.raises(ValueError, match="key_name cannot be empty"):
            ApiKeyConfig(api_key="test-key", key_name="")
    
    def test_header_based_auth(self):
        """Test header-based API key authentication."""
        config = ApiKeyConfig(
            api_key="secret-key",
            location=ApiKeyLocation.HEADER,
            key_name="X-API-Key"
        )
        auth = ApiKeyAuth(config)
        
        # Create test request
        request = httpx.Request("GET", "https://api.example.com/test")
        
        # Apply authentication
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        assert authenticated_request.headers["X-API-Key"] == "secret-key"
    
    def test_header_with_prefix_auth(self):
        """Test header-based authentication with prefix."""
        config = ApiKeyConfig(
            api_key="secret-token",
            location=ApiKeyLocation.HEADER,
            key_name="Authorization",
            prefix="Bearer"
        )
        auth = ApiKeyAuth(config)
        
        request = httpx.Request("GET", "https://api.example.com/test")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        assert authenticated_request.headers["Authorization"] == "Bearer secret-token"
    
    def test_query_parameter_auth(self):
        """Test query parameter-based API key authentication."""
        config = ApiKeyConfig(
            api_key="api-key-123",
            location=ApiKeyLocation.QUERY,
            key_name="api_key"
        )
        auth = ApiKeyAuth(config)
        
        request = httpx.Request("GET", "https://api.example.com/test?existing=value")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        # Check that API key was added to query parameters
        url_str = str(authenticated_request.url)
        assert "api_key=api-key-123" in url_str
        assert "existing=value" in url_str  # Existing params preserved
    
    def test_cookie_based_auth(self):
        """Test cookie-based API key authentication."""
        config = ApiKeyConfig(
            api_key="session-token",
            location=ApiKeyLocation.COOKIE,
            key_name="session_id"
        )
        auth = ApiKeyAuth(config)
        
        request = httpx.Request("GET", "https://api.example.com/test")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        assert authenticated_request.cookies["session_id"] == "session-token"


class TestApiKeyFactories:
    """Test API key authentication factory functions."""
    
    def test_bearer_token_factory(self):
        """Test Bearer token authentication factory."""
        auth = create_bearer_token_auth("my-bearer-token")
        
        request = httpx.Request("GET", "https://api.example.com/test")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        assert authenticated_request.headers["Authorization"] == "Bearer my-bearer-token"
    
    def test_api_key_header_factory(self):
        """Test API key header authentication factory."""
        auth = create_api_key_header_auth("my-api-key", "X-Custom-Key")
        
        request = httpx.Request("GET", "https://api.example.com/test")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        assert authenticated_request.headers["X-Custom-Key"] == "my-api-key"
    
    def test_query_param_factory(self):
        """Test query parameter authentication factory."""
        auth = create_query_param_auth("param-value", "custom_param")
        
        request = httpx.Request("GET", "https://api.example.com/test")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        url_str = str(authenticated_request.url)
        assert "custom_param=param-value" in url_str
    
    def test_google_api_factory(self):
        """Test Google API authentication factory."""
        auth = create_google_api_auth("google-api-key")
        
        request = httpx.Request("GET", "https://googleapis.com/test")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        url_str = str(authenticated_request.url)
        assert "key=google-api-key" in url_str
    
    def test_serpapi_factory(self):
        """Test SerpAPI authentication factory."""
        auth = create_serpapi_auth("serpapi-key")
        
        request = httpx.Request("GET", "https://serpapi.com/search")
        auth_flow = auth.auth_flow(request)
        authenticated_request = next(auth_flow)
        
        url_str = str(authenticated_request.url)
        assert "api_key=serpapi-key" in url_str


class TestOAuth2Token:
    """Test OAuth 2.0 token functionality."""
    
    def test_token_creation(self):
        """Test OAuth token creation and properties."""
        token = OAuth2Token(
            access_token="access-123",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="refresh-456",
            scope="read write"
        )
        
        assert token.access_token == "access-123"
        assert token.token_type == "Bearer"
        assert token.expires_in == 3600
        assert token.refresh_token == "refresh-456"
        assert token.scope == "read write"
        assert not token.is_expired  # Just created
        assert token.time_to_expiry > 3500  # Should be close to 3600
    
    def test_token_expiration(self):
        """Test token expiration detection."""
        # Expired token
        expired_token = OAuth2Token(
            access_token="access-123",
            expires_in=3600,
            created_at=1000.0  # Long ago
        )
        
        with patch('time.time', return_value=5000.0):  # Much later
            assert expired_token.is_expired
            assert expired_token.time_to_expiry == 0
    
    def test_token_serialization(self):
        """Test token serialization and deserialization."""
        original_token = OAuth2Token(
            access_token="access-123",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="refresh-456",
            scope="read write",
            client_id="client-id"
        )
        
        # Serialize
        token_dict = original_token.to_dict()
        
        # Deserialize  
        restored_token = OAuth2Token.from_dict(token_dict)
        
        assert restored_token.access_token == original_token.access_token
        assert restored_token.token_type == original_token.token_type
        assert restored_token.expires_in == original_token.expires_in
        assert restored_token.refresh_token == original_token.refresh_token
        assert restored_token.scope == original_token.scope
        assert restored_token.client_id == original_token.client_id


class TestOAuth2Config:
    """Test OAuth 2.0 configuration validation."""
    
    def test_valid_config(self):
        """Test valid OAuth configuration."""
        config = OAuth2Config(
            client_id="client-123",
            client_secret="secret-456", 
            authorization_url="https://auth.example.com/oauth/authorize",
            token_url="https://auth.example.com/oauth/token",
            scopes=["read", "write"]
        )
        
        assert config.client_id == "client-123"
        assert config.client_secret == "secret-456"
        assert config.scopes == ["read", "write"]
    
    def test_config_validation(self):
        """Test OAuth configuration validation."""
        # Missing client_id
        with pytest.raises(ValueError, match="client_id is required"):
            OAuth2Config(
                client_id="",
                client_secret="secret",
                authorization_url="https://auth.example.com/authorize",
                token_url="https://auth.example.com/token"
            )
        
        # Missing client_secret
        with pytest.raises(ValueError, match="client_secret is required"):
            OAuth2Config(
                client_id="client",
                client_secret="",
                authorization_url="https://auth.example.com/authorize", 
                token_url="https://auth.example.com/token"
            )


class TestOAuth2Client:
    """Test OAuth 2.0 client functionality."""
    
    @pytest.fixture
    def oauth_config(self):
        """Create OAuth config for testing."""
        return OAuth2Config(
            client_id="test-client-id",
            client_secret="test-client-secret",
            authorization_url="https://auth.example.com/oauth/authorize",
            token_url="https://auth.example.com/oauth/token",
            redirect_uri="https://app.example.com/callback",
            scopes=["read", "write"]
        )
    
    @pytest.fixture
    async def oauth_client(self, oauth_config):
        """Create OAuth client for testing."""
        client = OAuth2Client(oauth_config)
        yield client
        await client.close()
    
    def test_authorization_url_generation(self, oauth_client):
        """Test authorization URL generation."""
        auth_url = oauth_client.get_authorization_url(state="csrf-token")
        
        assert "https://auth.example.com/oauth/authorize" in auth_url
        assert "client_id=test-client-id" in auth_url
        assert "response_type=code" in auth_url
        assert "state=csrf-token" in auth_url
        assert "scope=read+write" in auth_url
        assert "redirect_uri=https%3A//app.example.com/callback" in auth_url
    
    @pytest.mark.asyncio
    async def test_successful_token_exchange(self, oauth_client):
        """Test successful authorization code to token exchange."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "access_token": "access-token-123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh-token-456",
            "scope": "read write"
        }
        
        with patch('httpx.AsyncClient.post', return_value=mock_response) as mock_post:
            token = await oauth_client.exchange_code_for_token("auth-code-123")
            
            assert token.access_token == "access-token-123"
            assert token.token_type == "Bearer"
            assert token.expires_in == 3600
            assert token.refresh_token == "refresh-token-456"
            assert token.scope == "read write"
            
            # Verify correct API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://auth.example.com/oauth/token"
            assert "code=auth-code-123" in str(call_args[1]["data"])
    
    @pytest.mark.asyncio
    async def test_failed_token_exchange(self, oauth_client):
        """Test failed token exchange handling.""" 
        # Mock HTTP error response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "The authorization code is invalid"
        }
        
        http_error = httpx.HTTPStatusError(
            "Bad Request",
            request=Mock(),
            response=mock_response
        )
        
        with patch('httpx.AsyncClient.post', side_effect=http_error):
            with pytest.raises(OAuth2Error) as exc_info:
                await oauth_client.exchange_code_for_token("invalid-code")
            
            assert exc_info.value.error_code == "invalid_grant"
            assert "authorization code is invalid" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_successful_token_refresh(self, oauth_client):
        """Test successful token refresh."""
        # Set up existing token
        existing_token = OAuth2Token(
            access_token="old-access-token",
            refresh_token="refresh-token-456",
            expires_in=3600
        )
        oauth_client.set_token(existing_token)
        
        # Mock refresh response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600
        }
        
        with patch('httpx.AsyncClient.post', return_value=mock_response) as mock_post:
            new_token = await oauth_client.refresh_access_token()
            
            assert new_token.access_token == "new-access-token"
            assert new_token.refresh_token == "refresh-token-456"  # Preserved
            
            # Verify correct API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "refresh_token=refresh-token-456" in str(call_args[1]["data"])
    
    @pytest.mark.asyncio
    async def test_get_valid_token_with_refresh(self, oauth_client):
        """Test getting valid token with automatic refresh."""
        # Set up expired token with refresh token
        expired_token = OAuth2Token(
            access_token="expired-access-token",
            refresh_token="refresh-token-456",
            expires_in=3600,
            created_at=1000.0  # Long ago
        )
        oauth_client.set_token(expired_token)
        
        # Mock refresh response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "access_token": "refreshed-access-token",
            "token_type": "Bearer",
            "expires_in": 3600
        }
        
        with patch('httpx.AsyncClient.post', return_value=mock_response):
            with patch('time.time', return_value=5000.0):  # Much later
                valid_token = await oauth_client.get_valid_token()
                
                assert valid_token.access_token == "refreshed-access-token"
                assert not valid_token.is_expired


class TestOAuth2Factories:
    """Test OAuth 2.0 factory functions."""
    
    def test_google_oauth_config_factory(self):
        """Test Google OAuth configuration factory."""
        config = create_google_oauth_config(
            client_id="google-client-id",
            client_secret="google-client-secret",
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
            redirect_uri="https://app.example.com/callback"
        )
        
        assert config.client_id == "google-client-id"
        assert config.client_secret == "google-client-secret"
        assert config.authorization_url == "https://accounts.google.com/o/oauth2/v2/auth"
        assert config.token_url == "https://oauth2.googleapis.com/token"
        assert config.scopes == ["https://www.googleapis.com/auth/webmasters.readonly"]
        assert config.redirect_uri == "https://app.example.com/callback"
    
    def test_google_search_console_oauth_factory(self):
        """Test Google Search Console OAuth configuration factory."""
        config = create_google_search_console_oauth(
            client_id="gsc-client-id",
            client_secret="gsc-client-secret"
        )
        
        assert config.client_id == "gsc-client-id"
        assert "webmasters.readonly" in config.scopes[0]
    
    def test_google_analytics_oauth_factory(self):
        """Test Google Analytics OAuth configuration factory."""
        config = create_google_analytics_oauth(
            client_id="ga4-client-id", 
            client_secret="ga4-client-secret"
        )
        
        assert config.client_id == "ga4-client-id"
        assert "analytics.readonly" in config.scopes[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
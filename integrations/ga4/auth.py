"""
Google Service Account Authentication for GA4 API.

This module provides OAuth 2.0 service account authentication for
Google Analytics 4 Data API using JWT token exchange.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

import httpx
import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from integrations.utils.auth.oauth import OAuth2Token, OAuth2Error
from .models import ServiceAccountConfig

logger = structlog.get_logger(__name__)


class ServiceAccountAuthError(OAuth2Error):
    """Service account authentication specific error."""
    pass


class GA4Auth:
    """
    Google Service Account authentication for GA4 Data API.
    
    Uses the Google client library for robust OAuth 2.0 flow implementation.
    Handles token refresh and manages authentication state.
    """
    
    # GA4 Data API scopes
    DEFAULT_SCOPES = [
        'https://www.googleapis.com/auth/analytics.readonly'
    ]
    
    def __init__(
        self, 
        config: ServiceAccountConfig,
        scopes: Optional[List[str]] = None
    ):
        self.config = config
        self.scopes = scopes or self.DEFAULT_SCOPES
        self._credentials: Optional[service_account.Credentials] = None
        self._current_token: Optional[OAuth2Token] = None
        
        # Load service account credentials
        self._load_credentials()
    
    def _load_credentials(self) -> None:
        """Load service account credentials from config."""
        try:
            if self.config.json_file_path:
                # Load from JSON file
                self._credentials = service_account.Credentials.from_service_account_file(
                    self.config.json_file_path,
                    scopes=self.scopes
                )
                logger.info("Loaded GA4 credentials from JSON file",
                          file_path=self.config.json_file_path)
            else:
                # Load from individual config fields
                service_account_info = {
                    "type": self.config.type,
                    "project_id": self.config.project_id,
                    "private_key_id": self.config.private_key_id,
                    "private_key": self.config.private_key,
                    "client_email": self.config.client_email,
                    "client_id": self.config.client_id,
                    "auth_uri": self.config.auth_uri,
                    "token_uri": self.config.token_uri,
                    "auth_provider_x509_cert_url": self.config.auth_provider_x509_cert_url,
                    "client_x509_cert_url": self.config.client_x509_cert_url,
                }
                
                self._credentials = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=self.scopes
                )
                logger.info("Loaded GA4 credentials from config fields",
                          client_email=self.config.client_email)
        
        except Exception as e:
            logger.error("Failed to load GA4 service account credentials",
                       error=str(e), error_type=type(e).__name__)
            raise ServiceAccountAuthError(f"Failed to load credentials: {e}")
    
    async def get_access_token(self) -> OAuth2Token:
        """
        Get a valid access token, refreshing if necessary.
        
        Returns:
            OAuth2Token with access token and expiry info
            
        Raises:
            ServiceAccountAuthError: If authentication fails
        """
        try:
            # Check if current token is still valid
            if self._current_token and not self._is_token_expired():
                return self._current_token
            
            # Refresh or get new token
            await self._refresh_token()
            
            if not self._current_token:
                raise ServiceAccountAuthError("Failed to obtain access token")
            
            return self._current_token
        
        except Exception as e:
            logger.error("Failed to get GA4 access token",
                       error=str(e), error_type=type(e).__name__)
            raise ServiceAccountAuthError(f"Token acquisition failed: {e}")
    
    async def _refresh_token(self) -> None:
        """Refresh the access token using service account credentials."""
        try:
            # Use Google's Request class for token refresh
            request = Request()
            
            # Refresh the credentials
            self._credentials.refresh(request)
            
            if not self._credentials.token:
                raise ServiceAccountAuthError("No token received after refresh")
            
            # Create OAuth2Token from refreshed credentials
            expires_at = None
            if self._credentials.expiry:
                expires_at = int(self._credentials.expiry.timestamp())
            
            self._current_token = OAuth2Token(
                access_token=self._credentials.token,
                token_type="Bearer",
                expires_in=3600,  # Default to 1 hour if not specified
                expires_at=expires_at,
                scope=" ".join(self.scopes)
            )
            
            logger.info("Successfully refreshed GA4 access token",
                      expires_at=expires_at)
        
        except Exception as e:
            logger.error("Failed to refresh GA4 access token",
                       error=str(e), error_type=type(e).__name__)
            raise ServiceAccountAuthError(f"Token refresh failed: {e}")
    
    def _is_token_expired(self) -> bool:
        """Check if the current token is expired or will expire soon."""
        if not self._current_token or not self._current_token.expires_at:
            return True
        
        # Consider token expired if it expires within the next 60 seconds
        buffer_seconds = 60
        current_time = int(datetime.utcnow().timestamp())
        return self._current_token.expires_at <= (current_time + buffer_seconds)
    
    def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers for API requests.
        
        Returns:
            Dict with Authorization header
            
        Note:
            This is a synchronous method for convenience.
            Call get_access_token() first to ensure valid token.
        """
        if not self._current_token:
            raise ServiceAccountAuthError("No access token available. Call get_access_token() first.")
        
        return {
            "Authorization": f"Bearer {self._current_token.access_token}"
        }
    
    def get_credentials(self) -> service_account.Credentials:
        """
        Get the underlying service account credentials.
        
        Useful for direct use with Google client libraries.
        
        Returns:
            Google service account credentials
        """
        if not self._credentials:
            raise ServiceAccountAuthError("Credentials not loaded")
        
        return self._credentials
    
    def is_authenticated(self) -> bool:
        """Check if authentication is configured and working."""
        return (
            self._credentials is not None and
            self._current_token is not None and
            not self._is_token_expired()
        )
    
    async def validate_credentials(self) -> bool:
        """
        Validate that credentials work by attempting to get a token.
        
        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            token = await self.get_access_token()
            return token is not None and token.access_token is not None
        except Exception as e:
            logger.warning("GA4 credential validation failed",
                         error=str(e), error_type=type(e).__name__)
            return False
    
    def get_project_id(self) -> Optional[str]:
        """Get the project ID from the service account."""
        if self.config.json_file_path and self._credentials:
            return getattr(self._credentials, 'project_id', None)
        return self.config.project_id
    
    def get_client_email(self) -> Optional[str]:
        """Get the client email from the service account."""
        if self.config.json_file_path and self._credentials:
            return getattr(self._credentials, 'service_account_email', None)
        return self.config.client_email
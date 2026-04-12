"""
Google Service Account Authentication for GSC API.

This module provides OAuth 2.0 service account authentication for
Google Search Console API using JWT token exchange.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlencode

import httpx
import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

from integrations.utils.auth.oauth import OAuth2Token, OAuth2Error
from .models import ServiceAccountConfig

logger = structlog.get_logger(__name__)


class ServiceAccountAuthError(OAuth2Error):
    """Service account authentication specific error."""
    pass


class GSCAuth:
    """
    Google Service Account authentication for Search Console API.
    
    Implements JWT-based OAuth 2.0 flow for service accounts as per:
    https://developers.google.com/identity/protocols/oauth2/service-account
    """
    
    def __init__(
        self, 
        config: ServiceAccountConfig,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.config = config
        self._http_client = http_client
        self._service_account_info: Optional[Dict[str, Any]] = None
        self._current_token: Optional[OAuth2Token] = None
        
        # Load service account info
        self._load_service_account_info()
    
    def _load_service_account_info(self) -> None:
        """Load service account credentials from file or dict."""
        try:
            if self.config.service_account_info:
                self._service_account_info = self.config.service_account_info
            elif self.config.service_account_path:
                path = Path(self.config.service_account_path)
                if not path.exists():
                    raise ServiceAccountAuthError(
                        f"Service account file not found: {path}"
                    )
                
                with open(path, 'r') as f:
                    self._service_account_info = json.load(f)
            else:
                raise ServiceAccountAuthError(
                    "Either service_account_path or service_account_info must be provided"
                )
            
            # Validate required fields
            required_fields = [
                'client_email', 'private_key', 'token_uri', 'client_id'
            ]
            missing_fields = [
                field for field in required_fields 
                if field not in self._service_account_info
            ]
            
            if missing_fields:
                raise ServiceAccountAuthError(
                    f"Missing required fields in service account: {missing_fields}"
                )
                
            logger.info(
                "Loaded service account credentials",
                client_email=self._service_account_info['client_email'],
                client_id=self._service_account_info['client_id']
            )
            
        except json.JSONDecodeError as e:
            raise ServiceAccountAuthError(f"Invalid JSON in service account file: {e}")
        except Exception as e:
            raise ServiceAccountAuthError(f"Failed to load service account: {e}")
    
    def _create_jwt_assertion(self) -> str:
        """
        Create JWT assertion for service account authentication.
        
        Returns:
            Signed JWT token for OAuth 2.0 token exchange
        """
        if not self._service_account_info:
            raise ServiceAccountAuthError("Service account info not loaded")
        
        now = int(time.time())
        expiry = now + 3600  # 1 hour expiry
        
        # JWT header
        header = {
            "alg": "RS256",
            "typ": "JWT"
        }
        
        # JWT payload
        payload = {
            "iss": self._service_account_info["client_email"],  # Issuer
            "sub": self._service_account_info["client_email"],  # Subject  
            "aud": self._service_account_info["token_uri"],     # Audience
            "scope": " ".join(self.config.scopes),            # Requested scopes
            "iat": now,                                       # Issued at
            "exp": expiry                                     # Expires at
        }
        
        try:
            # Encode header and payload
            import base64
            
            def base64url_encode(data: bytes) -> str:
                """Base64 URL-safe encoding without padding."""
                return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')
            
            header_encoded = base64url_encode(json.dumps(header).encode())
            payload_encoded = base64url_encode(json.dumps(payload).encode())
            
            # Create signing string
            signing_input = f"{header_encoded}.{payload_encoded}"
            
            # Load private key
            private_key_pem = self._service_account_info["private_key"]
            private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None
            )
            
            # Sign with RS256
            signature = private_key.sign(
                signing_input.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            # Encode signature
            signature_encoded = base64url_encode(signature)
            
            # Return complete JWT
            jwt_token = f"{signing_input}.{signature_encoded}"
            
            logger.debug(
                "Created JWT assertion",
                iss=payload["iss"],
                exp=datetime.fromtimestamp(expiry).isoformat()
            )
            
            return jwt_token
            
        except Exception as e:
            raise ServiceAccountAuthError(f"Failed to create JWT assertion: {e}")
    
    async def _exchange_jwt_for_token(self, jwt_assertion: str) -> OAuth2Token:
        """
        Exchange JWT assertion for OAuth 2.0 access token.
        
        Args:
            jwt_assertion: Signed JWT token
            
        Returns:
            OAuth 2.0 access token
        """
        if not self._service_account_info:
            raise ServiceAccountAuthError("Service account info not loaded")
        
        token_uri = self._service_account_info["token_uri"]
        
        # Prepare token request
        request_data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt_assertion
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            if self._http_client:
                response = await self._http_client.post(
                    token_uri,
                    data=request_data,
                    headers=headers,
                    timeout=30.0
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        token_uri,
                        data=request_data,
                        headers=headers,
                        timeout=30.0
                    )
            
            if response.status_code != 200:
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    pass
                
                raise ServiceAccountAuthError(
                    f"Token exchange failed: {response.status_code} - "
                    f"{error_data.get('error_description', response.text)}"
                )
            
            token_data = response.json()
            
            # Create OAuth2Token
            token = OAuth2Token(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "Bearer"),
                expires_in=token_data.get("expires_in"),
                scope=token_data.get("scope"),
                client_id=self._service_account_info["client_id"]
            )
            
            logger.info(
                "Successfully obtained access token",
                client_email=self._service_account_info["client_email"],
                expires_in=token.expires_in,
                scopes=token.scope
            )
            
            return token
            
        except httpx.RequestError as e:
            raise ServiceAccountAuthError(f"Token request failed: {e}")
        except Exception as e:
            raise ServiceAccountAuthError(f"Token exchange error: {e}")
    
    async def get_access_token(self, force_refresh: bool = False) -> OAuth2Token:
        """
        Get valid access token, refreshing if necessary.
        
        Args:
            force_refresh: Force token refresh even if current token is valid
            
        Returns:
            Valid OAuth 2.0 access token
        """
        # Check if current token is valid
        if (not force_refresh and self._current_token and 
            not self._current_token.is_expired):
            logger.debug(
                "Using cached access token",
                expires_in=self._current_token.time_to_expiry
            )
            return self._current_token
        
        logger.info(
            "Refreshing access token",
            force_refresh=force_refresh,
            token_expired=self._current_token.is_expired if self._current_token else None
        )
        
        try:
            # Create JWT assertion
            jwt_assertion = self._create_jwt_assertion()
            
            # Exchange for access token
            token = await self._exchange_jwt_for_token(jwt_assertion)
            
            # Cache token
            self._current_token = token
            
            return token
            
        except Exception as e:
            logger.error(
                "Failed to get access token",
                error=str(e),
                client_email=self._service_account_info.get("client_email") 
                if self._service_account_info else None
            )
            raise
    
    async def get_auth_headers(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        Get HTTP headers for authenticated requests.
        
        Args:
            force_refresh: Force token refresh
            
        Returns:
            HTTP headers with Authorization bearer token
        """
        token = await self.get_access_token(force_refresh=force_refresh)
        
        return {
            "Authorization": f"{token.token_type} {token.access_token}",
            "User-Agent": "SEO-Automation-Platform/1.0 GSC-Integration"
        }
    
    def get_client_info(self) -> Dict[str, Any]:
        """Get service account client information."""
        if not self._service_account_info:
            return {}
        
        return {
            "client_email": self._service_account_info.get("client_email"),
            "client_id": self._service_account_info.get("client_id"),
            "project_id": self._service_account_info.get("project_id"),
            "scopes": self.config.scopes
        }
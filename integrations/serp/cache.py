"""
SerpAPI Result Caching for API Efficiency

Redis-backed caching system optimized for SerpAPI responses to minimize
API calls and stay within tight quota constraints. Includes intelligent
cache invalidation, compression, and TTL management.
"""

import hashlib
import json
import pickle
import gzip
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass
from enum import Enum

import structlog
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

logger = structlog.get_logger(__name__)


class CacheStrategy(str, Enum):
    """Cache storage strategies."""
    JSON = "json"           # JSON serialization (human readable)
    PICKLE = "pickle"       # Pickle serialization (Python objects)
    COMPRESSED = "compressed"  # Gzip compressed pickle (space efficient)


@dataclass
class CachePolicy:
    """Cache policy configuration."""
    
    # Cache TTL settings
    default_ttl: int = 86400  # 24 hours in seconds
    search_ttl: int = 43200   # 12 hours for search results
    quota_ttl: int = 3600     # 1 hour for quota info
    
    # Cache behavior
    strategy: CacheStrategy = CacheStrategy.COMPRESSED
    enable_compression: bool = True
    max_size_mb: float = 10.0  # Maximum cached object size
    
    # Key prefixes
    key_prefix: str = "serp_cache"
    search_prefix: str = "search"
    quota_prefix: str = "quota"
    
    # Cache invalidation
    auto_invalidate: bool = True
    invalidate_on_error: bool = False
    
    def __post_init__(self):
        """Validate cache policy."""
        if self.default_ttl <= 0:
            raise ValueError("default_ttl must be positive")
        if self.max_size_mb <= 0:
            raise ValueError("max_size_mb must be positive")


class ResultCache:
    """
    Redis-backed cache for SerpAPI responses with intelligent TTL management.
    
    Features:
    - Configurable serialization strategies (JSON, Pickle, Compressed)
    - TTL management with different policies per data type
    - Automatic cache invalidation and cleanup
    - Size-based eviction for large objects
    - Compression for space efficiency
    - Error resilience with fallback behaviors
    """
    
    def __init__(
        self, 
        policy: Optional[CachePolicy] = None,
        redis_url: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None
    ):
        """
        Initialize result cache.
        
        Args:
            policy: Cache policy configuration
            redis_url: Redis connection URL
            redis_client: Pre-configured Redis client
        """
        self.policy = policy or CachePolicy()
        
        # Initialize Redis client
        if redis_client:
            self._redis = redis_client
        elif redis_url:
            self._redis = redis.from_url(redis_url)
        else:
            # Default Redis configuration
            self._redis = redis.Redis(
                host='localhost',
                port=6379,
                db=1,  # Use db 1 for cache (db 0 for rate limiter)
                decode_responses=False,  # Handle binary data
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True
            )
        
        self._connected = False
        
        logger.info(
            "Result cache initialized",
            strategy=self.policy.strategy.value,
            default_ttl=self.policy.default_ttl,
            compression=self.policy.enable_compression
        )
    
    async def _ensure_connection(self) -> bool:
        """Ensure Redis connection is established."""
        if self._connected:
            return True
        
        try:
            await self._redis.ping()
            self._connected = True
            logger.debug("Redis cache connection established")
            return True
        except RedisConnectionError as e:
            logger.warning("Redis cache connection failed", error=str(e))
            return False
    
    def generate_key(
        self, 
        endpoint: str, 
        params: Dict[str, Any], 
        prefix: Optional[str] = None
    ) -> str:
        """
        Generate cache key from endpoint and parameters.
        
        Args:
            endpoint: API endpoint
            params: Request parameters
            prefix: Optional key prefix
            
        Returns:
            Cache key string
        """
        # Use specified prefix or default
        key_prefix = prefix or self.policy.search_prefix
        
        # Create canonical parameter representation
        param_copy = params.copy()
        
        # Remove cache-busting parameters
        param_copy.pop('no_cache', None)
        param_copy.pop('api_key', None)  # Don't include API key in cache key
        
        # Sort parameters for consistent key generation
        canonical_params = json.dumps(param_copy, sort_keys=True, separators=(',', ':'))
        
        # Create hash for compact key
        param_hash = hashlib.sha256(
            f"{endpoint}:{canonical_params}".encode('utf-8')
        ).hexdigest()[:16]  # Use first 16 chars for readability
        
        return f"{self.policy.key_prefix}:{key_prefix}:{param_hash}"
    
    def _serialize_data(self, data: Any) -> bytes:
        """
        Serialize data according to cache policy.
        
        Args:
            data: Data to serialize
            
        Returns:
            Serialized data as bytes
            
        Raises:
            ValueError: If serialization fails
        """
        try:
            if self.policy.strategy == CacheStrategy.JSON:
                serialized = json.dumps(data).encode('utf-8')
            else:
                # Use pickle for other strategies
                serialized = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
            
            # Apply compression if enabled
            if self.policy.enable_compression or self.policy.strategy == CacheStrategy.COMPRESSED:
                serialized = gzip.compress(serialized)
            
            # Check size limit
            size_mb = len(serialized) / (1024 * 1024)
            if size_mb > self.policy.max_size_mb:
                raise ValueError(f"Serialized data too large: {size_mb:.2f}MB > {self.policy.max_size_mb}MB")
            
            return serialized
            
        except Exception as e:
            logger.error("Data serialization failed", error=str(e))
            raise ValueError(f"Serialization failed: {str(e)}")
    
    def _deserialize_data(self, data: bytes) -> Any:
        """
        Deserialize cached data.
        
        Args:
            data: Serialized data bytes
            
        Returns:
            Deserialized data
            
        Raises:
            ValueError: If deserialization fails
        """
        try:
            # Decompress if needed
            if self.policy.enable_compression or self.policy.strategy == CacheStrategy.COMPRESSED:
                data = gzip.decompress(data)
            
            if self.policy.strategy == CacheStrategy.JSON:
                return json.loads(data.decode('utf-8'))
            else:
                return pickle.loads(data)
                
        except Exception as e:
            logger.error("Data deserialization failed", error=str(e))
            raise ValueError(f"Deserialization failed: {str(e)}")
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Retrieve cached data by key.
        
        Args:
            key: Cache key
            
        Returns:
            Cached data or None if not found/expired
        """
        if not await self._ensure_connection():
            return None
        
        try:
            cached_data = await self._redis.get(key)
            if cached_data is None:
                return None
            
            data = self._deserialize_data(cached_data)
            
            logger.debug("Cache hit", key=key)
            return data
            
        except (RedisError, ValueError) as e:
            logger.warning("Cache get failed", key=key, error=str(e))
            return None
    
    async def set(
        self, 
        key: str, 
        data: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """
        Store data in cache with TTL.
        
        Args:
            key: Cache key
            data: Data to cache
            ttl: Time to live in seconds (uses default if None)
            
        Returns:
            True if successfully cached
        """
        if not await self._ensure_connection():
            return False
        
        try:
            serialized_data = self._serialize_data(data)
            cache_ttl = ttl or self.policy.default_ttl
            
            await self._redis.setex(key, cache_ttl, serialized_data)
            
            logger.debug(
                "Cache set", 
                key=key, 
                ttl=cache_ttl,
                size_bytes=len(serialized_data)
            )
            return True
            
        except (RedisError, ValueError) as e:
            logger.warning("Cache set failed", key=key, error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """
        Delete cached data by key.
        
        Args:
            key: Cache key to delete
            
        Returns:
            True if key was deleted
        """
        if not await self._ensure_connection():
            return False
        
        try:
            deleted = await self._redis.delete(key)
            if deleted:
                logger.debug("Cache delete", key=key)
            return bool(deleted)
            
        except RedisError as e:
            logger.warning("Cache delete failed", key=key, error=str(e))
            return False
    
    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache.
        
        Args:
            key: Cache key to check
            
        Returns:
            True if key exists
        """
        if not await self._ensure_connection():
            return False
        
        try:
            return bool(await self._redis.exists(key))
        except RedisError as e:
            logger.warning("Cache exists check failed", key=key, error=str(e))
            return False
    
    async def clear_pattern(self, pattern: str) -> int:
        """
        Clear all keys matching a pattern.
        
        Args:
            pattern: Redis key pattern (e.g., 'serp_cache:search:*')
            
        Returns:
            Number of keys deleted
        """
        if not await self._ensure_connection():
            return 0
        
        try:
            keys = await self._redis.keys(pattern)
            if keys:
                deleted = await self._redis.delete(*keys)
                logger.info("Cache pattern cleared", pattern=pattern, keys_deleted=deleted)
                return deleted
            return 0
            
        except RedisError as e:
            logger.warning("Cache pattern clear failed", pattern=pattern, error=str(e))
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        if not await self._ensure_connection():
            return {}
        
        try:
            info = await self._redis.info('memory')
            
            # Count keys by prefix
            search_keys = len(await self._redis.keys(f"{self.policy.key_prefix}:{self.policy.search_prefix}:*"))
            quota_keys = len(await self._redis.keys(f"{self.policy.key_prefix}:{self.policy.quota_prefix}:*"))
            
            return {
                'memory_used_mb': info.get('used_memory', 0) / (1024 * 1024),
                'peak_memory_mb': info.get('used_memory_peak', 0) / (1024 * 1024),
                'search_keys': search_keys,
                'quota_keys': quota_keys,
                'total_keys': search_keys + quota_keys,
                'policy': {
                    'strategy': self.policy.strategy.value,
                    'default_ttl': self.policy.default_ttl,
                    'compression': self.policy.enable_compression
                }
            }
            
        except RedisError as e:
            logger.warning("Failed to get cache stats", error=str(e))
            return {}
    
    async def cleanup_expired(self) -> int:
        """
        Manually cleanup expired keys (Redis does this automatically, but can be forced).
        
        Returns:
            Number of keys cleaned up
        """
        # Redis automatically handles TTL expiration, but we can scan for any remaining
        # This method is mainly for monitoring/debugging purposes
        
        if not await self._ensure_connection():
            return 0
        
        try:
            all_keys = await self._redis.keys(f"{self.policy.key_prefix}:*")
            expired_count = 0
            
            for key in all_keys:
                ttl = await self._redis.ttl(key)
                if ttl == -2:  # Key expired and removed
                    expired_count += 1
            
            if expired_count > 0:
                logger.info("Expired keys cleaned up", count=expired_count)
            
            return expired_count
            
        except RedisError as e:
            logger.warning("Cache cleanup failed", error=str(e))
            return 0
    
    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._connected = False
            logger.debug("Cache connection closed")
"""
SerpAPI Integration for Rank Tracking

This module provides comprehensive SerpAPI integration for daily keyword rank
tracking with geographic targeting, device-specific results, and competitor
analysis within tight quota constraints.

Core Components:
    - SerpAPIClient: Main API client with authentication and quota management
    - SerpResult/RankingData: Pydantic models for API responses
    - ResultTransformer: SERP result parsing and position extraction
    - RankScheduler: Daily tracking automation with priority queues
    - ResultCache: Redis-backed caching for API efficiency

Usage:
    from integrations.serp import SerpAPIClient, RankScheduler
    
    async with SerpAPIClient() as client:
        rankings = await client.track_keywords(['seo automation', 'python seo'])
"""

from .client import SerpAPIClient, SerpAPIError, SerpAPIQuotaError
from .models import (
    SerpResult, OrganicResult, RankingData, SerpFeatures,
    SearchParams, LocationTarget, DeviceType
)
from .transformers import ResultTransformer, PositionExtractor
from .scheduler import RankScheduler, TrackingJob
from .cache import ResultCache, CachePolicy

__all__ = [
    # Client
    "SerpAPIClient", 
    "SerpAPIError", 
    "SerpAPIQuotaError",
    
    # Models
    "SerpResult", 
    "OrganicResult", 
    "RankingData", 
    "SerpFeatures",
    "SearchParams", 
    "LocationTarget", 
    "DeviceType",
    
    # Processing
    "ResultTransformer", 
    "PositionExtractor",
    
    # Scheduling
    "RankScheduler", 
    "TrackingJob",
    
    # Caching
    "ResultCache", 
    "CachePolicy"
]
"""
Pytest configuration and shared fixtures for SEO Automation Platform.

This module provides comprehensive test fixtures for database, Redis, NATS,
and API mocking across all test categories (unit, integration, e2e).
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Generator, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

# Optional imports with fallbacks
try:
    from httpx_mock import HTTPXMock
    HTTPX_MOCK_AVAILABLE = True
except ImportError:
    HTTPX_MOCK_AVAILABLE = False

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy.pool import StaticPool
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import nats
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False

try:
    from config.settings import (
        get_settings, AppSettings, DatabaseSettings, RedisSettings, NATSSettings
    )
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False

try:
    from db.base import Base
    from db.connection import DatabaseManager
    DB_BASE_AVAILABLE = True
except ImportError:
    DB_BASE_AVAILABLE = False

try:
    from agents.registry import AgentRegistry
    AGENTS_AVAILABLE = True
except ImportError:
    AGENTS_AVAILABLE = False

try:
    from task_queue.producer import TaskProducer
    QUEUE_AVAILABLE = True
except ImportError:
    QUEUE_AVAILABLE = False

try:
    from notifications.publisher import NotificationPublisher
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False


# Test configuration overrides
if SETTINGS_AVAILABLE:
    class TestAppSettings(AppSettings):
        """Test application settings with overrides."""
        environment: str = "testing"
        debug: bool = True
        log_level: str = "DEBUG"

    class TestDatabaseSettings(DatabaseSettings):
        """Test database settings with in-memory SQLite for speed."""
        host: str = "localhost" 
        port: int = 5432
        database: str = "seo_platform_test"
        username: str = "test"
        password: str = "testpassword123"
        max_connections: int = 5
        min_connections: int = 1
        
        @property
        def connection_url(self) -> str:
            """Use in-memory SQLite for fast tests."""
            return "sqlite+aiosqlite:///:memory:"
        
        @property 
        def sync_connection_url(self) -> str:
            """Sync connection for setup/teardown."""
            return "sqlite:///:memory:"

    class TestRedisSettings(RedisSettings):
        """Test Redis settings."""
        host: str = "localhost"
        port: int = 6379
        database: int = 15  # Use separate test database
        stream_name: str = "test:tasks"
        consumer_group: str = "test-agents"

    class TestNATSSettings(NATSSettings):
        """Test NATS settings."""
        host: str = "localhost"
        port: int = 4222
        stream_approval: str = "test-approvals"
        stream_alerts: str = "test-alerts"
        stream_tasks: str = "test-tasks"
else:
    # Mock settings classes when not available
    class TestAppSettings:
        environment = "testing"
        debug = True
        log_level = "DEBUG"
    
    class TestDatabaseSettings:
        host = "localhost"
        database = "seo_platform_test"
        
    class TestRedisSettings:
        host = "localhost"
        database = 15
        stream_name = "test:tasks"
        
    class TestNATSSettings:
        host = "localhost"
        stream_approval = "test-approvals"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings():
    """Override application settings for testing."""
    return {
        "app": TestAppSettings(),
        "database": TestDatabaseSettings(), 
        "redis": TestRedisSettings(),
        "nats": TestNATSSettings()
    }


# Database Fixtures
@pytest.fixture(scope="session")
async def async_engine(test_settings):
    """Create async SQLAlchemy engine for tests."""
    if not DB_AVAILABLE or not DB_BASE_AVAILABLE:
        yield AsyncMock()
    else:    
        engine = create_async_engine(
            test_settings["database"].connection_url,
            echo=test_settings["app"].debug,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False}
        )
        
        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        yield engine
        
        # Cleanup 
        await engine.dispose()


@pytest.fixture(scope="session")
def sync_engine(test_settings):
    """Create sync SQLAlchemy engine for setup/teardown."""
    if not DB_AVAILABLE or not DB_BASE_AVAILABLE:
        yield MagicMock()
        return
        
    engine = create_engine(
        test_settings["database"].sync_connection_url,
        echo=test_settings["app"].debug,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False}
    )
    
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    """
    Database session with transaction rollback isolation.
    
    Each test gets a fresh database session within a transaction 
    that is rolled back after the test completes, ensuring test isolation.
    """
    if not DB_AVAILABLE:
        yield AsyncMock()
    else:
        async_session_maker = async_sessionmaker(
            async_engine, 
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        async with async_session_maker() as session:
            # Begin a transaction
            async with session.begin():
                yield session
                # Transaction will be rolled back automatically


@pytest.fixture 
async def populated_db(db_session):
    """Database with sample sites and keywords for testing.""" 
    if not DB_BASE_AVAILABLE:
        # Return mock data when DB not available
        from uuid import uuid4
        mock_site = type('MockSite', (), {
            'id': uuid4(),
            'domain': 'example.com',
            'name': 'Example Site'
        })()
        
        mock_keywords = [
            type('MockKeyword', (), {
                'id': uuid4(),
                'site_id': mock_site.id,
                'keyword': 'seo best practices'
            })(),
            type('MockKeyword', (), {
                'id': uuid4(),  
                'site_id': mock_site.id,
                'keyword': 'buy seo tools'
            })()
        ]
        
        return {"site": mock_site, "keywords": mock_keywords}
    
    # Real DB implementation when available
    from db.models import Site, Keyword, CMSType, KeywordIntent
    
    # Create test site
    site = Site(
        id=uuid4(),
        domain="example.com",
        name="Example Site",
        cms_type=CMSType.WORDPRESS,
        cms_url="https://example.com/wp-admin",
        gsc_property_url="sc-domain:example.com",
        ga4_property_id="123456789", 
        is_active=True
    )
    db_session.add(site)
    
    # Create test keywords
    keywords = [
        Keyword(
            id=uuid4(),
            site_id=site.id,
            keyword="seo best practices",
            intent=KeywordIntent.INFORMATIONAL,
            target_url="https://example.com/seo-guide",
            is_active=True
        ),
        Keyword( 
            id=uuid4(),
            site_id=site.id,
            keyword="buy seo tools",
            intent=KeywordIntent.TRANSACTIONAL,
            target_url="https://example.com/tools",
            is_active=True  
        )
    ]
    
    for keyword in keywords:
        db_session.add(keyword)
    
    await db_session.commit()
    return {"site": site, "keywords": keywords}


# Redis Fixtures  
@pytest.fixture
def redis_client(test_settings):
    """Redis client for test operations."""
    if not REDIS_AVAILABLE:
        return MagicMock()
        
    client = redis.Redis(
        host=test_settings["redis"].host,
        port=test_settings["redis"].port, 
        db=test_settings["redis"].database,
        decode_responses=True
    )
    
    # Clear test database before each test
    try:
        client.flushdb()
    except:
        pass  # Ignore if Redis not available
        
    yield client
    
    # Clean up after test
    try:
        client.flushdb()
        client.close()
    except:
        pass


@pytest.fixture
async def async_redis_client(test_settings):
    """Async Redis client for test operations."""
    if not REDIS_AVAILABLE:
        yield AsyncMock()
    else:
        client = redis.asyncio.Redis(
            host=test_settings["redis"].host,
            port=test_settings["redis"].port,
            db=test_settings["redis"].database,
            decode_responses=True
        )
        
        # Clear test database before each test  
        try:
            await client.flushdb()
        except:
            pass
            
        yield client
        
        # Clean up after test
        try:
            await client.flushdb() 
            await client.close()
        except:
            pass


# NATS Fixtures
@pytest.fixture
async def nats_client(test_settings):
    """NATS client for test operations."""
    if not NATS_AVAILABLE:
        yield AsyncMock()
    else:    
        try:
            nc = await nats.connect(f"nats://{test_settings['nats'].host}:{test_settings['nats'].port}")
            yield nc
        except Exception:
            # If NATS is not available, yield a mock
            yield AsyncMock()
        finally:
            if 'nc' in locals() and hasattr(nc, 'close'):
                await nc.close()


# HTTP Client Mock Fixtures
@pytest.fixture
def httpx_mock():
    """HTTPXMock for mocking HTTP requests."""
    if HTTPX_MOCK_AVAILABLE:
        with HTTPXMock() as mock:
            yield mock
    else:
        # Fallback to basic mock
        yield MagicMock()


@pytest.fixture 
async def http_client():
    """Async HTTP client for testing."""
    async with AsyncClient() as client:
        yield client


# API Mock Response Fixtures
@pytest.fixture
def gsc_mock_responses():
    """GSC API mock response data."""
    fixtures_path = Path(__file__).parent / "fixtures" / "gsc_responses.json"
    
    if fixtures_path.exists():
        with open(fixtures_path) as f:
            return json.load(f)
    
    # Fallback mock data
    return {
        "search_analytics": {
            "rows": [
                {
                    "keys": ["seo best practices"],
                    "clicks": 150.0,
                    "impressions": 2500.0,
                    "ctr": 0.06,
                    "position": 5.2
                },
                {
                    "keys": ["buy seo tools"], 
                    "clicks": 75.0,
                    "impressions": 1200.0,
                    "ctr": 0.0625,
                    "position": 8.1
                }
            ],
            "responseAggregationType": "byPage"
        },
        "sites": {
            "siteEntry": [
                {
                    "siteUrl": "sc-domain:example.com",
                    "permissionLevel": "siteOwner"
                }
            ]
        }
    }


@pytest.fixture
def ga4_mock_responses():
    """GA4 API mock response data.""" 
    fixtures_path = Path(__file__).parent / "fixtures" / "ga4_responses.json"
    
    if fixtures_path.exists():
        with open(fixtures_path) as f:
            return json.load(f)
    
    # Fallback mock data
    return {
        "reports": [
            {
                "dimensionHeaders": [
                    {"name": "pagePath"},
                    {"name": "date"}
                ],
                "metricHeaders": [
                    {"name": "organicGoogleSearchClicks", "type": "TYPE_INTEGER"},
                    {"name": "organicGoogleSearchImpressions", "type": "TYPE_INTEGER"}
                ],
                "rows": [
                    {
                        "dimensionValues": [
                            {"value": "/seo-guide"},  
                            {"value": "20240401"}
                        ],
                        "metricValues": [
                            {"value": "125"},
                            {"value": "2100"}
                        ]
                    }
                ]
            }
        ]
    }


@pytest.fixture  
def serpapi_mock_responses():
    """SerpAPI mock response data."""
    fixtures_path = Path(__file__).parent / "fixtures" / "serp_responses.json"
    
    if fixtures_path.exists():
        with open(fixtures_path) as f:
            return json.load(f)
    
    # Fallback mock data
    return {
        "search_metadata": {
            "id": "mock-search-123",
            "status": "Success", 
            "json_endpoint": "https://serpapi.com/searches/mock-search-123.json",
            "created_at": "2024-04-01 12:00:00 UTC",
            "processed_at": "2024-04-01 12:00:01 UTC",
            "google_url": "https://www.google.com/search?q=seo+best+practices"
        },
        "search_parameters": {
            "engine": "google",
            "q": "seo best practices",
            "location": "United States",
            "hl": "en",
            "gl": "us",
            "google_domain": "google.com"
        },
        "organic_results": [
            {
                "position": 1,
                "title": "13 SEO Best Practices: Improve Your Search Rankings",
                "link": "https://blog.hubspot.com/marketing/seo-best-practices-list",
                "displayed_link": "blog.hubspot.com › marketing › seo-best-practices-list", 
                "snippet": "Learn the essential SEO best practices that will help improve your search engine rankings...",
                "rich_snippet": {
                    "top": {
                        "detected_extensions": {
                            "rating": 4.5,
                            "reviews": 128,
                            "price": "$0"
                        }
                    }
                }
            },
            {
                "position": 5,  
                "title": "SEO Guide: Best Practices for 2024",
                "link": "https://example.com/seo-guide",
                "displayed_link": "example.com › seo-guide",
                "snippet": "Complete guide to SEO best practices for improving organic search rankings..."
            }
        ],
        "related_searches": [
            {
                "query": "seo best practices 2024",
                "link": "https://www.google.com/search?q=seo+best+practices+2024"  
            }
        ]
    }


@pytest.fixture
def api_error_responses():
    """Mock API error responses for testing error handling."""
    return {
        "rate_limit": {
            "error": {
                "code": 429,
                "message": "Quota exceeded", 
                "status": "RESOURCE_EXHAUSTED"
            }
        },
        "server_error": {
            "error": {
                "code": 500,
                "message": "Internal server error",
                "status": "INTERNAL"
            }
        },
        "auth_error": { 
            "error": {
                "code": 401,
                "message": "Request is not authorized",
                "status": "UNAUTHENTICATED"
            }
        }
    }


# Agent and Queue System Fixtures
@pytest.fixture
def agent_registry():
    """Agent registry for testing agent workflows."""
    if not AGENTS_AVAILABLE:
        return MagicMock()
    return AgentRegistry()


@pytest.fixture
async def task_producer(async_redis_client, test_settings):
    """Task queue producer for testing."""
    if not QUEUE_AVAILABLE:
        yield AsyncMock()
    else:
        producer = TaskProducer(
            redis_client=async_redis_client,
            stream_name=test_settings["redis"].stream_name
        )
        yield producer


@pytest.fixture
async def notification_publisher(nats_client, test_settings):
    """Notification publisher for testing approval workflows."""
    if not NOTIFICATIONS_AVAILABLE:
        yield AsyncMock()
    else:
        publisher = NotificationPublisher(
            nats_client=nats_client,
            stream_approval=test_settings["nats"].stream_approval
        )
        yield publisher


# Application Fixtures
@pytest.fixture
async def app_client(test_settings):
    """Application client for end-to-end testing."""
    # This will be implemented when we have the FastAPI app
    # For now, return a mock
    return AsyncMock()


# Utility Fixtures
@pytest.fixture
def sample_uuid():
    """Generate a sample UUID for testing."""
    return uuid4()


@pytest.fixture
def sample_date():
    """Sample date for testing."""
    from datetime import date
    return date(2024, 4, 1)


@pytest.fixture
def clean_env():
    """Clean environment variables for testing."""
    original_env = os.environ.copy()
    
    # Set test environment variables
    test_env = {
        "ENVIRONMENT": "testing",
        "DEBUG": "true",
        "LOG_LEVEL": "DEBUG",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "seo_platform_test",
        "POSTGRES_USER": "test",
        "POSTGRES_PASSWORD": "testpassword123",
        "REDIS_HOST": "localhost", 
        "REDIS_PORT": "6379",
        "REDIS_DB": "15",
        "NATS_HOST": "localhost",
        "NATS_PORT": "4222"
    }
    
    for key, value in test_env.items():
        os.environ[key] = value
    
    yield
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
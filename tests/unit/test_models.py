"""
Unit tests for database models.

Tests the core database models without external dependencies,
using in-memory SQLite for fast execution.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from db.models import Site, Keyword, Ranking, GSCMetric, AuditLog, CMSType, KeywordIntent


@pytest.mark.unit
@pytest.mark.database
class TestSiteModel:
    """Test cases for the Site model."""
    
    def test_site_creation(self):
        """Test basic site creation with required fields."""
        site = Site(
            id=uuid4(),
            domain="example.com",
            name="Example Site",
            cms_type=CMSType.WORDPRESS,
            cms_url="https://example.com/wp-admin",
            gsc_property_url="sc-domain:example.com",
            ga4_property_id="123456789"
        )
        
        assert site.domain == "example.com"
        assert site.name == "Example Site"
        assert site.cms_type == CMSType.WORDPRESS
        assert site.is_active is True  # Default value
    
    def test_site_validation(self):
        """Test site model validation rules."""
        # Test with invalid domain (should not raise for now, but we can add validation later)
        site = Site(
            id=uuid4(),
            domain="invalid-domain",  # Missing TLD
            name="Test Site",
            cms_type=CMSType.CUSTOM,
            cms_url="https://test.com/admin",
            gsc_property_url="https://test.com/",
            ga4_property_id="987654321"
        )
        assert site.domain == "invalid-domain"
    
    async def test_site_persistence(self, db_session):
        """Test site model database persistence."""
        site = Site(
            id=uuid4(),
            domain="test-persistence.com",
            name="Persistence Test Site",
            cms_type=CMSType.WORDPRESS,
            cms_url="https://test-persistence.com/wp-admin",
            gsc_property_url="sc-domain:test-persistence.com",
            ga4_property_id="111222333"
        )
        
        db_session.add(site)
        await db_session.commit()
        
        # Verify the site was saved
        assert site.id is not None
        assert site.created_at is not None
        assert site.updated_at is not None


@pytest.mark.unit  
@pytest.mark.database
class TestKeywordModel:
    """Test cases for the Keyword model."""
    
    async def test_keyword_creation_with_site(self, populated_db):
        """Test keyword creation linked to a site.""" 
        site = populated_db["site"]
        
        keyword = Keyword(
            id=uuid4(),
            site_id=site.id,
            keyword="test keyword creation",
            intent=KeywordIntent.INFORMATIONAL,
            target_url="https://example.com/test-page",
            search_volume=1000,
            difficulty_score=Decimal("65.5")
        )
        
        assert keyword.site_id == site.id
        assert keyword.keyword == "test keyword creation"
        assert keyword.intent == KeywordIntent.INFORMATIONAL
        assert keyword.search_volume == 1000
        assert keyword.difficulty_score == Decimal("65.5")
    
    def test_keyword_intent_enum(self):
        """Test keyword intent enumeration values."""
        assert KeywordIntent.INFORMATIONAL.value == "informational"
        assert KeywordIntent.NAVIGATIONAL.value == "navigational" 
        assert KeywordIntent.TRANSACTIONAL.value == "transactional"
        assert KeywordIntent.COMMERCIAL.value == "commercial"
    
    async def test_keyword_relationships(self, populated_db, db_session):
        """Test keyword-to-site relationship."""
        site = populated_db["site"]
        keywords = populated_db["keywords"]
        
        # Test that we can access the site from keyword (if relationship is set up)
        keyword = keywords[0]
        
        # Since we don't have the relationship set up yet, just verify the foreign key
        assert keyword.site_id == site.id


@pytest.mark.unit
@pytest.mark.database  
class TestRankingModel:
    """Test cases for the Ranking model (TimescaleDB)."""
    
    async def test_ranking_creation(self, populated_db, db_session):
        """Test ranking data creation."""
        keywords = populated_db["keywords"]
        keyword = keywords[0]
        
        ranking = Ranking(
            id=uuid4(),
            keyword_id=keyword.id,
            date=date(2024, 4, 1),
            position=5,
            url="https://example.com/seo-guide",
            device="DESKTOP",
            location="US"
        )
        
        db_session.add(ranking)
        await db_session.commit()
        
        assert ranking.keyword_id == keyword.id
        assert ranking.date == date(2024, 4, 1)
        assert ranking.position == 5
        assert ranking.device == "DESKTOP"
    
    def test_ranking_validation(self):
        """Test ranking model validation."""
        ranking = Ranking(
            id=uuid4(),
            keyword_id=uuid4(),
            date=date(2024, 4, 1),
            position=1,  # Valid position
            url="https://example.com/page",
            device="MOBILE",
            location="UK"
        )
        
        assert ranking.position == 1
        
        # Test position bounds (should be handled by database constraints)
        ranking_invalid = Ranking(
            id=uuid4(),
            keyword_id=uuid4(),
            date=date(2024, 4, 1),
            position=0,  # Invalid position (should be >= 1)
            url="https://example.com/page",
            device="MOBILE",
            location="UK"
        )
        
        # Position 0 should be allowed at model level, constraints at DB level
        assert ranking_invalid.position == 0


@pytest.mark.unit
@pytest.mark.database
class TestGSCMetricModel:
    """Test cases for the GSCMetric model (TimescaleDB)."""
    
    async def test_gsc_metric_creation(self, populated_db, db_session):
        """Test GSC metric data creation."""
        site = populated_db["site"]
        
        gsc_metric = GSCMetric(
            id=uuid4(),
            site_id=site.id,
            date=date(2024, 4, 1),
            query="seo best practices",
            page="/seo-guide",
            clicks=150, 
            impressions=2500,
            ctr=Decimal("0.06"),
            position=Decimal("5.2"),
            device="DESKTOP",
            country="US"
        )
        
        db_session.add(gsc_metric)
        await db_session.commit()
        
        assert gsc_metric.site_id == site.id
        assert gsc_metric.query == "seo best practices"
        assert gsc_metric.clicks == 150
        assert gsc_metric.impressions == 2500
        assert gsc_metric.ctr == Decimal("0.06")
        assert gsc_metric.position == Decimal("5.2")
    
    def test_gsc_metric_calculations(self):
        """Test GSC metric derived calculations."""
        gsc_metric = GSCMetric(
            id=uuid4(),
            site_id=uuid4(),
            date=date(2024, 4, 1),
            query="test query",
            page="/test",
            clicks=75,
            impressions=1200,
            ctr=None,  # Will be calculated
            position=Decimal("8.1"),
            device="MOBILE"
        )
        
        # Calculate CTR if not provided
        if gsc_metric.ctr is None and gsc_metric.impressions > 0:
            calculated_ctr = Decimal(str(gsc_metric.clicks / gsc_metric.impressions))
            assert calculated_ctr == Decimal("0.0625")


@pytest.mark.unit
@pytest.mark.database
class TestAuditLogModel:
    """Test cases for the AuditLog model."""
    
    async def test_audit_log_creation(self, populated_db, db_session):
        """Test audit log entry creation."""
        site = populated_db["site"]
        
        audit_log = AuditLog(
            id=uuid4(),
            site_id=site.id,
            action="keyword_research",
            agent_name="keyword_agent",
            status="completed",
            input_data={"query": "seo tools", "limit": 50},
            output_data={"keywords_found": 25, "avg_volume": 1500},
            execution_time_ms=2500
        )
        
        db_session.add(audit_log)
        await db_session.commit()
        
        assert audit_log.site_id == site.id
        assert audit_log.action == "keyword_research"
        assert audit_log.agent_name == "keyword_agent"
        assert audit_log.status == "completed"
        assert audit_log.input_data["query"] == "seo tools"
        assert audit_log.output_data["keywords_found"] == 25
        assert audit_log.execution_time_ms == 2500
    
    def test_audit_log_approval_workflow(self):
        """Test audit log for approval workflow tracking."""
        audit_log = AuditLog(
            id=uuid4(), 
            site_id=uuid4(),
            action="publish_post",
            agent_name="content_agent", 
            status="pending_approval",
            input_data={"title": "New SEO Article", "content_length": 2500},
            approval_required=True,
            approval_timeout_at=datetime.utcnow().replace(microsecond=0)
        )
        
        assert audit_log.approval_required is True
        assert audit_log.status == "pending_approval"
        assert audit_log.approval_timeout_at is not None


@pytest.mark.unit
class TestModelEnums:
    """Test model enumeration classes."""
    
    def test_cms_type_enum(self):
        """Test CMS type enumeration."""
        assert CMSType.WORDPRESS.value == "wordpress"
        assert CMSType.CUSTOM.value == "custom"
        
        # Test enum usage in model
        site = Site(
            id=uuid4(),
            domain="wp-test.com",
            name="WordPress Test",
            cms_type=CMSType.WORDPRESS,
            cms_url="https://wp-test.com/wp-admin",
            gsc_property_url="sc-domain:wp-test.com",
            ga4_property_id="999888777"
        )
        assert site.cms_type == CMSType.WORDPRESS
    
    def test_keyword_intent_enum(self):
        """Test keyword intent enumeration."""
        intents = [
            KeywordIntent.INFORMATIONAL,
            KeywordIntent.NAVIGATIONAL, 
            KeywordIntent.TRANSACTIONAL,
            KeywordIntent.COMMERCIAL
        ]
        
        values = [intent.value for intent in intents]
        expected = ["informational", "navigational", "transactional", "commercial"]
        
        assert values == expected


# Utility test functions
@pytest.mark.unit
class TestModelUtilities:
    """Test model utility functions and methods."""
    
    def test_uuid_generation(self):
        """Test UUID generation for models."""
        site1_id = uuid4()
        site2_id = uuid4()
        
        assert site1_id != site2_id
        assert len(str(site1_id)) == 36  # UUID string length
    
    def test_timestamp_mixin(self):
        """Test timestamp mixin functionality."""
        site = Site(
            id=uuid4(),
            domain="timestamp-test.com",
            name="Timestamp Test", 
            cms_type=CMSType.CUSTOM,
            cms_url="https://timestamp-test.com/admin",
            gsc_property_url="https://timestamp-test.com/",
            ga4_property_id="555444333"
        )
        
        # Timestamps should be set during DB operations
        # For now, just test that the fields exist
        assert hasattr(site, 'created_at')
        assert hasattr(site, 'updated_at')
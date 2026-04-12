"""
SQLAlchemy ORM models for SEO Automation Platform.

This module defines all database models for the SEO automation system,
including core entities, time-series metrics, and audit logging.

Models:
    - Site: Managed websites with CMS integration
    - Keyword: Target keywords with intent classification
    - Ranking: Daily SERP position tracking (TimescaleDB)
    - GSCMetric: Google Search Console metrics (TimescaleDB)
    - GA4Metric: Google Analytics 4 metrics (TimescaleDB)
    - AuditLog: Automated action tracking and approval workflows
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, Float, ForeignKey,
    Index, Integer, Numeric, String, Text, UniqueConstraint,
    CheckConstraint, text
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from .base import Base, TimestampMixin, UUIDMixin, SoftDeleteMixin, utcnow
from .mixins import MetadataMixin, StatusMixin, AuditMixin, TimescaleMixin


# Enums for type safety
class CMSType(PyEnum):
    """Supported CMS types."""
    WORDPRESS = "wordpress"
    CUSTOM = "custom"


class KeywordIntent(PyEnum):
    """Keyword search intent classification."""
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    TRANSACTIONAL = "transactional"
    COMMERCIAL = "commercial"


class KeywordPriority(PyEnum):
    """Keyword priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(PyEnum):
    """Types of automated actions for audit logging."""
    KEYWORD_RESEARCH = "keyword_research"
    CONTENT_GENERATION = "content_generation"
    CONTENT_PUBLISH = "content_publish"
    RANK_TRACKING = "rank_tracking"
    GSC_SYNC = "gsc_sync"
    GA4_SYNC = "ga4_sync"
    LINK_ANALYSIS = "link_analysis"
    SITE_OPTIMIZATION = "site_optimization"


class EntityType(PyEnum):
    """Entity types for audit logging."""
    SITE = "site"
    KEYWORD = "keyword"
    CONTENT = "content"
    RANKING = "ranking"
    METRIC = "metric"


class ApprovalStatus(PyEnum):
    """Approval workflow statuses."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


# Core Models
class Site(Base, UUIDMixin, TimestampMixin, MetadataMixin, StatusMixin):
    """
    Managed websites with CMS integration details.
    
    Represents websites that are managed by the SEO automation platform,
    including connection details for WordPress or custom CMS integration.
    """
    
    __tablename__ = "sites"
    
    # Basic site information
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name of the website"
    )
    
    url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        unique=True,
        comment="Primary URL of the website"
    )
    
    cms_type: Mapped[CMSType] = mapped_column(
        Enum(CMSType),
        nullable=False,
        comment="Content management system type"
    )
    
    # CMS connection details (stored in metadata for security)
    cms_host: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="CMS API endpoint or admin URL"
    )
    
    # SEO configuration
    primary_domain: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Primary domain for GSC and GA4 tracking"
    )
    
    target_country: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="US",
        comment="Target country code (ISO 3166-1 alpha-2)"
    )
    
    target_language: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="en",
        comment="Target language code (ISO 639-1)"
    )
    
    # Relationships
    keywords: Mapped[List["Keyword"]] = relationship(
        "Keyword",
        back_populates="site",
        cascade="all, delete-orphan"
    )
    
    rankings: Mapped[List["Ranking"]] = relationship(
        "Ranking",
        back_populates="site"
    )
    
    gsc_metrics: Mapped[List["GSCMetric"]] = relationship(
        "GSCMetric",
        back_populates="site"
    )
    
    ga4_metrics: Mapped[List["GA4Metric"]] = relationship(
        "GA4Metric",
        back_populates="site"
    )
    
    __table_args__ = (
        Index("ix_sites_cms_type", "cms_type"),
        Index("ix_sites_status", "status"),
        Index("ix_sites_primary_domain", "primary_domain"),
    )
    
    def __repr__(self) -> str:
        return f"<Site(id={self.id}, name='{self.name}', url='{self.url}')>"


class Keyword(Base, UUIDMixin, TimestampMixin, MetadataMixin):
    """
    Target keywords with intent classification and embeddings.
    
    Stores keywords that the SEO platform is tracking and optimizing for,
    including semantic embeddings for content matching and clustering.
    """
    
    __tablename__ = "keywords"
    
    # Foreign key to site
    site_id: Mapped[UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the associated website"
    )
    
    # Keyword details
    keyword: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="The target keyword phrase"
    )
    
    intent: Mapped[KeywordIntent] = mapped_column(
        Enum(KeywordIntent),
        nullable=False,
        comment="Search intent classification"
    )
    
    priority: Mapped[KeywordPriority] = mapped_column(
        Enum(KeywordPriority),
        nullable=False,
        default=KeywordPriority.MEDIUM,
        comment="Keyword optimization priority"
    )
    
    # SEO metrics
    monthly_search_volume: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Average monthly search volume"
    )
    
    competition_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2),  # 0.00 to 1.00
        nullable=True,
        comment="Competition difficulty score (0.0 = easy, 1.0 = hard)"
    )
    
    # Vector embeddings for semantic similarity
    embedding: Mapped[Optional[List[float]]] = mapped_column(
        Vector(1536),  # OpenAI embedding dimensions
        nullable=True,
        comment="Semantic embedding vector for similarity matching"
    )
    
    # Content optimization
    target_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Target URL to optimize for this keyword"
    )
    
    content_brief: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Content optimization brief and guidelines"
    )
    
    # Relationships
    site: Mapped["Site"] = relationship(
        "Site",
        back_populates="keywords"
    )
    
    rankings: Mapped[List["Ranking"]] = relationship(
        "Ranking",
        back_populates="keyword"
    )
    
    __table_args__ = (
        UniqueConstraint("site_id", "keyword", name="uq_site_keyword"),
        Index("ix_keywords_site_id", "site_id"),
        Index("ix_keywords_intent", "intent"),
        Index("ix_keywords_priority", "priority"),
        Index("ix_keywords_search_volume", "monthly_search_volume"),
        # Vector similarity index (cosine distance)
        Index("ix_keywords_embedding_cosine", "embedding", 
              postgresql_using="ivfflat",
              postgresql_with={"lists": 100},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )
    
    def __repr__(self) -> str:
        return f"<Keyword(id={self.id}, keyword='{self.keyword}', intent='{self.intent.value}')>"


# Time-Series Models (TimescaleDB Hypertables)
class Ranking(Base, UUIDMixin, TimestampMixin, TimescaleMixin):
    """
    Daily SERP position tracking for keywords.
    
    TimescaleDB hypertable for efficient time-series storage of
    keyword ranking data with automatic compression and retention.
    """
    
    __tablename__ = "rankings"
    
    # Foreign keys
    site_id: Mapped[UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the associated website"
    )
    
    keyword_id: Mapped[UUID] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the tracked keyword"
    )
    
    # Time-series data
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Date of the ranking snapshot"
    )
    
    # Ranking metrics
    position: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="SERP position (1-indexed, null = not ranking in top 100)"
    )
    
    url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="URL that ranked for this keyword"
    )
    
    search_volume: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Daily search volume for this keyword"
    )
    
    # SERP feature tracking
    featured_snippet: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the URL appeared in a featured snippet"
    )
    
    image_pack: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the URL appeared in image pack results"
    )
    
    local_pack: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the URL appeared in local pack results"
    )
    
    # Relationships
    site: Mapped["Site"] = relationship("Site", back_populates="rankings")
    keyword: Mapped["Keyword"] = relationship("Keyword", back_populates="rankings")
    
    __table_args__ = (
        UniqueConstraint("site_id", "keyword_id", "date", name="uq_ranking_daily"),
        Index("ix_rankings_site_date", "site_id", "date"),
        Index("ix_rankings_keyword_date", "keyword_id", "date"),
        Index("ix_rankings_position", "position"),
        CheckConstraint("position > 0 AND position <= 100", name="ck_valid_position"),
    )
    
    @hybrid_property
    def is_ranking(self) -> bool:
        """Check if the keyword is ranking (has a position)."""
        return self.position is not None
    
    def __repr__(self) -> str:
        return f"<Ranking(keyword_id={self.keyword_id}, date={self.date}, position={self.position})>"


class GSCMetric(Base, UUIDMixin, TimestampMixin, TimescaleMixin):
    """
    Google Search Console daily metrics.
    
    TimescaleDB hypertable for GSC performance data including
    clicks, impressions, CTR, and position data per URL.
    """
    
    __tablename__ = "gsc_metrics"
    
    # Foreign key
    site_id: Mapped[UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the associated website"
    )
    
    # Time-series data
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Date of the metric snapshot"
    )
    
    # GSC dimensions
    url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="URL that received the traffic"
    )
    
    query: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Search query that triggered the result"
    )
    
    country: Mapped[Optional[str]] = mapped_column(
        String(2),
        nullable=True,
        comment="Country code where the search occurred"
    )
    
    device: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Device type (desktop, mobile, tablet)"
    )
    
    # GSC metrics
    clicks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of clicks from search results"
    )
    
    impressions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of times URL appeared in search results"
    )
    
    ctr: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),  # 0.0000 to 1.0000
        nullable=False,
        default=0,
        comment="Click-through rate (clicks/impressions)"
    )
    
    position: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),  # Average position with 2 decimal places
        nullable=False,
        default=0,
        comment="Average position in search results"
    )
    
    # Relationships
    site: Mapped["Site"] = relationship("Site", back_populates="gsc_metrics")
    
    __table_args__ = (
        UniqueConstraint("site_id", "date", "url", "query", "country", "device",
                        name="uq_gsc_metric_daily"),
        Index("ix_gsc_metrics_site_date", "site_id", "date"),
        Index("ix_gsc_metrics_url", "url"),
        Index("ix_gsc_metrics_query", "query"),
        Index("ix_gsc_metrics_clicks", "clicks"),
        CheckConstraint("clicks >= 0", name="ck_gsc_clicks_positive"),
        CheckConstraint("impressions >= 0", name="ck_gsc_impressions_positive"),
        CheckConstraint("ctr >= 0 AND ctr <= 1", name="ck_gsc_ctr_valid"),
    )
    
    def __repr__(self) -> str:
        return f"<GSCMetric(site_id={self.site_id}, date={self.date}, url='{self.url[:50]}...')>"


class GA4Metric(Base, UUIDMixin, TimestampMixin, TimescaleMixin):
    """
    Google Analytics 4 organic traffic metrics.
    
    TimescaleDB hypertable for GA4 performance data including
    sessions, bounce rate, and page view metrics per page.
    """
    
    __tablename__ = "ga4_metrics"
    
    # Foreign key
    site_id: Mapped[UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to the associated website"
    )
    
    # Time-series data
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Date of the metric snapshot"
    )
    
    # GA4 dimensions
    page_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Page path that received organic traffic"
    )
    
    landing_page: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Landing page for the session"
    )
    
    source_medium: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Traffic source and medium (e.g., google / organic)"
    )
    
    country: Mapped[Optional[str]] = mapped_column(
        String(2),
        nullable=True,
        comment="Country code of the visitor"
    )
    
    device_category: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Device category (desktop, mobile, tablet)"
    )
    
    # GA4 metrics
    sessions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of sessions for this page"
    )
    
    page_views: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of page views"
    )
    
    unique_page_views: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of unique page views"
    )
    
    bounce_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4),  # 0.0000 to 1.0000
        nullable=True,
        comment="Bounce rate for sessions starting on this page"
    )
    
    avg_session_duration: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Average session duration in seconds"
    )
    
    conversions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of conversions attributed to this page"
    )
    
    revenue: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Revenue attributed to this page"
    )
    
    # Relationships
    site: Mapped["Site"] = relationship("Site", back_populates="ga4_metrics")
    
    __table_args__ = (
        UniqueConstraint("site_id", "date", "page_path", "source_medium", "country", "device_category",
                        name="uq_ga4_metric_daily"),
        Index("ix_ga4_metrics_site_date", "site_id", "date"),
        Index("ix_ga4_metrics_page_path", "page_path"),
        Index("ix_ga4_metrics_sessions", "sessions"),
        Index("ix_ga4_metrics_conversions", "conversions"),
        CheckConstraint("sessions >= 0", name="ck_ga4_sessions_positive"),
        CheckConstraint("page_views >= 0", name="ck_ga4_page_views_positive"),
        CheckConstraint("bounce_rate >= 0 AND bounce_rate <= 1", name="ck_ga4_bounce_rate_valid"),
    )
    
    def __repr__(self) -> str:
        return f"<GA4Metric(site_id={self.site_id}, date={self.date}, page_path='{self.page_path[:50]}...')>"


class AuditLog(Base, UUIDMixin, TimestampMixin):
    """
    Audit log for all automated actions and approval workflows.
    
    Tracks every action performed by the SEO automation platform
    including human approval gates and system decisions.
    """
    
    __tablename__ = "audit_log"
    
    # Action classification
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType),
        nullable=False,
        comment="Type of action performed"
    )
    
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType),
        nullable=False,
        comment="Type of entity affected by the action"
    )
    
    entity_id: Mapped[Optional[UUID]] = mapped_column(
        PostgresUUID(as_uuid=True),
        nullable=True,
        comment="ID of the affected entity (if applicable)"
    )
    
    # Action details
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable description of the action"
    )
    
    changes: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="JSON representation of changes made"
    )
    
    # Context and metadata
    user_context: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="User or system context for the action"
    )
    
    request_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Original request data that triggered the action"
    )
    
    response_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Response data from the action"
    )
    
    # Approval workflow
    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this action required human approval"
    )
    
    approval_status: Mapped[Optional[ApprovalStatus]] = mapped_column(
        Enum(ApprovalStatus),
        nullable=True,
        comment="Status of the approval workflow"
    )
    
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="User who approved or rejected the action"
    )
    
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the action was approved/rejected"
    )
    
    # Error handling
    success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether the action completed successfully"
    )
    
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if the action failed"
    )
    
    # Performance tracking
    execution_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Action execution time in milliseconds"
    )
    
    __table_args__ = (
        Index("ix_audit_log_action_type", "action_type"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_approval_status", "approval_status"),
        Index("ix_audit_log_success", "success"),
        Index("ix_audit_log_created_at", "created_at"),
    )
    
    @hybrid_property
    def is_pending_approval(self) -> bool:
        """Check if the action is pending approval."""
        return (self.requires_approval and 
                self.approval_status == ApprovalStatus.PENDING)
    
    def approve(self, approved_by: str) -> None:
        """Approve the action."""
        self.approval_status = ApprovalStatus.APPROVED
        self.approved_by = approved_by
        self.approved_at = utcnow()
    
    def reject(self, rejected_by: str) -> None:
        """Reject the action."""
        self.approval_status = ApprovalStatus.REJECTED
        self.approved_by = rejected_by
        self.approved_at = utcnow()
    
    def timeout(self) -> None:
        """Mark the approval as timed out."""
        self.approval_status = ApprovalStatus.TIMEOUT
        self.approved_at = utcnow()
    
    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action='{self.action_type.value}', entity='{self.entity_type.value}')>"


# Export all models for easy importing
__all__ = [
    "Base",
    "Site",
    "Keyword", 
    "Ranking",
    "GSCMetric",
    "GA4Metric",
    "AuditLog",
    "CMSType",
    "KeywordIntent",
    "KeywordPriority",
    "ActionType",
    "EntityType",
    "ApprovalStatus",
]
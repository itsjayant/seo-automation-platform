"""initial_schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-04-12 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text
import pgvector.sqlalchemy

# revision identifiers
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial database schema with TimescaleDB hypertables and pgvector indexes."""
    
    # Enable required PostgreSQL extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    
    # Create enum types
    op.execute("CREATE TYPE cmstype AS ENUM ('wordpress', 'custom')")
    op.execute("CREATE TYPE keywordintent AS ENUM ('informational', 'navigational', 'transactional', 'commercial')")
    op.execute("CREATE TYPE keywordpriority AS ENUM ('low', 'medium', 'high', 'critical')")
    op.execute("CREATE TYPE actiontype AS ENUM ('keyword_research', 'content_generation', 'content_publish', 'rank_tracking', 'gsc_sync', 'ga4_sync', 'link_analysis', 'site_optimization')")
    op.execute("CREATE TYPE entitytype AS ENUM ('site', 'keyword', 'content', 'ranking', 'metric')")
    op.execute("CREATE TYPE approvalstatus AS ENUM ('pending', 'approved', 'rejected', 'timeout')")
    
    # Create sites table
    op.create_table(
        'sites',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('name', sa.String(255), nullable=False, comment='Display name of the website'),
        sa.Column('url', sa.String(500), nullable=False, comment='Primary URL of the website'),
        sa.Column('cms_type', sa.Enum('wordpress', 'custom', name='cmstype'), nullable=False, comment='Content management system type'),
        sa.Column('cms_host', sa.String(500), nullable=True, comment='CMS API endpoint or admin URL'),
        sa.Column('primary_domain', sa.String(255), nullable=False, comment='Primary domain for GSC and GA4 tracking'),
        sa.Column('target_country', sa.String(2), nullable=False, server_default='US', comment='Target country code (ISO 3166-1 alpha-2)'),
        sa.Column('target_language', sa.String(5), nullable=False, server_default='en', comment='Target language code (ISO 639-1)'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url'),
    )
    
    # Create indexes for sites table
    op.create_index('ix_sites_cms_type', 'sites', ['cms_type'])
    op.create_index('ix_sites_status', 'sites', ['status'])
    op.create_index('ix_sites_primary_domain', 'sites', ['primary_domain'])
    op.create_index('ix_sites_created_at', 'sites', ['created_at'])
    op.create_index('ix_sites_updated_at', 'sites', ['updated_at'])
    
    # Create keywords table
    op.create_table(
        'keywords',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Reference to the associated website'),
        sa.Column('keyword', sa.String(500), nullable=False, comment='The target keyword phrase'),
        sa.Column('intent', sa.Enum('informational', 'navigational', 'transactional', 'commercial', name='keywordintent'), nullable=False, comment='Search intent classification'),
        sa.Column('priority', sa.Enum('low', 'medium', 'high', 'critical', name='keywordpriority'), nullable=False, server_default='medium', comment='Keyword optimization priority'),
        sa.Column('monthly_search_volume', sa.Integer(), nullable=True, comment='Average monthly search volume'),
        sa.Column('competition_score', sa.Numeric(3, 2), nullable=True, comment='Competition difficulty score (0.0 = easy, 1.0 = hard)'),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1536), nullable=True, comment='Semantic embedding vector for similarity matching'),
        sa.Column('target_url', sa.String(500), nullable=True, comment='Target URL to optimize for this keyword'),
        sa.Column('content_brief', sa.Text(), nullable=True, comment='Content optimization brief and guidelines'),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('site_id', 'keyword', name='uq_site_keyword'),
    )
    
    # Create indexes for keywords table
    op.create_index('ix_keywords_site_id', 'keywords', ['site_id'])
    op.create_index('ix_keywords_intent', 'keywords', ['intent'])
    op.create_index('ix_keywords_priority', 'keywords', ['priority'])
    op.create_index('ix_keywords_search_volume', 'keywords', ['monthly_search_volume'])
    op.create_index('ix_keywords_created_at', 'keywords', ['created_at'])
    op.create_index('ix_keywords_updated_at', 'keywords', ['updated_at'])
    
    # Create audit_log table
    op.create_table(
        'audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('action_type', sa.Enum('keyword_research', 'content_generation', 'content_publish', 'rank_tracking', 'gsc_sync', 'ga4_sync', 'link_analysis', 'site_optimization', name='actiontype'), nullable=False, comment='Type of automated action performed'),
        sa.Column('entity_type', sa.Enum('site', 'keyword', 'content', 'ranking', 'metric', name='entitytype'), nullable=False, comment='Type of entity being acted upon'),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True, comment='ID of the entity being acted upon'),
        sa.Column('description', sa.Text(), nullable=False, comment='Human-readable description of the action'),
        sa.Column('changes', postgresql.JSONB(), nullable=True, comment='JSON object describing the changes made'),
        sa.Column('user_context', postgresql.JSONB(), nullable=True, comment='Context about the user or system that initiated the action'),
        sa.Column('request_data', postgresql.JSONB(), nullable=True, comment='Original request data that triggered the action'),
        sa.Column('response_data', postgresql.JSONB(), nullable=True, comment='Response data from the action'),
        sa.Column('requires_approval', sa.Boolean(), nullable=False, server_default='false', comment='Whether this action required human approval'),
        sa.Column('approval_status', sa.Enum('pending', 'approved', 'rejected', 'timeout', name='approvalstatus'), nullable=True, comment='Status of the approval workflow'),
        sa.Column('approved_by', sa.String(255), nullable=True, comment='User who approved or rejected the action'),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp when the action was approved/rejected'),
        sa.Column('success', sa.Boolean(), nullable=False, server_default='true', comment='Whether the action completed successfully'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='Error message if the action failed'),
        sa.Column('execution_time_ms', sa.Integer(), nullable=True, comment='Action execution time in milliseconds'),
        sa.PrimaryKeyConstraint('id'),
    )
    
    # Create indexes for audit_log table
    op.create_index('ix_audit_log_action_type', 'audit_log', ['action_type'])
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_type', 'entity_id'])
    op.create_index('ix_audit_log_approval_status', 'audit_log', ['approval_status'])
    op.create_index('ix_audit_log_success', 'audit_log', ['success'])
    op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'])
    
    # Create time-series tables
    # Rankings table
    op.create_table(
        'rankings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Reference to the associated website'),
        sa.Column('keyword_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Reference to the tracked keyword'),
        sa.Column('date', sa.Date(), nullable=False, comment='Date of the ranking snapshot'),
        sa.Column('position', sa.Integer(), nullable=True, comment='SERP position (1-indexed, null = not ranking in top 100)'),
        sa.Column('url', sa.String(500), nullable=True, comment='URL that ranked for this keyword'),
        sa.Column('search_volume', sa.Integer(), nullable=True, comment='Daily search volume for this keyword'),
        sa.Column('featured_snippet', sa.Boolean(), nullable=False, server_default='false', comment='Whether the URL appeared in a featured snippet'),
        sa.Column('image_pack', sa.Boolean(), nullable=False, server_default='false', comment='Whether the URL appeared in image pack results'),
        sa.Column('local_pack', sa.Boolean(), nullable=False, server_default='false', comment='Whether the URL appeared in local pack results'),
        sa.CheckConstraint('position > 0 AND position <= 100', name='ck_valid_position'),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['keyword_id'], ['keywords.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('site_id', 'keyword_id', 'date', name='uq_ranking_daily'),
    )
    
    # Create indexes for rankings table
    op.create_index('ix_rankings_site_date', 'rankings', ['site_id', 'date'])
    op.create_index('ix_rankings_keyword_date', 'rankings', ['keyword_id', 'date'])
    op.create_index('ix_rankings_position', 'rankings', ['position'])
    op.create_index('ix_rankings_created_at', 'rankings', ['created_at'])
    
    # GSC Metrics table
    op.create_table(
        'gsc_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Reference to the associated website'),
        sa.Column('date', sa.Date(), nullable=False, comment='Date of the metric snapshot'),
        sa.Column('url', sa.String(500), nullable=False, comment='URL that received the traffic'),
        sa.Column('query', sa.String(500), nullable=True, comment='Search query that triggered the result'),
        sa.Column('country', sa.String(2), nullable=True, comment='Country code where the search occurred'),
        sa.Column('device', sa.String(10), nullable=True, comment='Device type (desktop, mobile, tablet)'),
        sa.Column('clicks', sa.Integer(), nullable=False, server_default='0', comment='Number of clicks from search results'),
        sa.Column('impressions', sa.Integer(), nullable=False, server_default='0', comment='Number of times URL appeared in search results'),
        sa.Column('ctr', sa.Numeric(5, 4), nullable=False, server_default='0', comment='Click-through rate (clicks/impressions)'),
        sa.Column('position', sa.Numeric(5, 2), nullable=False, server_default='0', comment='Average position in search results'),
        sa.CheckConstraint('clicks >= 0', name='ck_gsc_clicks_positive'),
        sa.CheckConstraint('impressions >= 0', name='ck_gsc_impressions_positive'),
        sa.CheckConstraint('ctr >= 0 AND ctr <= 1', name='ck_gsc_ctr_valid'),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('site_id', 'date', 'url', 'query', 'country', 'device', name='uq_gsc_metric_daily'),
    )
    
    # Create indexes for gsc_metrics table
    op.create_index('ix_gsc_metrics_site_date', 'gsc_metrics', ['site_id', 'date'])
    op.create_index('ix_gsc_metrics_url', 'gsc_metrics', ['url'])
    op.create_index('ix_gsc_metrics_query', 'gsc_metrics', ['query'])
    op.create_index('ix_gsc_metrics_clicks', 'gsc_metrics', ['clicks'])
    op.create_index('ix_gsc_metrics_created_at', 'gsc_metrics', ['created_at'])
    
    # GA4 Metrics table
    op.create_table(
        'ga4_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Reference to the associated website'),
        sa.Column('date', sa.Date(), nullable=False, comment='Date of the metric snapshot'),
        sa.Column('page_path', sa.String(500), nullable=False, comment='Page path that received organic traffic'),
        sa.Column('landing_page', sa.String(500), nullable=True, comment='Landing page for the session'),
        sa.Column('source_medium', sa.String(100), nullable=True, comment='Traffic source and medium (e.g., google / organic)'),
        sa.Column('country', sa.String(2), nullable=True, comment='Country code of the visitor'),
        sa.Column('device_category', sa.String(10), nullable=True, comment='Device category (desktop, mobile, tablet)'),
        sa.Column('sessions', sa.Integer(), nullable=False, server_default='0', comment='Number of sessions for this page'),
        sa.Column('page_views', sa.Integer(), nullable=False, server_default='0', comment='Number of page views'),
        sa.Column('unique_page_views', sa.Integer(), nullable=False, server_default='0', comment='Number of unique page views'),
        sa.Column('bounce_rate', sa.Numeric(5, 4), nullable=True, comment='Bounce rate for sessions starting on this page'),
        sa.Column('avg_session_duration', sa.Integer(), nullable=True, comment='Average session duration in seconds'),
        sa.Column('conversions', sa.Integer(), nullable=False, server_default='0', comment='Number of conversions attributed to this page'),
        sa.Column('revenue', sa.Numeric(10, 2), nullable=True, comment='Revenue attributed to this page'),
        sa.CheckConstraint('sessions >= 0', name='ck_ga4_sessions_positive'),
        sa.CheckConstraint('page_views >= 0', name='ck_ga4_page_views_positive'),
        sa.CheckConstraint('bounce_rate >= 0 AND bounce_rate <= 1', name='ck_ga4_bounce_rate_valid'),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('site_id', 'date', 'page_path', 'source_medium', 'country', 'device_category', name='uq_ga4_metric_daily'),
    )
    
    # Create indexes for ga4_metrics table
    op.create_index('ix_ga4_metrics_site_date', 'ga4_metrics', ['site_id', 'date'])
    op.create_index('ix_ga4_metrics_page_path', 'ga4_metrics', ['page_path'])
    op.create_index('ix_ga4_metrics_sessions', 'ga4_metrics', ['sessions'])
    op.create_index('ix_ga4_metrics_conversions', 'ga4_metrics', ['conversions'])
    op.create_index('ix_ga4_metrics_created_at', 'ga4_metrics', ['created_at'])
    
    # After creating all regular tables, convert time-series tables to TimescaleDB hypertables
    # Use raw SQL execution for TimescaleDB specific operations
    
    # Convert rankings to hypertable (partitioned by date with 7-day chunks)
    op.execute(text("""
        SELECT create_hypertable('rankings', 'date', 
                                 chunk_time_interval => INTERVAL '7 days',
                                 if_not_exists => TRUE);
    """))
    
    # Convert gsc_metrics to hypertable (partitioned by date with 7-day chunks)
    op.execute(text("""
        SELECT create_hypertable('gsc_metrics', 'date', 
                                 chunk_time_interval => INTERVAL '7 days',
                                 if_not_exists => TRUE);
    """))
    
    # Convert ga4_metrics to hypertable (partitioned by date with 7-day chunks)  
    op.execute(text("""
        SELECT create_hypertable('ga4_metrics', 'date', 
                                 chunk_time_interval => INTERVAL '7 days',
                                 if_not_exists => TRUE);
    """))
    
    # Create pgvector index for similarity search on keyword embeddings
    # Note: Using pgvector extension for vector similarity searches
    op.execute(text("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_keywords_embedding_cosine 
        ON keywords USING ivfflat (embedding vector_cosine_ops) 
        WITH (lists = 100);
    """))


def downgrade() -> None:
    """Drop all tables and extensions in reverse order."""
    
    # Drop pgvector index first
    op.drop_index('ix_keywords_embedding_cosine', table_name='keywords')
    
    # Drop time-series tables (hypertables will be automatically dropped)
    op.drop_table('ga4_metrics')
    op.drop_table('gsc_metrics') 
    op.drop_table('rankings')
    
    # Drop regular tables
    op.drop_table('audit_log')
    op.drop_table('keywords')
    op.drop_table('sites')
    
    # Drop enum types
    op.execute("DROP TYPE IF EXISTS approvalstatus")
    op.execute("DROP TYPE IF EXISTS entitytype")
    op.execute("DROP TYPE IF EXISTS actiontype")
    op.execute("DROP TYPE IF EXISTS keywordpriority")
    op.execute("DROP TYPE IF EXISTS keywordintent")
    op.execute("DROP TYPE IF EXISTS cmstype")
    
    # Note: We don't drop extensions as they might be used by other databases
    # Extensions: timescaledb, vector, uuid-ossp will remain
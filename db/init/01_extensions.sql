-- SEO Platform Database Initialization
-- This script creates the required extensions for the SEO automation platform
-- Compatible with TimescaleDB/PostgreSQL image

-- Enable TimescaleDB extension (automatically available in TimescaleDB image)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable pgvector extension for vector embeddings and semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID generation functions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable query performance monitoring
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Log successful initialization
DO $$
BEGIN
    RAISE NOTICE 'SEO Platform extensions initialized successfully';
    RAISE NOTICE 'PostgreSQL version: %', version();
    RAISE NOTICE 'TimescaleDB version: %', (SELECT extversion FROM pg_extension WHERE extname = 'timescaledb');
    RAISE NOTICE 'pgvector version: %', (SELECT extversion FROM pg_extension WHERE extname = 'vector');
END
$$;
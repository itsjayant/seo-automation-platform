#!/bin/bash
set -e

# This script is run automatically when the PostgreSQL container starts for the first time
# It enables the required extensions for the SEO automation platform

echo "Initializing SEO Platform database..."

# Connect to the database and enable extensions
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Enable TimescaleDB extension (TimescaleDB image provides this automatically)
    CREATE EXTENSION IF NOT EXISTS timescaledb;
    
    -- Enable pgvector extension for vector embeddings
    CREATE EXTENSION IF NOT EXISTS vector;
    
    -- Enable additional extensions that are commonly available
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    
    -- Create basic schema for SEO platform
    -- These will be managed by Alembic migrations in later phases
    
    SELECT 'PostgreSQL version: ' || version();
    SELECT 'TimescaleDB version: ' || extversion FROM pg_extension WHERE extname = 'timescaledb';
    SELECT 'pgvector version: ' || extversion FROM pg_extension WHERE extname = 'vector';
EOSQL

echo "Database initialization completed successfully!"
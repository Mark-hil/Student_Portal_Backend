-- Initial PostgreSQL setup for Student Portal
-- Run once on fresh database creation

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- trigram search for courses
CREATE EXTENSION IF NOT EXISTS "btree_gin";     -- GIN indexes on JSONB

-- Set timezone
SET timezone = 'UTC';

-- Connection limits (for PgBouncer compatibility)
ALTER DATABASE portal_db CONNECTION LIMIT 200;

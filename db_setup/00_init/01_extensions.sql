-- ==============================================================================
-- 01_extensions.sql: Required PostgreSQL Extensions
-- ==============================================================================

-- 1. Spatial 3D coordinate support (bounding box <@ and KNN <-> Euclidean distance)
CREATE EXTENSION IF NOT EXISTS cube;

-- 2. Trigram indexing support for fast fuzzy and substring name searches
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ==============================================================================
-- 14__ingested_tables.sql: Pipeline Checkpointing & Progress Tracking Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS _ingested_tables (
    filename TEXT,
    table_name TEXT,
    ingested_at TIMESTAMP,
    PRIMARY KEY (filename, table_name)
);

-- Documentation
COMMENT ON TABLE _ingested_tables IS
  'Pipeline checkpoint table. Tracks which (source file, table) pairs have been fully ingested. '
  'Used by GalaxyIngestor.run() to resume after crashes without re-ingesting completed tables. '
  'One row is inserted per table per source file immediately after that table''s upsert/insert transaction completes. '
  'Composite primary key: (filename, table_name).';

COMMENT ON COLUMN _ingested_tables.filename IS
  'Basename of the source .ndjson chunk file (e.g. "galaxy_split_20250101_0130_part_001.ndjson"). '
  'Part of the composite primary key.';

COMMENT ON COLUMN _ingested_tables.table_name IS
  'Name of the PostgreSQL table that was successfully populated from this file '
  '(e.g. "systems", "bodies", "station_commodities"). Part of the composite primary key.';

COMMENT ON COLUMN _ingested_tables.ingested_at IS
  'UTC timestamp of when this (filename, table_name) pair was marked as completed by the pipeline.';

-- Security: Isolate internal checkpoint tracking from analytical read-only user
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'galaxy_searcher') THEN
        REVOKE SELECT ON TABLE _ingested_tables FROM galaxy_searcher;
    END IF;
END
$$;


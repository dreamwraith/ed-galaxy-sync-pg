-- ==============================================================================
-- 16__raw_debug_log.sql: Generalized EDDN Debug Audit Log Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS _raw_debug_log (
    id BIGSERIAL PRIMARY KEY,
    filter_label TEXT NOT NULL,
    software_name TEXT,
    software_version TEXT,
    uploader_id TEXT,
    schema_ref TEXT,
    event_name TEXT,
    message_timestamp TIMESTAMP,
    received_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    raw_payload JSONB NOT NULL
);

-- Documentation
COMMENT ON TABLE _raw_debug_log IS
  'Audit log capturing full raw EDDN JSON payloads matching configured debug filter rules.';

COMMENT ON COLUMN _raw_debug_log.id IS
  'Auto-incrementing surrogate primary key.';

COMMENT ON COLUMN _raw_debug_log.filter_label IS
  'Configured descriptive tag or rule name (e.g. "MyFilter", "CuratedCommodityHunt").';

COMMENT ON COLUMN _raw_debug_log.software_name IS
  'Software name from the EDDN message header.';

COMMENT ON COLUMN _raw_debug_log.software_version IS
  'Software version from the EDDN message header.';

COMMENT ON COLUMN _raw_debug_log.uploader_id IS
  'MD5 uploader ID hash from the EDDN message header.';

COMMENT ON COLUMN _raw_debug_log.schema_ref IS
  'Full EDDN schema URI (e.g. "https://eddn.edcd.io/schemas/journal/1").';

COMMENT ON COLUMN _raw_debug_log.event_name IS
  'Event name if present (e.g. "Docked", "FSDJump", "FSSSignalDiscovered").';

COMMENT ON COLUMN _raw_debug_log.message_timestamp IS
  'Timestamp from within the message payload.';

COMMENT ON COLUMN _raw_debug_log.received_at IS
  'UTC timestamp when the event was received by the live listener.';

COMMENT ON COLUMN _raw_debug_log.raw_payload IS
  'Complete, unmodified raw JSONB payload received from EDDN.';

-- Security: Isolate debug audit log from analytical read-only user
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'galaxy_searcher') THEN
        REVOKE SELECT ON TABLE _raw_debug_log FROM galaxy_searcher;
    END IF;
END
$$;


-- ==============================================================================
-- 15_eddn_unhandled_events.sql: Dead-Letter Queue (DLQ) Staging Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS eddn_unhandled_events (
    id BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    message_timestamp TIMESTAMP,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    schema_ref TEXT NOT NULL,
    event_name TEXT,
    system_name TEXT,
    station_name TEXT,
    uploader_id TEXT,
    app_name TEXT,
    dlq_reason TEXT DEFAULT 'unhandled_schema',
    raw_message JSONB NOT NULL
);

-- Documentation
COMMENT ON TABLE eddn_unhandled_events IS
  'Dead-Letter Queue (DLQ) and catch-all staging table for newly evolving, experimental, or unmapped EDDN event streams. '
  'Stores raw JSON messages for offline analysis and future schema expansion.';

COMMENT ON COLUMN eddn_unhandled_events.id IS
  'Auto-incrementing surrogate primary key.';

COMMENT ON COLUMN eddn_unhandled_events.received_at IS
  'UTC timestamp when the event was received and recorded by the live EDDN listener daemon.';

COMMENT ON COLUMN eddn_unhandled_events.message_timestamp IS
  'Original UTC timestamp reported within the EDDN message payload, if present.';

COMMENT ON COLUMN eddn_unhandled_events.update_dtm IS
  'Standardized UTC timestamp for row creation or update.';

COMMENT ON COLUMN eddn_unhandled_events.schema_ref IS
  'Full EDDN schema URI (e.g. "https://eddn.edcd.io/schemas/fssdiscoversignals/1").';

COMMENT ON COLUMN eddn_unhandled_events.event_name IS
  'Name of the event (e.g. "FSSSignalDiscovered", "NavRoute", "CarrierJump").';

COMMENT ON COLUMN eddn_unhandled_events.system_name IS
  'Star system name associated with the event if available in the message.';

COMMENT ON COLUMN eddn_unhandled_events.station_name IS
  'Station name associated with the event if available in the message.';

COMMENT ON COLUMN eddn_unhandled_events.uploader_id IS
  'Anonymized or raw uploader ID string from the EDDN message header.';

COMMENT ON COLUMN eddn_unhandled_events.app_name IS
  'Software/Application name from the EDDN message header.';

COMMENT ON COLUMN eddn_unhandled_events.dlq_reason IS
  'Categorized reason for routing to DLQ (e.g. "unhandled_schema", "unhandled_journal_event", "unwhitelisted_software", "legacy_game_version").';

COMMENT ON COLUMN eddn_unhandled_events.raw_message IS
  'Complete, unmodified JSONB payload of the EDDN message for downstream analysis and schema development.';

-- Security: Isolate DLQ raw payloads and uploader metadata from analytical read-only user
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'galaxy_searcher') THEN
        REVOKE SELECT ON TABLE eddn_unhandled_events FROM galaxy_searcher;
    END IF;
END
$$;


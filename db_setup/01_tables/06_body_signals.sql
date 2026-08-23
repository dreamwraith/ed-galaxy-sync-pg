-- ==============================================================================
-- 06_body_signals.sql: Planetary DSS Surface Signals Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS body_signals (
    system_id64 BIGINT,
    body_id64 BIGINT PRIMARY KEY,
    signals JSONB,
    genuses TEXT[],
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc')
);

-- Documentation
COMMENT ON TABLE body_signals IS
  'One row per planet''s surface signal report. '
  'Stores biological and geological signals detected by the Detailed Surface Scanner (DSS). '
  'Flattened from bodies[].signals in galaxy.json. '
  'Primary key: body_id64 (one signal record per body).';

COMMENT ON COLUMN body_signals.system_id64 IS
  'Foreign reference to systems.id64 — the system this body belongs to.';

COMMENT ON COLUMN body_signals.body_id64 IS
  'Foreign reference to bodies.id64. Primary key. Source: parent body context.';

COMMENT ON COLUMN body_signals.signals IS
  'JSONB object mapping signal type name to count (e.g. {"$SAA_SignalType_Biological;": 3}). '
  'Source field: bodies[].signals.signals.';

COMMENT ON COLUMN body_signals.genuses IS
  'TEXT array of Codex genus identifiers for biological signals confirmed on this body '
  '(e.g. "$Codex_Ent_Bacterial_Genus_Name;", "$Codex_Ent_Osseus_Genus_Name;"). '
  'Source field: bodies[].signals.genuses.';

COMMENT ON COLUMN body_signals.update_dtm IS
  'UTC timestamp of when this surface signal discovery record was last updated by the Spansh ingest pipeline or live EDDN stream.';

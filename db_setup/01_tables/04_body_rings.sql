-- ==============================================================================
-- 04_body_rings.sql: Planetary and Stellar Rings Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS body_rings (
    body_id64 BIGINT NOT NULL,
    id64 BIGINT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    mass DOUBLE PRECISION NOT NULL,
    innerradius DOUBLE PRECISION NOT NULL,
    outerradius DOUBLE PRECISION NOT NULL,
    density DOUBLE PRECISION,
    signals JSONB,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (body_id64, name)
);

-- Documentation
COMMENT ON TABLE body_rings IS
  'One row per ring associated with a planet or star. '
  'Rings are distinct from belts — rings orbit planets/stars directly and can contain '
  'mineable hotspot signals. Flattened from bodies[].rings[]. '
  'Composite primary key: (body_id64, name).';

COMMENT ON COLUMN body_rings.body_id64 IS
  'Foreign reference to bodies.id64 — the body this ring encircles.';

COMMENT ON COLUMN body_rings.id64 IS
  'Galactic ID64 of the ring itself, if assigned. May be NULL for older records. '
  'Source field: bodies[].rings[].id64.';

COMMENT ON COLUMN body_rings.name IS
  'Name of the ring (e.g. "Odin A Ring"). Part of the composite primary key. '
  'Source field: bodies[].rings[].name.';

COMMENT ON COLUMN body_rings.type IS
  'Composition type of the ring. Enum: Icy, Metal Rich, Metallic, Rocky. '
  'B-Tree indexed for ring-type filtering. Source field: bodies[].rings[].type.';

COMMENT ON COLUMN body_rings.mass IS
  'Mass of the ring in megatonnes. Source field: bodies[].rings[].mass.';

COMMENT ON COLUMN body_rings.innerradius IS
  'Inner boundary radius of the ring in kilometres from the body centre. '
  'Source field: bodies[].rings[].innerRadius.';

COMMENT ON COLUMN body_rings.outerradius IS
  'Outer boundary radius of the ring in kilometres from the body centre. '
  'Source field: bodies[].rings[].outerRadius.';

COMMENT ON COLUMN body_rings.density IS
  'Computed or estimated density of the ring. May be NULL if not reported. '
  'Not present in galaxy.schema.json enum; populated when available from extended data.';

COMMENT ON COLUMN body_rings.signals IS
  'JSONB key-value mapping of mineable hotspot materials to signal count '
  '(e.g. {"Platinum": 3, "Void Opal": 1}). GIN-indexed for fast '
  'hotspot material searches. NULL when no signals have been reported.';

COMMENT ON COLUMN body_rings.update_dtm IS
  'UTC timestamp of when this ring record was last updated by the Spansh ingest pipeline or live EDDN stream.';

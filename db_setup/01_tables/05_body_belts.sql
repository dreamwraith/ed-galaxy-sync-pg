-- ==============================================================================
-- 05_body_belts.sql: Stellar Asteroid Belts Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS body_belts (
    body_id64 BIGINT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    mass DOUBLE PRECISION NOT NULL,
    innerradius DOUBLE PRECISION NOT NULL,
    outerradius DOUBLE PRECISION NOT NULL,
    density DOUBLE PRECISION,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (body_id64, name)
);

-- Documentation
COMMENT ON TABLE body_belts IS
  'One row per asteroid belt associated with a star. '
  'Belts orbit stars (not planets) and share the same schema as rings but are stored separately '
  'because belts do not carry hotspot signal data. '
  'Flattened from bodies[].belts[]. Composite primary key: (body_id64, name).';

COMMENT ON COLUMN body_belts.body_id64 IS
  'Foreign reference to bodies.id64 — the star body this belt encircles.';

COMMENT ON COLUMN body_belts.name IS
  'Name of the belt (e.g. "Sol A Belt"). Part of the composite primary key. '
  'Source field: bodies[].belts[].name.';

COMMENT ON COLUMN body_belts.type IS
  'Composition type of the belt. Enum: Icy, Metal Rich, Metallic, Rocky. '
  'Source field: bodies[].belts[].type.';

COMMENT ON COLUMN body_belts.mass IS
  'Mass of the belt in megatonnes. Source field: bodies[].belts[].mass.';

COMMENT ON COLUMN body_belts.innerradius IS
  'Inner boundary radius of the belt in kilometres. Source field: bodies[].belts[].innerRadius.';

COMMENT ON COLUMN body_belts.outerradius IS
  'Outer boundary radius of the belt in kilometres. Source field: bodies[].belts[].outerRadius.';

COMMENT ON COLUMN body_belts.density IS
  'Density of the belt material. May be NULL. Not enumerated in galaxy.schema.json.';

COMMENT ON COLUMN body_belts.update_dtm IS
  'UTC timestamp of when this belt record was last updated by the Spansh ingest pipeline or live EDDN stream.';

-- ==============================================================================
-- 13_body_pois.sql: Planetary Surface Points of Interest Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS body_pois (
    system_id64 BIGINT NOT NULL,
    body_id64 BIGINT NOT NULL,
    body_name TEXT,
    poi_type TEXT NOT NULL,
    name TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (body_id64, raw_name)
);

-- Documentation
COMMENT ON TABLE body_pois IS
  'Discrete planetary surface points of interest (Guardian ruins, Thargoid structures, non-market settlements, surface POIs). '
  'Stores exact surface latitude/longitude coordinates and binds to a specific body via body_id64. '
  'Composite primary key: (body_id64, raw_name).';

COMMENT ON COLUMN body_pois.system_id64 IS
  'Galactic ID64 of the parent star system.';

COMMENT ON COLUMN body_pois.body_id64 IS
  'Deterministic 64-bit ID of the parent planetary body ((system_id64 << 9) | body_id). Part of composite primary key.';

COMMENT ON COLUMN body_pois.body_name IS
  'Name of the parent planetary body if known (e.g. "Synuefe EU-Q c21-10 A 3").';

COMMENT ON COLUMN body_pois.poi_type IS
  'Type/category of surface POI. Values: Guardian, Thargoid, Settlement, SurfacePOI, CrashSite.';

COMMENT ON COLUMN body_pois.name IS
  'Human-readable or localized display name of the surface location.';

COMMENT ON COLUMN body_pois.raw_name IS
  'Exact raw symbol or name token (e.g. "$Ancient_Small_002:#index=1;"). Part of composite primary key.';

COMMENT ON COLUMN body_pois.latitude IS
  'Planetary surface latitude in degrees (-90.0 to +90.0).';

COMMENT ON COLUMN body_pois.longitude IS
  'Planetary surface longitude in degrees (-180.0 to +180.0).';

COMMENT ON COLUMN body_pois.update_dtm IS
  'UTC timestamp when this surface POI was last updated.';

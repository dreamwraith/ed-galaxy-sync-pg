-- ==============================================================================
-- 10_station_modules.sql: Station Outfitting Modules Inventory Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS station_modules (
    market_id BIGINT NOT NULL,
    name TEXT,
    symbol TEXT,
    moduleId INTEGER,
    class INTEGER,
    rating TEXT,
    category TEXT,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (market_id, moduleid)
);

-- Documentation
COMMENT ON TABLE station_modules IS
  'One row per outfitting module available at a station. '
  'Flattened from stations[].outfitting.modules[]. '
  'Composite primary key: (market_id, moduleId).';

COMMENT ON COLUMN station_modules.market_id IS
  'Foreign reference to stations.market_id.';

COMMENT ON COLUMN station_modules.name IS
  'Human-readable module name (e.g. "Frame Shift Drive", "Guardian Gauss Cannon"). '
  'Source field: outfitting.modules[].name.';

COMMENT ON COLUMN station_modules.symbol IS
  'Frontier internal symbol/key for the module. Source field: outfitting.modules[].symbol.';

COMMENT ON COLUMN station_modules.moduleId IS
  'Frontier numeric identifier of the module. Part of the composite primary key. '
  'Source field: outfitting.modules[].moduleId.';

COMMENT ON COLUMN station_modules.class IS
  'Module size class (0–8). Lower classes are physically smaller; higher classes are larger. '
  'Source field: outfitting.modules[].class.';

COMMENT ON COLUMN station_modules.rating IS
  'Module performance rating. Enum: E (lowest), D, C, B, A (highest for most modules), '
  'and specialist ratings F, G, H, I. Source field: outfitting.modules[].rating.';

COMMENT ON COLUMN station_modules.category IS
  'Slot category for the module. Enum: hardpoint, internal, utility, standard. '
  'Source field: outfitting.modules[].category.';

COMMENT ON COLUMN station_modules.update_dtm IS
  'UTC timestamp of when this outfitting row was last updated by the Spansh ingest pipeline or live EDDN stream.';

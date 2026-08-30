-- ==============================================================================
-- 09_station_ships.sql: Station Shipyard Ship Inventory Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS station_ships (
    market_id BIGINT NOT NULL,
    name TEXT,
    symbol TEXT,
    shipid INTEGER,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (market_id, shipid)
);

-- Documentation
COMMENT ON TABLE station_ships IS
  'One row per ship available for purchase at a station''s shipyard. '
  'Flattened from stations[].shipyard.ships[]. '
  'Composite primary key: (market_id, shipId).';

COMMENT ON COLUMN station_ships.market_id IS
  'Foreign reference to stations.market_id.';

COMMENT ON COLUMN station_ships.name IS
  'Human-readable ship name (e.g. "Anaconda", "Krait MkII", "Federal Corvette"). '
  'Source field: shipyard.ships[].name.';

COMMENT ON COLUMN station_ships.symbol IS
  'Frontier internal symbol/key for the ship (e.g. "$Anaconda_Name;"). '
  'Source field: shipyard.ships[].symbol.';

COMMENT ON COLUMN station_ships.shipid IS
  'Frontier numeric identifier of the ship. Part of the composite primary key. '
  'Source field: shipyard.ships[].shipId.';

COMMENT ON COLUMN station_ships.update_dtm IS
  'UTC timestamp of when this shipyard row was last updated by the Spansh ingest pipeline or live EDDN stream.';

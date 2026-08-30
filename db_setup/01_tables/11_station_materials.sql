-- ==============================================================================
-- 11_station_materials.sql: Fleet Carrier Odyssey Materials Market & Bartender Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS station_materials (
    market_id BIGINT NOT NULL,
    carrier_id TEXT,
    material_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    symbol TEXT,
    category TEXT,
    stock INTEGER DEFAULT 0,
    demand INTEGER DEFAULT 0,
    buyprice INTEGER DEFAULT 0,
    sellprice INTEGER DEFAULT 0,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (market_id, material_id)
);

-- Documentation
COMMENT ON TABLE station_materials IS
  'One row per Odyssey material listed on a Fleet Carrier Bar / Bartender material exchange. '
  'Sourced from EDDN FCMaterials (Journal & CAPI) feeds. '
  'Composite primary key: (market_id, material_id).';

COMMENT ON COLUMN station_materials.market_id IS
  'Frontier numeric identifier of the Fleet Carrier / Station market.';

COMMENT ON COLUMN station_materials.carrier_id IS
  'Fleet Carrier callsign token (e.g. "V3N-T4K").';

COMMENT ON COLUMN station_materials.material_id IS
  'Frontier numeric material identifier. Part of composite primary key.';

COMMENT ON COLUMN station_materials.name IS
  'Normalized or cleaned display name of the Odyssey material (e.g. "Micro Hydraulics").';

COMMENT ON COLUMN station_materials.symbol IS
  'Raw Frontier symbol token (e.g. "$microhydraulics_name;").';

COMMENT ON COLUMN station_materials.category IS
  'Trade category for the material (Chemicals, Technology, Circuitry, Goods, Data).';

COMMENT ON COLUMN station_materials.stock IS
  'Available units currently in stock for purchase from the carrier.';

COMMENT ON COLUMN station_materials.demand IS
  'Units demanded by the carrier owner.';

COMMENT ON COLUMN station_materials.buyprice IS
  'Price in credits at which the carrier sells material to commanders.';

COMMENT ON COLUMN station_materials.sellprice IS
  'Price in credits at which the carrier buys material from commanders.';

COMMENT ON COLUMN station_materials.update_dtm IS
  'UTC timestamp of when this material inventory was last updated.';

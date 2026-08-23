-- ==============================================================================
-- 08_station_commodities.sql: Station Market Commodity Prices & Supply/Demand Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS station_commodities (
    market_id BIGINT NOT NULL,
    name TEXT,
    symbol TEXT,
    category TEXT,
    commodityId INTEGER,
    demand INTEGER,
    supply INTEGER,
    buyPrice INTEGER,
    sellPrice INTEGER,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (market_id, commodityid)
);

-- Documentation
COMMENT ON TABLE station_commodities IS
  'One row per commodity listed at a station''s market. '
  'Flattened from stations[].market.commodities[]. '
  'Composite primary key: (market_id, commodityId).';

COMMENT ON COLUMN station_commodities.market_id IS
  'Foreign reference to stations.market_id.';

COMMENT ON COLUMN station_commodities.name IS
  'Human-readable commodity name (e.g. "Gold", "Low Temperature Diamonds", "Tritium"). '
  'Source field: market.commodities[].name.';

COMMENT ON COLUMN station_commodities.symbol IS
  'Frontier internal symbol/key for the commodity (e.g. "$Gold_Name;"). '
  'Source field: market.commodities[].symbol.';

COMMENT ON COLUMN station_commodities.category IS
  'Trade category of the commodity. '
  'Enum: Chemicals, Consumer Items, Foods, Industrial Materials, Legal Drugs, Machinery, '
  'Medicines, Metals, Minerals, Salvage, Slavery, Technology, Textiles, Waste, Weapons. '
  'Source field: market.commodities[].category.';

COMMENT ON COLUMN station_commodities.commodityId IS
  'Frontier numeric identifier of the commodity. Part of the composite primary key. '
  'Source field: market.commodities[].commodityId.';

COMMENT ON COLUMN station_commodities.demand IS
  'Station''s demand for this commodity in units. 0 means the station does not buy it. '
  'Source field: market.commodities[].demand.';

COMMENT ON COLUMN station_commodities.supply IS
  'Station''s available supply of this commodity in units. 0 means the station does not sell it. '
  'Source field: market.commodities[].supply.';

COMMENT ON COLUMN station_commodities.buyPrice IS
  'Price in credits at which a player can purchase this commodity from the station. '
  'Source field: market.commodities[].buyPrice.';

COMMENT ON COLUMN station_commodities.sellPrice IS
  'Price in credits at which a player can sell this commodity to the station. '
  'Source field: market.commodities[].sellPrice.';

COMMENT ON COLUMN station_commodities.update_dtm IS
  'UTC timestamp of when this commodity price row was last updated by the Spansh ingest pipeline or live EDDN stream.';

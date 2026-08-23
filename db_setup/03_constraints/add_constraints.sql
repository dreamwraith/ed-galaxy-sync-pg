-- ==============================================================================
-- add_constraints.sql: Re-Add Primary Key Constraints Post-Bulk Ingest
-- ==============================================================================
-- IMPORTANT: If bulk ingestion introduced duplicate rows, PostgreSQL will raise
-- an error. Ensure duplicate rows are pruned prior to executing this script.

ALTER TABLE systems ADD PRIMARY KEY (id64);
ALTER TABLE system_factions ADD PRIMARY KEY (system_id64, name);
ALTER TABLE bodies ADD PRIMARY KEY (id64);
ALTER TABLE body_rings ADD PRIMARY KEY (body_id64, name);
ALTER TABLE body_belts ADD PRIMARY KEY (body_id64, name);
ALTER TABLE body_signals ADD PRIMARY KEY (body_id64);
ALTER TABLE stations ADD PRIMARY KEY (market_id);
ALTER TABLE station_commodities ADD PRIMARY KEY (market_id, commodityId);
ALTER TABLE station_ships ADD PRIMARY KEY (market_id, shipId);
ALTER TABLE station_modules ADD PRIMARY KEY (market_id, moduleId);
ALTER TABLE station_materials ADD PRIMARY KEY (market_id, material_id);
ALTER TABLE system_signals ADD PRIMARY KEY (system_id64, raw_name);
ALTER TABLE body_pois ADD PRIMARY KEY (body_id64, raw_name);
ALTER TABLE _ingested_tables ADD PRIMARY KEY (filename, table_name);

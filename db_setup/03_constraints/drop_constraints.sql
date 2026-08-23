-- ==============================================================================
-- drop_constraints.sql: Drop Primary Key Constraints for Maximum Ingest Speed
-- ==============================================================================
-- OPTIONAL: For clean, non-overlapping raw file loads where constraint checking
-- overhead should be completely eliminated during initial load.

ALTER TABLE systems DROP CONSTRAINT IF EXISTS systems_pkey CASCADE;
ALTER TABLE system_factions DROP CONSTRAINT IF EXISTS system_factions_pkey CASCADE;
ALTER TABLE bodies DROP CONSTRAINT IF EXISTS bodies_pkey CASCADE;
ALTER TABLE body_rings DROP CONSTRAINT IF EXISTS body_rings_pkey CASCADE;
ALTER TABLE body_belts DROP CONSTRAINT IF EXISTS body_belts_pkey CASCADE;
ALTER TABLE body_signals DROP CONSTRAINT IF EXISTS body_signals_pkey CASCADE;
ALTER TABLE stations DROP CONSTRAINT IF EXISTS stations_pkey CASCADE;
ALTER TABLE station_commodities DROP CONSTRAINT IF EXISTS station_commodities_pkey CASCADE;
ALTER TABLE station_ships DROP CONSTRAINT IF EXISTS station_ships_pkey CASCADE;
ALTER TABLE station_modules DROP CONSTRAINT IF EXISTS station_modules_pkey CASCADE;
ALTER TABLE station_materials DROP CONSTRAINT IF EXISTS station_materials_pkey CASCADE;
ALTER TABLE system_signals DROP CONSTRAINT IF EXISTS system_signals_pkey CASCADE;
ALTER TABLE body_pois DROP CONSTRAINT IF EXISTS body_pois_pkey CASCADE;
ALTER TABLE _ingested_tables DROP CONSTRAINT IF EXISTS _ingested_tables_pkey CASCADE;

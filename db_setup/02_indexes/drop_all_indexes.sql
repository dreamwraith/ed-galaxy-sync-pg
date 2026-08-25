-- ==============================================================================
-- drop_all_indexes.sql: Drop Secondary Indexes for Rapid Bulk Ingestion
-- ==============================================================================
-- Run this script BEFORE performing a massive initial database bulk ingest (e.g. 560GB+ dump)
-- to maximize write throughput and eliminate index maintenance overhead.
-- After ingestion completes, run create_all_indexes.sql to rebuild all indexes.
-- 1. systems indexes
DROP INDEX IF EXISTS idx_systems_coords_cube;

DROP INDEX IF EXISTS idx_systems_powers;

DROP INDEX IF EXISTS idx_systems_name;

DROP INDEX IF EXISTS idx_systems_name_lower;

DROP INDEX IF EXISTS idx_systems_name_trgm;

DROP INDEX IF EXISTS idx_systems_controlling_power;

-- 2. bodies indexes
DROP INDEX IF EXISTS idx_bodies_system;

DROP INDEX IF EXISTS idx_bodies_subtype;

DROP INDEX IF EXISTS idx_bodies_reserveLevel;

DROP INDEX IF EXISTS idx_bodies_materials;

DROP INDEX IF EXISTS idx_bodies_atmosphereComposition;

DROP INDEX IF EXISTS idx_bodies_solidComposition;

DROP INDEX IF EXISTS idx_bodies_gravity;

-- 3. body_rings indexes
DROP INDEX IF EXISTS idx_body_rings_type;

DROP INDEX IF EXISTS idx_body_rings_signals;

DROP INDEX IF EXISTS idx_body_rings_type_density;

-- 4. body_signals indexes
DROP INDEX IF EXISTS idx_body_signals_system;

DROP INDEX IF EXISTS idx_body_signals_genuses;

-- 5. stations indexes
DROP INDEX IF EXISTS idx_stations_system;

DROP INDEX IF EXISTS idx_stations_name;

DROP INDEX IF EXISTS idx_stations_name_trgm;

DROP INDEX IF EXISTS idx_stations_type;

DROP INDEX IF EXISTS idx_stations_services;

DROP INDEX IF EXISTS idx_stations_body_source;

-- 6. station_commodities indexes
DROP INDEX IF EXISTS idx_station_commodities_name;

-- 7. station_ships indexes
DROP INDEX IF EXISTS idx_station_ships_name;

-- 8. station_modules indexes
DROP INDEX IF EXISTS idx_station_modules_name_class_rating;

-- 9. station_materials indexes
DROP INDEX IF EXISTS idx_station_materials_name;

DROP INDEX IF EXISTS idx_station_materials_symbol;

DROP INDEX IF EXISTS idx_station_materials_carrier_id;

-- 10. system_signals indexes
DROP INDEX IF EXISTS idx_system_signals_type;

DROP INDEX IF EXISTS idx_system_signals_severity;

DROP INDEX IF EXISTS idx_system_signals_name;

-- 11. body_pois indexes
DROP INDEX IF EXISTS idx_body_pois_system;

DROP INDEX IF EXISTS idx_body_pois_type;

DROP INDEX IF EXISTS idx_body_pois_name;

-- 12. engineers indexes
DROP INDEX IF EXISTS idx_engineers_system;

DROP INDEX IF EXISTS idx_engineers_body;

DROP INDEX IF EXISTS idx_engineers_market;

DROP INDEX IF EXISTS idx_engineers_specialties;

DROP INDEX IF EXISTS idx_engineers_name_trgm;

-- 13. eddn_unhandled_events (DLQ) indexes
DROP INDEX IF EXISTS idx_eddn_unhandled_schema;

DROP INDEX IF EXISTS idx_eddn_unhandled_event;

DROP INDEX IF EXISTS idx_eddn_unhandled_app_name;

DROP INDEX IF EXISTS idx_eddn_unhandled_dlq_reason;

DROP INDEX IF EXISTS idx_eddn_unhandled_received_at;

-- 14. _raw_debug_log indexes
DROP INDEX IF EXISTS idx_raw_debug_log_label;

DROP INDEX IF EXISTS idx_raw_debug_log_software;

DROP INDEX IF EXISTS idx_raw_debug_log_received_at;

DROP INDEX IF EXISTS idx_raw_debug_log_uploader_id;

DROP INDEX IF EXISTS idx_raw_debug_log_event;
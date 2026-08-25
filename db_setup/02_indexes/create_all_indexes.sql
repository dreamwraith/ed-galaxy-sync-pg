-- ==============================================================================
-- create_all_indexes.sql: Secondary, Spatial, Trigram & GIN Search Indexes
-- ==============================================================================
-- 1. systems indexes
CREATE INDEX IF NOT EXISTS idx_systems_coords_cube ON systems USING gist (coords);

CREATE INDEX IF NOT EXISTS idx_systems_powers ON systems USING gin (powers);

CREATE INDEX IF NOT EXISTS idx_systems_name ON systems (name);

CREATE INDEX IF NOT EXISTS idx_systems_name_trgm ON systems USING gin (name gin_trgm_ops);

-- 2. bodies indexes
CREATE INDEX IF NOT EXISTS idx_bodies_system ON bodies (system_id64);

CREATE INDEX IF NOT EXISTS idx_bodies_subtype ON bodies (subtype);

CREATE INDEX IF NOT EXISTS idx_bodies_reserveLevel ON bodies (reserveLevel);

CREATE INDEX IF NOT EXISTS idx_bodies_materials ON bodies USING gin (materials);

CREATE INDEX IF NOT EXISTS idx_bodies_atmosphereComposition ON bodies USING gin (atmosphereComposition);

CREATE INDEX IF NOT EXISTS idx_bodies_solidComposition ON bodies USING gin (solidComposition);

-- 3. body_rings indexes
CREATE INDEX IF NOT EXISTS idx_body_rings_type ON body_rings (type);

CREATE INDEX IF NOT EXISTS idx_body_rings_signals ON body_rings USING gin (signals);

-- 4. station_materials indexes
CREATE INDEX IF NOT EXISTS idx_station_materials_name ON station_materials (name);

CREATE INDEX IF NOT EXISTS idx_station_materials_symbol ON station_materials (symbol);

CREATE INDEX IF NOT EXISTS idx_station_materials_carrier_id ON station_materials (carrier_id);

-- 5. system_signals indexes
CREATE INDEX IF NOT EXISTS idx_system_signals_type ON system_signals (signal_type);

CREATE INDEX IF NOT EXISTS idx_system_signals_severity ON system_signals (severity);

CREATE INDEX IF NOT EXISTS idx_system_signals_name ON system_signals (name);

-- 6. body_pois indexes
CREATE INDEX IF NOT EXISTS idx_body_pois_system ON body_pois (system_id64);

CREATE INDEX IF NOT EXISTS idx_body_pois_type ON body_pois (poi_type);

CREATE INDEX IF NOT EXISTS idx_body_pois_name ON body_pois (name);

-- 7. eddn_unhandled_events (DLQ) indexes
CREATE INDEX IF NOT EXISTS idx_eddn_unhandled_schema ON eddn_unhandled_events (schema_ref);

CREATE INDEX IF NOT EXISTS idx_eddn_unhandled_event ON eddn_unhandled_events (event_name);

CREATE INDEX IF NOT EXISTS idx_eddn_unhandled_app_name ON eddn_unhandled_events (app_name);

CREATE INDEX IF NOT EXISTS idx_eddn_unhandled_dlq_reason ON eddn_unhandled_events (dlq_reason);

CREATE INDEX IF NOT EXISTS idx_eddn_unhandled_received_at ON eddn_unhandled_events (received_at DESC);

-- 8. _raw_debug_log indexes
CREATE INDEX IF NOT EXISTS idx_raw_debug_log_label ON _raw_debug_log (filter_label);

CREATE INDEX IF NOT EXISTS idx_raw_debug_log_software ON _raw_debug_log (software_name);

CREATE INDEX IF NOT EXISTS idx_raw_debug_log_received_at ON _raw_debug_log (received_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_debug_log_uploader_id ON _raw_debug_log (uploader_id);

CREATE INDEX IF NOT EXISTS idx_raw_debug_log_event ON _raw_debug_log (event_name);

-- 9. stations indexes
CREATE INDEX IF NOT EXISTS idx_stations_system ON stations (system_id64);

CREATE INDEX IF NOT EXISTS idx_stations_name ON stations (name);

CREATE INDEX IF NOT EXISTS idx_stations_name_trgm ON stations USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_stations_type ON stations (type);

-- 10. engineers indexes
CREATE INDEX IF NOT EXISTS idx_engineers_system ON engineers (system_id64);

CREATE INDEX IF NOT EXISTS idx_engineers_body ON engineers (body_id64);

CREATE INDEX IF NOT EXISTS idx_engineers_market ON engineers (market_id);

CREATE INDEX IF NOT EXISTS idx_engineers_specialties ON engineers USING gin (specialties);

CREATE INDEX IF NOT EXISTS idx_engineers_name_trgm ON engineers USING gin (name gin_trgm_ops);
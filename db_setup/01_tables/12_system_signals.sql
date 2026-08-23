-- ==============================================================================
-- 12_system_signals.sql: System-Level POIs and Unresolved Signals Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS system_signals (
    system_id64 BIGINT NOT NULL,
    signal_type TEXT NOT NULL,
    name TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    severity TEXT,
    threat_level INTEGER,
    spawning_faction TEXT,
    spawning_state TEXT,
    is_station BOOLEAN DEFAULT FALSE,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (system_id64, raw_name)
);

-- Documentation
COMMENT ON TABLE system_signals IS
  'Persistent and semi-permanent system points of interest (Resource Extraction Sites, Nav Beacons, Conflict Zones, Installations, Megaships, Carrier Signals). '
  'Sourced from EDDN FSSSignalDiscovered messages. '
  'Composite primary key: (system_id64, raw_name).';

COMMENT ON COLUMN system_signals.system_id64 IS
  'Galactic ID64 of the star system where this signal is located.';

COMMENT ON COLUMN system_signals.signal_type IS
  'Categorized signal type (e.g. "Resource Extraction", "Conflict Zone", "FleetCarrier", "Station", "Installation", "Megaship", "NavBeacon").';

COMMENT ON COLUMN system_signals.name IS
  'Cleaned or localized display name of the signal.';

COMMENT ON COLUMN system_signals.raw_name IS
  'Raw signal name token reported by EDDN (e.g. "$FIXED_EVENT_HIGHTHREATRES;"). Part of composite primary key.';

COMMENT ON COLUMN system_signals.severity IS
  'Extracted severity rating if present (e.g. "High", "Low", "Hazardous").';

COMMENT ON COLUMN system_signals.threat_level IS
  'Numeric threat level integer (0-8) if reported.';

COMMENT ON COLUMN system_signals.spawning_faction IS
  'Minor faction associated with this scenario signal.';

COMMENT ON COLUMN system_signals.spawning_state IS
  'BGS state associated with this scenario signal.';

COMMENT ON COLUMN system_signals.is_station IS
  'Boolean flag indicating if the signal represents a dockable station/carrier.';

COMMENT ON COLUMN system_signals.update_dtm IS
  'UTC timestamp of when this system signal was last updated.';

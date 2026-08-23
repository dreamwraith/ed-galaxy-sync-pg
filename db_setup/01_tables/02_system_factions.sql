-- ==============================================================================
-- 02_system_factions.sql: System Minor Factions Presence Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS system_factions (
    system_id64 BIGINT NOT NULL,
    name TEXT NOT NULL,
    state TEXT,
    allegiance TEXT,
    government TEXT,
    influence DOUBLE PRECISION,
    activeStates JSONB,
    pendingStates JSONB,
    recoveringStates JSONB,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (system_id64, name)
);

-- Documentation
COMMENT ON TABLE system_factions IS
  'Normalised faction presence rows — one row per (system, faction) pair. '
  'Flattened from the factions[] array inside each system object in galaxy.json. '
  'Composite primary key: (system_id64, name).';

COMMENT ON COLUMN system_factions.system_id64 IS
  'Foreign reference to systems.id64 — the system this faction is present in.';

COMMENT ON COLUMN system_factions.name IS
  'Name of the minor faction (e.g. "Future of Lave"). Part of the composite primary key. '
  'Source field: factions[].name.';

COMMENT ON COLUMN system_factions.state IS
  'Current BGS state of the faction in this system. '
  'Enum: Blight, Boom, Bust, Civil Liberty, Civil Unrest, Civil War, Drought, Election, '
  'Expansion, Famine, Infrastructure Failure, Investment, Lockdown, Natural Disaster, '
  'None, Outbreak, Pirate Attack, Public Holiday, Retreat, Terrorist Attack, War, or NULL. '
  'Source field: factions[].state.';

COMMENT ON COLUMN system_factions.allegiance IS
  'Allegiance of the faction. Same enum as systems.allegiance. Source field: factions[].allegiance.';

COMMENT ON COLUMN system_factions.government IS
  'Government type of the faction. Same enum as systems.government. Source field: factions[].government.';

COMMENT ON COLUMN system_factions.influence IS
  'Influence share of the faction in this system, in the range 0.0–1.0. '
  'All factions in a system sum to approximately 1.0. Source field: factions[].influence.';

COMMENT ON COLUMN system_factions.activeStates IS
  'JSONB array of currently active BGS states for this faction [{state, trend}, ...]. '
  'Source field: factions[].activeStates.';

COMMENT ON COLUMN system_factions.pendingStates IS
  'JSONB array of pending (upcoming) BGS states for this faction [{state, trend}, ...]. '
  'Source field: factions[].pendingStates.';

COMMENT ON COLUMN system_factions.recoveringStates IS
  'JSONB array of recovering (fading) BGS states for this faction [{state, trend}, ...]. '
  'Source field: factions[].recoveringStates.';

COMMENT ON COLUMN system_factions.update_dtm IS
  'UTC timestamp of when this system faction presence was last updated by the ingest pipeline or live EDDN stream.';

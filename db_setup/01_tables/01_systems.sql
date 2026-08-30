-- ==============================================================================
-- 01_systems.sql: Star Systems Domain Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS systems (
    id64 BIGINT PRIMARY KEY,
    name TEXT,
    coords cube,
    allegiance TEXT,
    government TEXT,
    primaryeconomy TEXT,
    secondaryeconomy TEXT,
    security TEXT,
    population BIGINT,
    bodycount INTEGER,
    controllingpower TEXT,
    powerstate TEXT,
    powerstatecontrolprogress DOUBLE PRECISION,
    powerstatereinforcement DOUBLE PRECISION,
    powerstateundermining DOUBLE PRECISION,
    powers JSONB,
    controllingfaction JSONB,
    powerconflictprogress JSONB,
    thargoidwar JSONB,
    timestamps JSONB,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc')
);

-- Documentation
COMMENT ON TABLE systems IS
  'One row per Elite Dangerous star system. Sourced from the Spansh galaxy dump (galaxy.json). '
  'Each system is uniquely identified by its Galactic ID64. '
  'Coordinates are in light-years relative to Sol (0, 0, 0). '
  'Updated via incremental upsert on id64 conflict.';

COMMENT ON COLUMN systems.id64 IS
  'Galactic ID64 of the system — a 64-bit unsigned integer encoding sector, mass-code, and body offset. '
  'Primary key. Source field: id64.';

COMMENT ON COLUMN systems.name IS
  'Human-readable name of the star system (e.g. "Sol", "Alpha Centauri"). Source field: name.';

COMMENT ON COLUMN systems.coords IS
  '3D galactic coordinates in light-years (ly) relative to Sol, stored as PostgreSQL cube(3D). '
  'Indexed with GiST (idx_systems_coords_cube) for spatial bounding-box (<@) and KNN (<->) queries. '
  'Use system_distance_3d(coords_a, coords_b) or native "<->" operator to compute 3D Euclidean distance. Source field: coords.';

COMMENT ON COLUMN systems.allegiance IS
  'Political allegiance of the system. '
  'Enum: Alliance, Empire, Federation, Frontline Solutions, Guardian, Independent, Pilots Federation, Thargoid, or NULL. '
  'Source field: allegiance.';

COMMENT ON COLUMN systems.government IS
  'Government type of the controlling faction in the system. '
  'Enum: Anarchy, Communism, Confederacy, Cooperative, Corporate, Democracy, Dictatorship, Engineer, '
  'Feudal, Megaconstruction, None, Patronage, Prison, Prison Colony, Private Ownership, Theocracy, or NULL. '
  'Source field: government.';

COMMENT ON COLUMN systems.primaryeconomy IS
  'Primary economy type of the system. '
  'Enum: Agriculture, Colony, Extraction, High Tech, Industrial, Military, None, Prison, '
  'Private Enterprise, Refinery, Repair, Rescue, Service, Terraforming, Tourism, or NULL. '
  'Source field: primaryEconomy.';

COMMENT ON COLUMN systems.secondaryeconomy IS
  'Secondary economy type of the system. Same enum as primaryEconomy. Source field: secondaryEconomy.';

COMMENT ON COLUMN systems.security IS
  'Security rating of the system. Enum: Anarchy, High, Low, Medium. Source field: security.';

COMMENT ON COLUMN systems.population IS
  'Total human population of the system. 0 for uninhabited systems. Source field: population.';

COMMENT ON COLUMN systems.bodycount IS
  'Total number of surveyed planets and stars in the system as reported by Spansh. Source field: bodyCount.';

COMMENT ON COLUMN systems.controllingpower IS
  'Name of the Powerplay power that controls this system, or NULL if uncontrolled. '
  'Enum: Aisling Duval, A. Lavigny-Duval, Archon Delaine, Denton Patreus, Edmund Mahon, '
  'Felicia Winters, Jerome Archer, Li Yong-Rui, Nakato Kaine, Pranav Antal, Yuri Grom, Zemina Torval. '
  'Source field: controllingPower.';

COMMENT ON COLUMN systems.powerstate IS
  'Powerplay state of the system. Enum: Exploited, Fortified, Stronghold, Unoccupied, or NULL. '
  'Source field: powerState.';

COMMENT ON COLUMN systems.powerstatecontrolprogress IS
  'Progress (0.0–1.0) of the controlling power toward fully controlling this system. '
  'Source field: powerStateControlProgress.';

COMMENT ON COLUMN systems.powerstatereinforcement IS
  'Powerplay reinforcement score (>=0) for the system. Source field: powerStateReinforcement.';

COMMENT ON COLUMN systems.powerstateundermining IS
  'Powerplay undermining score (>=0) for the system. Source field: powerStateUndermining.';

COMMENT ON COLUMN systems.powers IS
  'JSONB array of power names (strings) currently exerting influence over this system. '
  'GIN-indexed for membership queries (e.g. powers @> ''["Aisling Duval"]''). '
  'Source field: powers.';

COMMENT ON COLUMN systems.controllingfaction IS
  'JSONB snapshot of the controlling faction object {name, state, allegiance, government, influence, ...}. '
  'Stored as JSONB rather than a foreign key because faction objects are embedded in the source dump '
  'and not normalised. Source field: controllingFaction.';

COMMENT ON COLUMN systems.powerconflictprogress IS
  'JSONB array of {power, progress} objects describing active Powerplay conflict progress in this system. '
  'Each entry maps a power name to its numeric progress value (>=0). '
  'Source field: powerConflictProgress.';

COMMENT ON COLUMN systems.thargoidwar IS
  'JSONB object describing the current Thargoid War state in this system. '
  'Fields: currentState, successState, failureState (enum strings), progress (0–1), '
  'daysRemaining, portsRemaining (numbers), successReached (boolean). '
  'NULL when the system is not involved in a Thargoid War. Source field: thargoidWar.';

COMMENT ON COLUMN systems.timestamps IS
  'JSONB object mapping individual field names to their last-updated UTC timestamp strings. '
  'Allows field-level change tracking within a system record. Source field: timestamps.';

COMMENT ON COLUMN systems.update_dtm IS
  'UTC timestamp of when this system record was last updated by the Spansh ingest pipeline or live EDDN stream.';

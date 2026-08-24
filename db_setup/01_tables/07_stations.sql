-- ==============================================================================
-- 07_stations.sql: Stations, Starports, Outposts & Fleet Carriers Table
-- ==============================================================================

CREATE TABLE IF NOT EXISTS stations (
    source TEXT,
    system_id64 BIGINT NOT NULL,
    body_source_id64 BIGINT,
    market_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    realName TEXT,
    carrierName TEXT,
    type TEXT,
    state TEXT,
    distanceToArrival DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    allegiance TEXT,
    government TEXT,
    controllingFaction TEXT,
    controllingFactionState TEXT,
    primaryEconomy TEXT,
    secondaryEconomy TEXT,
    economies JSONB,
    carrierDockingAccess TEXT,
    pad_large INTEGER,
    pad_medium INTEGER,
    pad_small INTEGER,
    services_arr TEXT[],
    prohibited_commodities TEXT[],
    market_updated_at TIMESTAMP,
    shipyard_updated_at TIMESTAMP,
    outfitting_updated_at TIMESTAMP,
    bartender_updated_at TIMESTAMP,
    update_dtm TIMESTAMP DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (market_id)
);

-- Documentation
COMMENT ON TABLE stations IS
  'One row per station (space station, surface port, fleet carrier, settlement, etc.). '
  'Sourced from both system-level stations[] and body-level stations[] arrays in galaxy.json. '
  'The source column distinguishes which array the row came from. '
  'Primary key: market_id (Frontier''s market/station ID).';

COMMENT ON COLUMN stations.source IS
  'Pipeline source identifier: "system" for stations embedded in the system-level stations[] array, '
  '"body" for stations embedded inside a body''s stations[] array (i.e. planet-based). '
  'Not part of the Spansh schema — added by the ingest pipeline.';

COMMENT ON COLUMN stations.system_id64 IS
  'Foreign reference to systems.id64 — the system the station is located in.';

COMMENT ON COLUMN stations.body_source_id64 IS
  'For planetary surface ports, outposts, and settlements: the body ID or index of the parent body. '
  'Resolves to bodies.id64 (or bodies.bodyId) for celestial linkage. NULL for orbital space stations.';

COMMENT ON COLUMN stations.market_id IS
  'Frontier''s numeric market/station identifier. Globally unique. Primary key. '
  'Source field: stations[].id.';

COMMENT ON COLUMN stations.name IS
  'In-game name of the station (e.g. "Jameson Memorial", "Hutton Orbital"). '
  'Source field: stations[].name.';

COMMENT ON COLUMN stations.realName IS
  'For colonisation-built stations: the ''real'' construction name, which may differ from the '
  'player-assigned display name. Source field: stations[].realName.';

COMMENT ON COLUMN stations.carrierName IS
  'For Drake-Class Fleet Carriers: the player-assigned carrier name (e.g. "DSSA Explorer''s Haven"). '
  'NULL for non-carrier stations. Source field: stations[].carrierName.';

COMMENT ON COLUMN stations.type IS
  'Physical type of the station. '
  'Enum: Asteroid base, Coriolis Starport, Dockable Planet Station, Dodec Starport, '
  'Drake-Class Carrier, Mega ship, Ocellus Starport, Orbis Starport, Outpost, '
  'Planetary Construction Depot, Planetary Outpost, Planetary Port, Settlement, '
  'Space Construction Depot, Surface Settlement. Source field: stations[].type.';

COMMENT ON COLUMN stations.state IS
  'Operational state of the station. '
  'Enum: Construction, Damaged, DamagedHuman, UnderAttack, UnderRepairs, or NULL (operational). '
  'Source field: stations[].state.';

COMMENT ON COLUMN stations.distanceToArrival IS
  'Distance from the system arrival point to this station, in light-seconds (ls). '
  'Source field: stations[].distanceToArrival.';

COMMENT ON COLUMN stations.latitude IS
  'Planetary stations only. Surface latitude of the station in degrees (-90 to +90). '
  'NULL for orbital stations. Source field: stations[].latitude.';

COMMENT ON COLUMN stations.longitude IS
  'Planetary stations only. Surface longitude of the station in degrees (-180 to +180). '
  'NULL for orbital stations. Source field: stations[].longitude.';

COMMENT ON COLUMN stations.allegiance IS
  'Allegiance of the station. Same enum as systems.allegiance. Source field: stations[].allegiance.';

COMMENT ON COLUMN stations.government IS
  'Government type of the station. Same enum as systems.government. Source field: stations[].government.';

COMMENT ON COLUMN stations.controllingFaction IS
  'Name of the minor faction that controls this station. Source field: stations[].controllingFaction.';

COMMENT ON COLUMN stations.controllingFactionState IS
  'BGS state of the controlling faction at this station. Same state enum as system_factions.state. '
  'Source field: stations[].controllingFactionState.';

COMMENT ON COLUMN stations.primaryEconomy IS
  'Primary economy type of the station. Same enum as systems.primaryEconomy. '
  'Source field: stations[].primaryEconomy.';

COMMENT ON COLUMN stations.secondaryEconomy IS
  'Secondary economy type of the station. Same enum as systems.primaryEconomy. '
  'Source field: stations[].secondaryEconomy.';

COMMENT ON COLUMN stations.economies IS
  'JSONB object mapping economy type name to its proportional share at this station '
  '(e.g. {"High Tech": 0.75, "Industrial": 0.25}). Source field: stations[].economies.';

COMMENT ON COLUMN stations.carrierDockingAccess IS
  'Fleet carriers only. Docking permission setting: "all", "friends", "squadron", etc. '
  'Source field: stations[].carrierDockingAccess.';

COMMENT ON COLUMN stations.pad_large IS
  'Number of large landing pads at this station. Source field: stations[].landingPads.large.';

COMMENT ON COLUMN stations.pad_medium IS
  'Number of medium landing pads at this station. Source field: stations[].landingPads.medium.';

COMMENT ON COLUMN stations.pad_small IS
  'Number of small landing pads at this station. Source field: stations[].landingPads.small.';

COMMENT ON COLUMN stations.services_arr IS
  'TEXT array of services available at this station. '
  'Values include: Market, Shipyard, Outfitting, Refuel, Repair, Restock, Black Market, '
  'Universal Cartographics, Contacts, Crew Lounge, Bartender, Vista Genomics, '
  'Fleet Carrier Management, Frontline Solutions, etc. '
  'Source field: stations[].services.';

COMMENT ON COLUMN stations.prohibited_commodities IS
  'TEXT array of commodity names that are illegal and cannot be traded at this station. '
  'Source field: stations[].market.prohibitedCommodities.';

COMMENT ON COLUMN stations.market_updated_at IS
  'UTC timestamp of the last update to this station''s commodity market data. '
  'Source field: stations[].market.updateTime.';

COMMENT ON COLUMN stations.shipyard_updated_at IS
  'UTC timestamp of the last update to this station''s shipyard inventory. '
  'Source field: stations[].shipyard.updateTime.';

COMMENT ON COLUMN stations.outfitting_updated_at IS
  'UTC timestamp of the last update to this station''s outfitting module inventory. '
  'Source field: stations[].outfitting.updateTime.';

COMMENT ON COLUMN stations.bartender_updated_at IS
  'UTC timestamp of the last update to this station''s bartender material exchange. '
  'Source field: stations[].bartender.updateTime.';

COMMENT ON COLUMN stations.update_dtm IS
  'UTC timestamp of when this station record was last updated by the Spansh ingest pipeline or live EDDN stream.';

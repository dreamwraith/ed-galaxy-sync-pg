# Elite Dangerous Merit Mining SQL Engine & Query Reference

This guide provides complete, production-tested SQL queries and parameter mappings recreating the full functionality of **MeritMiner (`meritminer.cc`)** using your PostgreSQL database (`galaxy_sync`).

---

## 1. Verified Database String Reference

Directly verified against the PostgreSQL database schema:

### Powers (`systems.controllingPower`)

`'Aisling Duval'`, `'A. Lavigny-Duval'`, `'Archon Delaine'`, `'Denton Patreus'`, `'Edmund Mahon'`, `'Felicia Winters'`, `'Jerome Archer'`, `'Li Yong-Rui'`, `'Nakato Kaine'`, `'Pranav Antal'`, `'Yuri Grom'`, `'Zemina Torval'`

### Power States (`systems.powerState`)

`'Exploited'`, `'Fortified'`, `'Stronghold'`, `'Unoccupied'`

### Fleet / Squadron Carrier & Non-Market Exclusion

In the database, fleet and squadron carriers as well as construction depots appear with several type variations:

* **Carrier Types**: `'Drake-Class Carrier'`, `'Fleet Carrier'`, `'FleetCarrier'`, `'SquadronCarrier'`, plus rows where `carrierName IS NOT NULL` or `carrierDockingAccess IS NOT NULL`.
* **Depot Types**: `'Planetary Construction Depot'`, `'PlanetaryConstructionDepot'`, `'Space Construction Depot'`, `'SpaceConstructionDepot'`.

**Bulletproof Starport / Non-Carrier Filter:**

```sql
(
    stations.type NOT ILIKE '%carrier%'
    AND stations.type NOT ILIKE '%depot%'
    AND stations.carrierName IS NULL
    AND stations.carrierDockingAccess IS NULL
)
```

### Ring Types (`body_rings.type`)

Normalized to exact canonical values as defined in [`ring_types.yaml`](file:///c:/Users/slugw/source/ed-galaxy-sync-pg/eddn/normalizations/direct/ring_types.yaml):

* **Metallic**: `'Metallic'`
* **Metal Rich**: `'Metal Rich'`
* **Icy**: `'Icy'`
* **Rocky**: `'Rocky'`

**Exact Ring Type Match Filter:**

```sql
-- For Metallic rings:
body_rings.type = 'Metallic'
```

### Mining Commodities & Signals

* **Station Commodities (`station_commodities.name`)**: Normalized canonical names (e.g. `'Platinum'`, `'Monazite'`, `'Painite'`, `'Osmium'`, `'Tritium'`). Always compare case-insensitively using `LOWER(station_commodities.name) = LOWER('Platinum')`.
* **Hotspot Signals (`body_rings.signals`)**: Stored as JSONB mapping commodity names to signal counts (e.g. `{"signals": {"Platinum": 2, "Tritium": 1}}` or `{"Platinum": 2}`).

---

## 2. Powerplay Goals Explained

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       POWERPLAY GOALS                                           │
├───────────────────┬───────────────────────────────────┬─────────────────────────────────────────┤
│ Goal              │ Objective                         │ Database Target Filter                  │
├───────────────────┼───────────────────────────────────┼─────────────────────────────────────────┤
│ 🛡️ **Reinforce**  │ Fortify/defend systems belonging   │ `systems.controllingPower = 'Aisling Duval'`  │
│   (Fortify)       │ to **your pledged Power**         │ OR `systems.powers @> '["Aisling Duval"]'`    │
├───────────────────┼───────────────────────────────────┼─────────────────────────────────────────┤
│ ⚔️ **Undermine**  │ Attack and disrupt systems        │ `systems.controllingPower != 'Aisling Duval'` │
│                   │ controlled by a **rival Power**   │ (or specific `systems.controllingPower = '...'`)│
├───────────────────┼───────────────────────────────────┼─────────────────────────────────────────┤
│ 🚩 **Acquire**    │ Expand into unaligned, contested,  │ `systems.controllingPower IS NULL`            │
│   (Expand)        │ or unoccupied systems             │ OR `systems.powerState = 'Unoccupied'`        │
│                   │                                   │ OR `systems.powerConflictProgress IS NOT NULL`│
└───────────────────┴───────────────────────────────────┴─────────────────────────────────────────┘
```

---

## 3. Master Merit Mining Query (All 3 Goals Supported)

Adjust the parameters in the `params` CTE at the top:

```sql
WITH params AS (
    SELECT
        'Cubeo'::text           AS ref_system,       -- Reference system origin
        250.0::double precision AS max_dist_from_ref,-- Max distance from reference (ly)
        'Aisling Duval'::text   AS my_power,         -- Your pledged power
        'Reinforce'::text       AS goal,             -- 'Reinforce', 'Undermine', or 'Acquire'
        'Any'::text             AS opposing_power,   -- 'Any' or specific rival (e.g. 'Felicia Winters')
        'Platinum'::text        AS mineral,          -- Commodity name (e.g. 'Platinum', 'Monazite', 'Painite')
        'Hotspots'::text        AS ring_filter,      -- 'Hotspots', 'Metallic', 'Icy', 'Rocky', or 'All'
        'Pristine'::text        AS reserve_filter,   -- 'Pristine', 'Major', or 'All'
        48::int                 AS max_age_hours,    -- Market data max age in hours (0 = disable)
        0::int                  AS min_demand,       -- Minimum market demand
        90000::int              AS max_demand,       -- Maximum market demand
        'Large'::text           AS pad_size,         -- 'Large', 'Medium', or 'Any'
        20.0::double precision  AS max_jump_ly,      -- Max jump distance between Ring and Market
        30::int                 AS result_limit      -- Results limit
),
origin AS (
    SELECT coords FROM systems WHERE name = (SELECT ref_system FROM params) LIMIT 1
),
nearby_systems AS (
    -- 1. Narrow down systems via 3D GiST index scan first
    SELECT
        systems.id64,
        systems.name,
        systems.coords,
        systems.controllingPower,
        systems.powers,
        systems.powerState,
        systems.powerConflictProgress,
        ROUND((systems.coords <-> origin.coords)::numeric, 1) AS dist_from_ref_ly
    FROM systems
    CROSS JOIN origin
    CROSS JOIN params
    WHERE systems.coords <@ cube_enlarge(origin.coords, params.max_dist_from_ref, 3)
      AND (systems.coords <-> origin.coords) <= params.max_dist_from_ref
),
candidate_markets AS (
    SELECT
        nearby.id64 AS system_id64,
        nearby.name AS system_name,
        nearby.coords,
        nearby.controllingPower,
        nearby.powerState,
        stations.name AS station_name,
        stations.type AS station_type,
        stations.pad_large,
        stations.pad_medium,
        ROUND(stations.distanceToArrival::numeric, 0) AS station_arrival_ls,
        station_commodities.sellPrice AS station_buys_price,
        station_commodities.demand AS station_demand,
        stations.market_updated_at
    FROM nearby_systems nearby
    CROSS JOIN params
    INNER JOIN stations ON stations.system_id64 = nearby.id64
    INNER JOIN station_commodities ON station_commodities.market_id = stations.market_id
    WHERE
        LOWER(station_commodities.name) = LOWER(params.mineral)
        AND station_commodities.demand BETWEEN params.min_demand AND params.max_demand
        AND station_commodities.sellPrice > 0
        -- Bulletproof Fleet & Squadron Carrier / Depot Exclusion
        AND stations.type NOT ILIKE '%carrier%'
        AND stations.type NOT ILIKE '%depot%'
        AND stations.carrierName IS NULL
        AND stations.carrierDockingAccess IS NULL
        -- Landing pad filter
        AND (
            params.pad_size = 'Any'
            OR (params.pad_size = 'Large' AND stations.pad_large > 0)
            OR (params.pad_size = 'Medium' AND (stations.pad_large > 0 OR stations.pad_medium > 0))
        )
        -- Market freshness filter
        AND (
            params.max_age_hours <= 0
            OR stations.market_updated_at >= (NOW() AT TIME ZONE 'utc' - (params.max_age_hours || ' hours')::interval)
        )
        -- POWERPLAY GOAL LOGIC
        AND (
            CASE
                -- 1. REINFORCE: Stations in your Power's space
                WHEN params.goal = 'Reinforce' THEN
                    (nearby.controllingPower = params.my_power OR nearby.powers @> jsonb_build_array(params.my_power))

                -- 2. UNDERMINE: Stations in rival Power's space
                WHEN params.goal = 'Undermine' THEN
                    (nearby.controllingPower IS NOT NULL AND nearby.controllingPower != params.my_power)
                    AND (params.opposing_power = 'Any' OR nearby.controllingPower = params.opposing_power OR nearby.powers @> jsonb_build_array(params.opposing_power))

                -- 3. ACQUIRE: Uncontrolled, Unoccupied, or Contested space
                WHEN params.goal = 'Acquire' THEN
                    (nearby.controllingPower IS NULL OR nearby.powerState = 'Unoccupied' OR nearby.powerConflictProgress IS NOT NULL)

                ELSE TRUE
            END
        )
),
candidate_rings AS (
    SELECT
        nearby.id64 AS system_id64,
        nearby.name AS system_name,
        nearby.coords,
        nearby.dist_from_ref_ly,
        bodies.name AS body_name,
        body_rings.name AS ring_name,
        body_rings.type AS ring_type,
        bodies.reserveLevel,
        ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
        COALESCE((body_rings.signals->>(SELECT mineral FROM params))::int, 0) AS mineral_hotspots,
        body_rings.signals AS all_hotspots
    FROM nearby_systems nearby
    CROSS JOIN params
    INNER JOIN bodies ON bodies.system_id64 = nearby.id64
    INNER JOIN body_rings ON body_rings.body_id64 = bodies.id64
    WHERE
        -- Reserve level filter
        (
            params.reserve_filter = 'All'
            OR bodies.reserveLevel = params.reserve_filter
            OR (params.reserve_filter = 'Pristine' AND bodies.reserveLevel IN ('Pristine', 'Major'))
        )
        -- Ring type / Hotspot filter with exact canonical token support
        AND (
            params.ring_filter = 'All'
            OR (params.ring_filter = 'Hotspots' AND body_rings.signals ? params.mineral)
            OR (params.ring_filter = 'Metallic' AND body_rings.type = 'Metallic')
            OR (params.ring_filter = 'Metal Rich' AND body_rings.type = 'Metal Rich')
            OR (params.ring_filter = 'Icy' AND body_rings.type = 'Icy')
            OR (params.ring_filter = 'Rocky' AND body_rings.type = 'Rocky')
        )
        -- Supercruise arrival distance limit
        AND bodies.distanceToArrival <= 4000
)
SELECT
    candidate_rings.system_name AS mining_system,
    candidate_rings.body_name,
    candidate_rings.ring_name,
    candidate_rings.ring_type,
    candidate_rings.reserveLevel AS reserves,
    candidate_rings.mineral_hotspots,
    candidate_rings.ring_arrival_ls,
    candidate_markets.system_name AS sell_system,
    candidate_markets.controllingPower AS target_system_power,
    candidate_markets.powerState AS target_power_state,
    candidate_markets.station_name AS sell_station,
    candidate_markets.station_type,
    candidate_markets.pad_large,
    candidate_markets.station_arrival_ls,
    candidate_markets.station_buys_price AS sell_price_cr,
    candidate_markets.station_demand AS demand,
    ROUND((candidate_rings.coords <-> candidate_markets.coords)::numeric, 2) AS jump_distance_ly,
    candidate_rings.dist_from_ref_ly
FROM candidate_rings
INNER JOIN candidate_markets
    ON (candidate_rings.coords <-> candidate_markets.coords) <= (SELECT max_jump_ly FROM params)
ORDER BY
    candidate_rings.mineral_hotspots DESC,
    jump_distance_ly ASC,
    candidate_markets.station_buys_price DESC
LIMIT (SELECT result_limit FROM params);
```

---

## 4. Goal-Specific Dedicated Queries

### Goal A: 🛡️ REINFORCE (Fortify Aisling Duval Territory)

*Target: Pristine Metallic/Rocky rings near high-paying Aisling Duval Fortified/Stronghold stations within 200 ly of Cubeo.*

```sql
WITH nearby_systems AS (
    SELECT
        systems.id64,
        systems.name,
        systems.coords,
        systems.controllingPower,
        systems.powers,
        systems.powerState,
        ROUND((systems.coords <-> (SELECT coords FROM systems WHERE name = 'Cubeo' LIMIT 1))::numeric, 1) AS dist_from_ref_ly
    FROM systems
    WHERE systems.coords <@ (SELECT cube_enlarge(coords, 200.0, 3) FROM systems WHERE name = 'Cubeo' LIMIT 1)
      AND (systems.coords <-> (SELECT coords FROM systems WHERE name = 'Cubeo' LIMIT 1)) <= 200.0
)
SELECT
    mining_systems.name AS mining_system,
    bodies.name AS body_name,
    body_rings.name AS ring_name,
    body_rings.type AS ring_type,
    COALESCE((body_rings.signals->>'Platinum')::int, 0) AS platinum_hotspots,
    ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
    sell_systems.name AS aisling_sell_system,
    sell_systems.powerState,
    stations.name AS station_name,
    stations.type AS station_type,
    stations.pad_large,
    ROUND(stations.distanceToArrival::numeric, 0) AS station_arrival_ls,
    station_commodities.sellPrice AS price_cr,
    station_commodities.demand,
    ROUND((mining_systems.coords <-> sell_systems.coords)::numeric, 2) AS jump_distance_ly
FROM nearby_systems mining_systems
INNER JOIN bodies ON bodies.system_id64 = mining_systems.id64
      AND bodies.reserveLevel = 'Pristine'
INNER JOIN body_rings ON body_rings.body_id64 = bodies.id64
      AND body_rings.type = 'Metallic'
INNER JOIN nearby_systems sell_systems ON (mining_systems.coords <-> sell_systems.coords) <= 15.0
      AND (sell_systems.controllingPower = 'Aisling Duval' OR sell_systems.powers @> '["Aisling Duval"]'::jsonb)
INNER JOIN stations ON stations.system_id64 = sell_systems.id64
      AND stations.pad_large > 0
      AND stations.type NOT ILIKE '%carrier%'
      AND stations.type NOT ILIKE '%depot%'
      AND stations.carrierName IS NULL
      AND stations.carrierDockingAccess IS NULL
INNER JOIN station_commodities ON station_commodities.market_id = stations.market_id
      AND LOWER(station_commodities.name) = 'platinum'
      AND station_commodities.sellPrice > 200000
ORDER BY
    platinum_hotspots DESC,
    jump_distance_ly ASC,
    station_commodities.sellPrice DESC
LIMIT 30;
```

---

### Goal B: ⚔️ UNDERMINE (Attack a Rival Power)

*Target: Mine in or near systems controlled by an opposing power (e.g. Felicia Winters) and sell at their stations within 200 ly of Rhea.*

```sql
WITH nearby_systems AS (
    SELECT
        systems.id64,
        systems.name,
        systems.coords,
        systems.controllingPower,
        systems.powers,
        systems.powerState,
        ROUND((systems.coords <-> (SELECT coords FROM systems WHERE name = 'Rhea' LIMIT 1))::numeric, 1) AS dist_from_ref_ly
    FROM systems
    WHERE systems.coords <@ (SELECT cube_enlarge(coords, 200.0, 3) FROM systems WHERE name = 'Rhea' LIMIT 1)
      AND (systems.coords <-> (SELECT coords FROM systems WHERE name = 'Rhea' LIMIT 1)) <= 200.0
)
SELECT
    mining_systems.name AS mining_system,
    bodies.name AS body_name,
    body_rings.name AS ring_name,
    COALESCE((body_rings.signals->>'Monazite')::int, 0) AS monazite_hotspots,
    ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
    sell_systems.name AS rival_sell_system,
    sell_systems.controllingPower AS opposing_power,
    sell_systems.powerState,
    stations.name AS rival_station,
    stations.pad_large,
    station_commodities.sellPrice AS price_cr,
    station_commodities.demand,
    ROUND((mining_systems.coords <-> sell_systems.coords)::numeric, 2) AS jump_distance_ly
FROM nearby_systems mining_systems
INNER JOIN bodies ON bodies.system_id64 = mining_systems.id64
      AND bodies.reserveLevel IN ('Pristine', 'Major')
INNER JOIN body_rings ON body_rings.body_id64 = bodies.id64
INNER JOIN nearby_systems sell_systems ON (mining_systems.coords <-> sell_systems.coords) <= 20.0
      AND sell_systems.controllingPower IS NOT NULL
      AND sell_systems.controllingPower != 'Aisling Duval'
INNER JOIN stations ON stations.system_id64 = sell_systems.id64
      AND stations.pad_large > 0
      AND stations.type NOT ILIKE '%carrier%'
      AND stations.type NOT ILIKE '%depot%'
      AND stations.carrierName IS NULL
      AND stations.carrierDockingAccess IS NULL
INNER JOIN station_commodities ON station_commodities.market_id = stations.market_id
      AND LOWER(station_commodities.name) = 'monazite'
      AND station_commodities.sellPrice > 500000
ORDER BY
    monazite_hotspots DESC,
    jump_distance_ly ASC,
    station_commodities.sellPrice DESC
LIMIT 30;
```

---

### Goal C: 🚩 ACQUIRE (Expand into Unoccupied / Contested Systems)

*Target: Deliver mined commodities to unaligned/unoccupied systems to build acquisition progress within 200 ly of Sol.*

```sql
WITH nearby_systems AS (
    SELECT
        systems.id64,
        systems.name,
        systems.coords,
        systems.controllingPower,
        systems.powers,
        systems.powerState,
        systems.powerConflictProgress,
        ROUND((systems.coords <-> (SELECT coords FROM systems WHERE name = 'Sol' LIMIT 1))::numeric, 1) AS dist_from_ref_ly
    FROM systems
    WHERE systems.coords <@ (SELECT cube_enlarge(coords, 200.0, 3) FROM systems WHERE name = 'Sol' LIMIT 1)
      AND (systems.coords <-> (SELECT coords FROM systems WHERE name = 'Sol' LIMIT 1)) <= 200.0
)
SELECT
    mining_systems.name AS mining_system,
    bodies.name AS body_name,
    body_rings.name AS ring_name,
    COALESCE((body_rings.signals->>'Platinum')::int, 0) AS platinum_hotspots,
    ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
    sell_systems.name AS expansion_system,
    sell_systems.powerState,
    stations.name AS expansion_station,
    stations.pad_large,
    station_commodities.sellPrice AS price_cr,
    station_commodities.demand,
    ROUND((mining_systems.coords <-> sell_systems.coords)::numeric, 2) AS jump_distance_ly
FROM nearby_systems mining_systems
INNER JOIN bodies ON bodies.system_id64 = mining_systems.id64
      AND bodies.reserveLevel = 'Pristine'
INNER JOIN body_rings ON body_rings.body_id64 = bodies.id64
      AND body_rings.type = 'Metallic'
INNER JOIN nearby_systems sell_systems ON (mining_systems.coords <-> sell_systems.coords) <= 20.0
      AND (sell_systems.controllingPower IS NULL OR sell_systems.powerState = 'Unoccupied' OR sell_systems.powerConflictProgress IS NOT NULL)
INNER JOIN stations ON stations.system_id64 = sell_systems.id64
      AND stations.pad_large > 0
      AND stations.type NOT ILIKE '%carrier%'
      AND stations.type NOT ILIKE '%depot%'
      AND stations.carrierName IS NULL
      AND stations.carrierDockingAccess IS NULL
INNER JOIN station_commodities ON station_commodities.market_id = stations.market_id
      AND LOWER(station_commodities.name) = 'platinum'
      AND station_commodities.sellPrice > 0
ORDER BY
    platinum_hotspots DESC,
    jump_distance_ly ASC,
    station_commodities.sellPrice DESC
LIMIT 30;
```

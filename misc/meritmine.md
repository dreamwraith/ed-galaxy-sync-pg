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

The database contains canonical display labels (from `NormalizerManager`) as well as raw Frontier tokens:

* **Metallic**: `'Metallic'`, `'eRingClass_Metalic'`
* **Metal Rich**: `'Metal Rich'`, `'eRingClass_MetalRich'`
* **Icy**: `'Icy'`, `'eRingClass_Icy'`
* **Rocky**: `'Rocky'`, `'eRingClass_Rocky'`

**Ring Type Match Filter:**

```sql
-- For Metallic rings:
(body_rings.type IN ('Metallic', 'eRingClass_Metalic') OR body_rings.type ILIKE '%metallic%')
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
        'Sol'::text             AS ref_system,       -- Reference system origin
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
    SELECT coords FROM systems WHERE LOWER(name) = LOWER((SELECT ref_system FROM params)) LIMIT 1
),
candidate_markets AS (
    SELECT 
        systems.id64 AS system_id64,
        systems.name AS system_name,
        systems.coords,
        systems.controllingPower,
        systems.powerState,
        stations.name AS station_name,
        stations.type AS station_type,
        stations.pad_large,
        stations.pad_medium,
        ROUND(stations.distanceToArrival::numeric, 0) AS station_arrival_ls,
        station_commodities.sellPrice AS station_buys_price,
        station_commodities.demand AS station_demand,
        stations.market_updated_at
    FROM systems
    CROSS JOIN params
    JOIN stations ON stations.system_id64 = systems.id64
    JOIN station_commodities ON station_commodities.market_id = stations.market_id
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
                    (systems.controllingPower = params.my_power OR systems.powers @> jsonb_build_array(params.my_power))
                
                -- 2. UNDERMINE: Stations in rival Power's space
                WHEN params.goal = 'Undermine' THEN 
                    (systems.controllingPower IS NOT NULL AND systems.controllingPower != params.my_power)
                    AND (params.opposing_power = 'Any' OR systems.controllingPower = params.opposing_power OR systems.powers @> jsonb_build_array(params.opposing_power))
                
                -- 3. ACQUIRE: Uncontrolled, Unoccupied, or Contested space
                WHEN params.goal = 'Acquire' THEN 
                    (systems.controllingPower IS NULL OR systems.powerState = 'Unoccupied' OR systems.powerConflictProgress IS NOT NULL)
                
                ELSE TRUE
            END
        )
),
candidate_rings AS (
    SELECT 
        systems.id64 AS system_id64,
        systems.name AS system_name,
        systems.coords,
        bodies.name AS body_name,
        body_rings.name AS ring_name,
        body_rings.type AS ring_type,
        bodies.reserveLevel,
        ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
        COALESCE(
            (body_rings.signals->'signals'->>(SELECT mineral FROM params))::int,
            (body_rings.signals->>(SELECT mineral FROM params))::int,
            0
        ) AS mineral_hotspots,
        body_rings.signals AS all_hotspots
    FROM systems
    CROSS JOIN params
    JOIN bodies ON bodies.system_id64 = systems.id64
    JOIN body_rings ON body_rings.body_id64 = bodies.id64
    WHERE 
        -- Reserve level filter
        (
            params.reserve_filter = 'All' 
            OR bodies.reserveLevel = params.reserve_filter
            OR (params.reserve_filter = 'Pristine' AND bodies.reserveLevel IN ('Pristine', 'Major'))
        )
        -- Ring type / Hotspot filter with frontier token support
        AND (
            params.ring_filter = 'All'
            OR (params.ring_filter = 'Hotspots' AND (body_rings.signals ? params.mineral OR body_rings.signals->'signals' ? params.mineral))
            OR (params.ring_filter = 'Metallic' AND (body_rings.type IN ('Metallic', 'eRingClass_Metalic') OR body_rings.type ILIKE '%metallic%'))
            OR (params.ring_filter = 'Metal Rich' AND (body_rings.type IN ('Metal Rich', 'eRingClass_MetalRich') OR body_rings.type ILIKE '%metalrich%'))
            OR (params.ring_filter = 'Icy' AND (body_rings.type IN ('Icy', 'eRingClass_Icy') OR body_rings.type ILIKE '%icy%'))
            OR (params.ring_filter = 'Rocky' AND (body_rings.type IN ('Rocky', 'eRingClass_Rocky') OR body_rings.type ILIKE '%rocky%'))
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
    ROUND((candidate_rings.coords <-> origin.coords)::numeric, 1) AS dist_from_ref_ly
FROM candidate_rings
CROSS JOIN origin
JOIN candidate_markets 
    -- Maximum jump distance between ring and market
    ON (candidate_rings.coords <-> candidate_markets.coords) <= (SELECT max_jump_ly FROM params)
WHERE 
    -- Maximum distance from reference system
    (candidate_rings.coords <-> origin.coords) <= (SELECT max_dist_from_ref FROM params)
ORDER BY 
    candidate_rings.mineral_hotspots DESC,
    jump_distance_ly ASC,
    candidate_markets.station_buys_price DESC
LIMIT (SELECT result_limit FROM params);
```

---

## 4. Goal-Specific Dedicated Queries

### Goal A: 🛡️ REINFORCE (Fortify Aisling Duval Territory)

*Target: Pristine Metallic/Rocky rings near high-paying Aisling Duval Fortified/Stronghold stations.*

```sql
SELECT 
    mining_sys.name AS mining_system,
    bodies.name AS body_name,
    body_rings.name AS ring_name,
    body_rings.type AS ring_type,
    COALESCE(
        (body_rings.signals->'signals'->>'Platinum')::int,
        (body_rings.signals->>'Platinum')::int,
        0
    ) AS platinum_hotspots,
    ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
    sell_sys.name AS aisling_sell_system,
    sell_sys.powerState,
    stations.name AS station_name,
    stations.type AS station_type,
    stations.pad_large,
    ROUND(stations.distanceToArrival::numeric, 0) AS station_arrival_ls,
    station_commodities.sellPrice AS price_cr,
    station_commodities.demand,
    ROUND((mining_sys.coords <-> sell_sys.coords)::numeric, 2) AS jump_distance_ly
FROM systems mining_sys
JOIN bodies ON bodies.system_id64 = mining_sys.id64
JOIN body_rings ON body_rings.body_id64 = bodies.id64
JOIN systems sell_sys ON (mining_sys.coords <-> sell_sys.coords) <= 15.0 -- <= 1 Jump
JOIN stations ON stations.system_id64 = sell_sys.id64
JOIN station_commodities ON station_commodities.market_id = stations.market_id
WHERE 
    -- Selling station must be in Aisling Duval space
    (sell_sys.controllingPower = 'Aisling Duval' OR sell_sys.powers @> '["Aisling Duval"]'::jsonb)
    -- Mining site criteria
    AND bodies.reserveLevel = 'Pristine'
    AND (body_rings.type IN ('Metallic', 'eRingClass_Metalic') OR body_rings.type ILIKE '%metallic%')
    -- Market criteria
    AND LOWER(station_commodities.name) = 'platinum'
    AND station_commodities.sellPrice > 200000
    AND stations.pad_large > 0
    -- Carrier & Depot exclusion
    AND stations.type NOT ILIKE '%carrier%' 
    AND stations.type NOT ILIKE '%depot%'
    AND stations.carrierName IS NULL 
    AND stations.carrierDockingAccess IS NULL
ORDER BY 
    platinum_hotspots DESC,
    jump_distance_ly ASC,
    station_commodities.sellPrice DESC
LIMIT 30;
```

---

### Goal B: ⚔️ UNDERMINE (Attack a Rival Power)

*Target: Mine in or near systems controlled by an opposing power (e.g. Felicia Winters) and sell at their stations to undermine their influence.*

```sql
SELECT 
    mining_sys.name AS mining_system,
    bodies.name AS body_name,
    body_rings.name AS ring_name,
    COALESCE(
        (body_rings.signals->'signals'->>'Monazite')::int,
        (body_rings.signals->>'Monazite')::int,
        0
    ) AS monazite_hotspots,
    ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
    sell_sys.name AS rival_sell_system,
    sell_sys.controllingPower AS opposing_power,
    sell_sys.powerState,
    stations.name AS rival_station,
    stations.pad_large,
    station_commodities.sellPrice AS price_cr,
    station_commodities.demand,
    ROUND((mining_sys.coords <-> sell_sys.coords)::numeric, 2) AS jump_distance_ly
FROM systems mining_sys
JOIN bodies ON bodies.system_id64 = mining_sys.id64
JOIN body_rings ON body_rings.body_id64 = bodies.id64
JOIN systems sell_sys ON (mining_sys.coords <-> sell_sys.coords) <= 20.0
JOIN stations ON stations.system_id64 = sell_sys.id64
JOIN station_commodities ON station_commodities.market_id = stations.market_id
WHERE 
    -- Target rival power systems (e.g. Felicia Winters, or ANY rival power)
    sell_sys.controllingPower IS NOT NULL
    AND sell_sys.controllingPower != 'Aisling Duval'
    -- To target a specific rival, uncomment:
    -- AND sell_sys.controllingPower = 'Felicia Winters'
    
    -- Mining site criteria
    AND bodies.reserveLevel IN ('Pristine', 'Major')
    -- Market criteria
    AND LOWER(station_commodities.name) = 'monazite'
    AND station_commodities.sellPrice > 500000
    AND stations.pad_large > 0
    -- Carrier & Depot exclusion
    AND stations.type NOT ILIKE '%carrier%' 
    AND stations.type NOT ILIKE '%depot%'
    AND stations.carrierName IS NULL 
    AND stations.carrierDockingAccess IS NULL
ORDER BY 
    monazite_hotspots DESC,
    jump_distance_ly ASC,
    station_commodities.sellPrice DESC
LIMIT 30;
```

---

### Goal C: 🚩 ACQUIRE (Expand into Unoccupied / Contested Systems)

*Target: Deliver mined commodities to unaligned/unoccupied systems to build acquisition progress.*

```sql
SELECT 
    mining_sys.name AS mining_system,
    bodies.name AS body_name,
    body_rings.name AS ring_name,
    COALESCE(
        (body_rings.signals->'signals'->>'Platinum')::int,
        (body_rings.signals->>'Platinum')::int,
        0
    ) AS platinum_hotspots,
    ROUND(bodies.distanceToArrival::numeric, 0) AS ring_arrival_ls,
    sell_sys.name AS expansion_system,
    sell_sys.powerState,
    stations.name AS expansion_station,
    stations.pad_large,
    station_commodities.sellPrice AS price_cr,
    station_commodities.demand,
    ROUND((mining_sys.coords <-> sell_sys.coords)::numeric, 2) AS jump_distance_ly
FROM systems mining_sys
JOIN bodies ON bodies.system_id64 = mining_sys.id64
JOIN body_rings ON body_rings.body_id64 = bodies.id64
JOIN systems sell_sys ON (mining_sys.coords <-> sell_sys.coords) <= 20.0
JOIN stations ON stations.system_id64 = sell_sys.id64
JOIN station_commodities ON station_commodities.market_id = stations.market_id
WHERE 
    -- Systems currently Unoccupied, Uncontrolled, or undergoing active Power Conflict
    (sell_sys.controllingPower IS NULL OR sell_sys.powerState = 'Unoccupied' OR sell_sys.powerConflictProgress IS NOT NULL)
    
    -- Mining site criteria
    AND bodies.reserveLevel = 'Pristine'
    AND (body_rings.type IN ('Metallic', 'eRingClass_Metalic') OR body_rings.type ILIKE '%metallic%')
    -- Market criteria
    AND LOWER(station_commodities.name) = 'platinum'
    AND station_commodities.sellPrice > 0
    AND stations.pad_large > 0
    -- Carrier & Depot exclusion
    AND stations.type NOT ILIKE '%carrier%' 
    AND stations.type NOT ILIKE '%depot%'
    AND stations.carrierName IS NULL 
    AND stations.carrierDockingAccess IS NULL
ORDER BY 
    platinum_hotspots DESC,
    jump_distance_ly ASC,
    station_commodities.sellPrice DESC
LIMIT 30;
```

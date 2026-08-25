# Elite Dangerous Galactic Analytics & Exploration Query Ideas

A curated collection of **deep analytical, astrophysical, geopolitical, and economic queries** designed to run against your PostgreSQL database (`galaxy_sync`).

Combining **3D spatial indexing (`cube` / GiST)**, **orbital mechanics**, **planetary geology/exobiology**, **real-time BGS geopolitics**, and **commodity market economics**, these queries uncover unique records and exploration targets across millions of star systems and celestial bodies.

---

## 🌌 1. Astrophysical Extremes & Cosmic Curiosities

*The "Guinness Book of Galactic Records" across surveyed bodies.*

### A. The "Pancake Death Trap" (Extreme High-G Landable Worlds)

* **The Concept:** Find landable planets with extreme gravitational forces where even light thrusting will crash your ship.
* **Why it's cool:** High-stakes flight challenges and exploration waypoints.
* **The Query:**

  ```sql
  SELECT
      systems.name AS system_name,
      top_bodies.name AS body_name,
      top_bodies.subType,
      ROUND(top_bodies.gravity::numeric, 2) AS gravity_g,
      top_bodies.earthMasses,
      ROUND(top_bodies.radius::numeric, 0) AS radius_km,
      ROUND(top_bodies.distanceToArrival::numeric, 1) AS distance_ls
  FROM (
      -- Uses idx_bodies_gravity to scan from top gravity downward, stopping after 15 landable worlds
      SELECT *
      FROM bodies
      WHERE isLandable = TRUE
        AND gravity > 4.0
      ORDER BY gravity DESC
      LIMIT 15
  ) top_bodies
  INNER JOIN systems ON systems.id64 = top_bodies.system_id64;
  ```

---

### B. The "Skimming the Surface" Ultra-Close Binary Orbits

* **The Concept:** Planets or stars with sub-hour orbital periods or tiny semi-major axes orbiting black holes, neutron stars, or white dwarfs.
* **Why it's cool:** These create cinematic in-game views where celestial bodies visibly move across the skybox in real time.
* **The Query:**

  ```sql
  WITH ultra_fast_orbits AS (
      -- Pre-sort top 20 fastest orbits first, avoiding an expensive self-join across all bodies
      SELECT
          system_id64,
          name,
          subType,
          orbitalPeriod,
          semiMajorAxis,
          orbitalEccentricity,
          (parents->0->>'Star')::bigint AS parent_star_id
      FROM bodies
      WHERE orbitalPeriod > 0
        AND orbitalPeriod < 0.2  -- Under ~4.8 hours
      ORDER BY orbitalPeriod ASC
      LIMIT 20
  )
  SELECT
      systems.name AS system_name,
      orbit.name AS body_name,
      orbit.subType,
      ROUND((orbit.orbitalPeriod * 24 * 60)::numeric, 1) AS orbital_period_minutes,
      ROUND(orbit.semiMajorAxis::numeric, 0) AS semi_major_axis_km,
      orbit.orbitalEccentricity,
      parent_body.subType AS parent_subType
  FROM ultra_fast_orbits orbit
  INNER JOIN systems ON systems.id64 = orbit.system_id64
  LEFT JOIN bodies parent_body ON parent_body.system_id64 = orbit.system_id64
       AND parent_body.bodyId = orbit.parent_star_id;
  ```

---

### C. Ring Titans (Rings that Dwarf Solar Systems)

* **The Concept:** Find planets or stars encircled by gigantic ring structures whose outer radius extends millions of kilometers into space.
* **Why it's cool:** Class I gas giants or brown dwarfs with rings wider than the orbit of Jupiter.
* **The Query:**

  ```sql
  SELECT
      systems.name AS system_name,
      bodies.name AS body_name,
      top_rings.name AS ring_name,
      top_rings.type AS ring_type,
      ROUND((top_rings.outerRadius - top_rings.innerRadius)::numeric, 0) AS ring_span_km,
      ROUND((top_rings.outerRadius / 149597870.7)::numeric, 3) AS outer_radius_au,
      top_rings.mass AS mass_megatonnes
  FROM (
      -- Pre-sort top 15 rings first to avoid joining 1.1M bodies/systems rows
      SELECT *
      FROM body_rings
      ORDER BY (outerRadius - innerRadius) DESC
      LIMIT 15
  ) top_rings
  INNER JOIN bodies ON bodies.id64 = top_rings.body_id64
  INNER JOIN systems ON systems.id64 = bodies.system_id64;
  ```

---

## 🌿 2. Exobiology Goldmines & Odyssey Expeditions

*For cataloging rare alien life and high-value biological DSS payouts.*

### A. The "Botanical Rosetta Stone" (Hyper-Biodiverse Worlds)

* **The Concept:** Planets with 6 to 9+ distinct biological genera living under extreme atmospheric conditions.
* **Why it's cool:** In *Elite Dangerous Odyssey*, landing on a single world with multiple biological genera yields tens of millions in Vista Genomics payouts.
* **The Query:**

  ```sql
  SELECT
      systems.name AS system_name,
      bodies.name AS planet_name,
      bodies.atmosphereType,
      bodies.gravity,
      bodies.surfaceTemperature,
      cardinality(body_signals.genuses) AS genus_count,
      body_signals.genuses
  FROM body_signals
  INNER JOIN bodies ON bodies.id64 = body_signals.body_id64
  INNER JOIN systems ON systems.id64 = body_signals.system_id64
  WHERE cardinality(body_signals.genuses) >= 6
  ORDER BY genus_count DESC, bodies.gravity DESC
  LIMIT 20;
  ```

---

### B. Life in the Inferno / Cryo-Extremophiles

* **The Concept:** Biological life flourishing on planets with extreme surface temperatures (< 40K cryo-worlds or > 500K boiling atmospheres).
* **The Query:**

  ```sql
  SELECT
      systems.name AS system_name,
      bodies.name AS body_name,
      bodies.subType,
      bodies.surfaceTemperature AS temp_kelvin,
      bodies.atmosphereType,
      body_signals.genuses
  FROM body_signals
  INNER JOIN bodies ON bodies.id64 = body_signals.body_id64
  INNER JOIN systems ON systems.id64 = body_signals.system_id64
  WHERE (bodies.surfaceTemperature > 500 OR bodies.surfaceTemperature < 50)
    AND cardinality(body_signals.genuses) > 0
  ORDER BY bodies.surfaceTemperature DESC
  LIMIT 25;
  ```

---

## 🏡 3. Real Estate Scout: "Paradise Worlds" & Scenic Skyline Index

*Finding dream candidate systems for colonization, scenic screenshots, or squad bases.*

### A. The "Multi-Earth-Like" & Terraforming Cluster

* **The Concept:** Systems containing 2+ Earth-like Worlds (ELWs) or 4+ Terraformable worlds in one star system.
* **The Query:**

  ```sql
  WITH candidate_bodies AS (
      -- Filter to only relevant planet types first, avoiding a 150M row full join
      SELECT
          system_id64,
          subType,
          terraformingState
      FROM bodies
      WHERE subType = 'Earth-like World'
         OR terraformingState IN ('Terraformable', 'Terraforming', 'Terraformed')
  ),
  aggregated_systems AS (
      SELECT
          system_id64,
          COUNT(*) FILTER (WHERE subType = 'Earth-like World') AS elw_count,
          COUNT(*) FILTER (WHERE terraformingState IN ('Terraformable', 'Terraforming', 'Terraformed')) AS terraformable_count
      FROM candidate_bodies
      GROUP BY system_id64
      HAVING COUNT(*) FILTER (WHERE subType = 'Earth-like World') >= 2
          OR COUNT(*) FILTER (WHERE terraformingState IN ('Terraformable', 'Terraforming', 'Terraformed')) >= 4
  )
  SELECT
      systems.name AS system_name,
      systems.population,
      systems.allegiance,
      agg.elw_count,
      agg.terraformable_count,
      ROUND((systems.coords <-> cube(ARRAY[0,0,0]::double precision[]))::numeric, 1) AS distance_from_sol_ly
  FROM aggregated_systems agg
  INNER JOIN systems ON systems.id64 = agg.system_id64
  ORDER BY agg.elw_count DESC, agg.terraformable_count DESC
  LIMIT 25;
  ```

---

### B. The "Massive Skyfill" Scenic Screenshot Spot

* **The Concept:** A landable moon orbiting a ringed gas giant or water world at an extremely tight orbital radius (< 80,000 km).
* **Why it's cool:** The massive ringed giant fills almost the entire skybox when standing on the surface.
* **The Query:**

  ```sql
  WITH tight_moons AS (
      -- Pre-filter rare tight landable moons first to eliminate 150M row scan
      SELECT
          id64,
          system_id64,
          name AS moon_name,
          semiMajorAxis,
          gravity,
          (parents->0->>'Planet')::bigint AS parent_body_id
      FROM bodies
      WHERE isLandable = TRUE
        AND semiMajorAxis > 0
        AND semiMajorAxis < 100000 -- Under 100,000 km
        AND parents->0 ? 'Planet'
  )
  SELECT
      systems.name AS system_name,
      moon.moon_name,
      parent_giant.name AS parent_giant_name,
      parent_giant.subType AS giant_type,
      ROUND(moon.semiMajorAxis::numeric, 0) AS moon_orbit_radius_km,
      ROUND(moon.gravity::numeric, 2) AS moon_gravity,
      EXISTS(SELECT 1 FROM body_rings WHERE body_rings.body_id64 = parent_giant.id64) AS parent_has_rings
  FROM tight_moons moon
  INNER JOIN bodies parent_giant ON parent_giant.system_id64 = moon.system_id64
        AND parent_giant.bodyId = moon.parent_body_id
        AND parent_giant.subType ILIKE '%gas giant%'
  INNER JOIN systems ON systems.id64 = moon.system_id64
  ORDER BY moon.semiMajorAxis ASC
  LIMIT 25;
  ```

---

## ⚔️ 4. Geopolitics, BGS Espionage & Thargoid War Frontlines

*Analyzing human power struggles, isolated fringe colonies, and warzones.*

### A. The "Hermit Kingdom" (Most Isolated Inhabited Systems)

* **The Concept:** Inhabited systems with human populations located hundreds of light-years away from any neighboring civilization.
* **Why it's cool:** Uses 3D Euclidean KNN distance spatial queries (`<->`) to measure civic isolation in the black.
* **The Query:**

  ```sql
  SELECT
      host_sys.name AS isolated_system,
      host_sys.population,
      ROUND((host_sys.coords <-> cube(ARRAY[0,0,0]::double precision[]))::numeric, 1) AS dist_to_sol_ly,
      nearest.nearest_neighbor_dist_ly
  FROM systems host_sys
  -- Directly referencing systems activates idx_systems_coords_cube for GiST KNN nearest-neighbor scan
  CROSS JOIN LATERAL (
      SELECT ROUND((host_sys.coords <-> neighbor.coords)::numeric, 1) AS nearest_neighbor_dist_ly
      FROM systems neighbor
      WHERE neighbor.id64 != host_sys.id64
        AND neighbor.population > 1000
      ORDER BY host_sys.coords <-> neighbor.coords
      LIMIT 1
  ) nearest
  WHERE host_sys.population > 1000
  ORDER BY nearest.nearest_neighbor_dist_ly DESC
  LIMIT 15;
  ```

---

### B. The "Total Anarchy" Pirate Strongholds

* **The Concept:** Starports situated in true Anarchy space featuring active Black Markets, zero prohibited items, and shipyard support.
* **The Query:**

  ```sql
  SELECT
      systems.name AS system_name,
      stations.name AS station_name,
      stations.type AS station_type,
      stations.controllingFaction,
      systems.security,
      stations.pad_large,
      ROUND(stations.distanceToArrival::numeric, 1) AS distance_ls
  FROM stations
  INNER JOIN systems ON systems.id64 = stations.system_id64
  WHERE systems.government = 'Anarchy'
    AND systems.security = 'Anarchy'
    AND stations.services_arr @> ARRAY['Black Market', 'Shipyard']::varchar[]  -- Uses GIN index (idx_stations_services)
    AND stations.pad_large > 0
    AND cardinality(stations.prohibited_commodities) = 0
  ORDER BY systems.population DESC
  LIMIT 20;
  ```

---

### C. Active Thargoid War Frontline Systems

* **The Concept:** Systems actively involved in Thargoid War operations with damaged starports and invasion progress.
* **The Query:**

  ```sql
  SELECT
      systems.name AS system_name,
      stations.name AS station_name,
      stations.state AS station_state,
      systems.thargoidWar->>'currentState' AS war_state,
      (systems.thargoidWar->>'progress')::numeric AS war_progress,
      systems.thargoidWar->>'portsRemaining' AS ports_left,
      ROUND((systems.coords <-> cube(ARRAY[0,0,0]::double precision[]))::numeric, 1) AS ly_from_sol
  FROM stations
  INNER JOIN systems ON systems.id64 = stations.system_id64
  WHERE stations.state IN ('Damaged', 'UnderAttack', 'UnderRepairs')
     OR systems.thargoidWar IS NOT NULL
  ORDER BY war_progress ASC, systems.population DESC
  LIMIT 25;
  ```

---

## 💎 5. High-Yield Mining & Market Arbitrage Triangulation

*Combining planetary ring hotspot scans with live commodity market demands.*

### A. The "Pristine Multi-Hotspot" Platinum / Tritium Fields

* **The Concept:** Pristine metallic or icy rings that contain multiple overlapping signals of lucrative ores (Platinum, Painite, Tritium, Void Opals).
* **The Query:**

  ```sql
  WITH multi_hotspots AS (
      -- Uses GIN index (idx_body_rings_signals) to isolate high-yield candidate rings first
      SELECT
          body_id64,
          name AS ring_name,
          COALESCE((signals->>'Platinum')::int, 0) AS platinum_hotspots,
          COALESCE((signals->>'Tritium')::int, 0) AS tritium_hotspots
      FROM body_rings
      WHERE (signals ? 'Platinum' OR signals ? 'Tritium')
        AND (
          COALESCE((signals->>'Platinum')::int, 0) >= 2 OR
          COALESCE((signals->>'Tritium')::int, 0) >= 2
        )
      ORDER BY platinum_hotspots DESC, tritium_hotspots DESC
      LIMIT 25
  )
  SELECT
      systems.name AS system_name,
      bodies.name AS planet_name,
      hotspots.ring_name,
      bodies.reserveLevel,
      hotspots.platinum_hotspots,
      hotspots.tritium_hotspots,
      ROUND(bodies.distanceToArrival::numeric, 1) AS distance_ls
  FROM multi_hotspots hotspots
  INNER JOIN bodies ON bodies.id64 = hotspots.body_id64
        AND bodies.reserveLevel = 'Pristine'
  INNER JOIN systems ON systems.id64 = bodies.system_id64
  ORDER BY hotspots.platinum_hotspots DESC, hotspots.tritium_hotspots DESC;
  ```

---

### B. High-Profit Spatial Trade Run (Within 40 Light-Years of Anchor)

* **The Concept:** Find high-supply commodities at Station A and pair them with high-demand buy prices at Station B within a standard single-jump hauler radius (40 ly of reference system, e.g. Cubeo) with Large landing pad support.
* **Planner Optimization (Single-Query Model):** Uses an uncorrelated scalar subquery (`InitPlan`) to resolve reference anchor coordinates once, driving a direct **3D GiST Index Scan** on `idx_systems_coords_cube` in the CTE. This filters candidate stations down to a local cluster before joining market commodities, turning a galaxy-wide Cartesian product into a sub-millisecond local search.
* **The Query:**

  ```sql
  WITH nearby_systems AS (
      SELECT
          systems.id64,
          systems.name,
          systems.coords,
          -- Use exact '=' for direct B-Tree lookup (idx_systems_name), or ILIKE for case-insensitive/wildcard searches (idx_systems_name_trgm)
          ROUND((systems.coords <-> (SELECT coords FROM systems WHERE name = 'Cubeo' LIMIT 1))::numeric, 2) AS dist_from_anchor_ly
      FROM systems
      -- Use exact '=' for direct B-Tree lookup (idx_systems_name), or ILIKE for case-insensitive/wildcard searches (idx_systems_name_trgm)
      WHERE
          systems.coords <@ (SELECT cube_enlarge(coords, 40.0, 3) FROM systems WHERE name = 'Cubeo' LIMIT 1)
          AND (systems.coords <-> (SELECT coords FROM systems WHERE name = 'Cubeo' LIMIT 1)) <= 40.0
  )
  SELECT
      sell_commodities.name AS commodity,
      origin_systems.name AS origin_system,
      origin_stations.name AS buy_station,
      sell_commodities.buyPrice AS purchase_cost,
      sell_commodities.supply AS available_supply,
      destination_systems.name AS destination_system,
      destination_stations.name AS sell_station,
      buy_commodities.sellPrice AS station_payout,
      (buy_commodities.sellPrice - sell_commodities.buyPrice) AS profit_per_ton,
      ROUND((origin_systems.coords <-> destination_systems.coords)::numeric, 1) AS distance_ly
  FROM nearby_systems origin_systems
  INNER JOIN stations origin_stations ON origin_stations.system_id64 = origin_systems.id64
        AND origin_stations.pad_large > 0
        AND origin_stations.type NOT ILIKE '%carrier%'
        AND origin_stations.carrierName IS NULL
  INNER JOIN station_commodities sell_commodities ON sell_commodities.market_id = origin_stations.market_id
        AND sell_commodities.supply >= 1000
        AND sell_commodities.buyPrice > 0
  INNER JOIN nearby_systems destination_systems ON destination_systems.id64 != origin_systems.id64
        AND (origin_systems.coords <-> destination_systems.coords) <= 40.0
  INNER JOIN stations destination_stations ON destination_stations.system_id64 = destination_systems.id64
        AND destination_stations.pad_large > 0
        AND destination_stations.market_id != origin_stations.market_id
        AND destination_stations.type NOT ILIKE '%carrier%'
        AND destination_stations.carrierName IS NULL
  INNER JOIN station_commodities buy_commodities ON buy_commodities.market_id = destination_stations.market_id
        AND buy_commodities.commodityid = sell_commodities.commodityid
        AND buy_commodities.demand >= 500
        AND buy_commodities.sellPrice > sell_commodities.buyPrice
  ORDER BY profit_per_ton DESC
  LIMIT 15;
  ```

---

### C. The "Dual-Yield Mining Haven" (Pristine Metallic Platinum + Icy Void Opal Hotspots)

* **The Concept:** Find star systems within a radial search area (e.g. 300 ly of Cubeo) that offer both high-yield laser mining (**Pristine Metallic rings with Platinum hotspots**) and high-value deep-core mining (**Icy rings with Void Opal hotspots**) in the exact same system.
* **Planner Optimization (Single-Query Model):** Uses uncorrelated scalar subqueries (`InitPlan`) to resolve reference origin coordinates and 3D bounding box constants once before query execution. This completely eliminates temporary table setup, prevents join inversion, and forces direct **GiST Index Scans** on `idx_systems_coords_cube` followed by top-down index nested loops.
* **The Query:**

  ```sql
  WITH nearby_systems AS (
      SELECT
          systems.id64,
          systems.name,
          systems.coords,
          systems.allegiance,
          systems.security,
          systems.population,
          systems.controllingPower,
          -- Use exact '=' for direct B-Tree lookup (idx_systems_name), or ILIKE for case-insensitive/wildcard searches (idx_systems_name_trgm)
          ROUND((systems.coords <-> (SELECT coords FROM systems WHERE name = 'Cubeo' LIMIT 1))::numeric, 2) AS distance_ly
      FROM systems
      -- Use exact '=' for direct B-Tree lookup (idx_systems_name), or ILIKE for case-insensitive/wildcard searches (idx_systems_name_trgm)
      WHERE
          systems.coords <@ (SELECT cube_enlarge(coords, 300.0, 3) FROM systems WHERE name = 'Cubeo' LIMIT 1)
          AND (systems.coords <-> (SELECT coords FROM systems WHERE name = 'Cubeo' LIMIT 1)) <= 300.0
  )
  SELECT
      nearby_systems.name AS system_name,
      nearby_systems.distance_ly AS dist_from_ref_ly,
      nearby_systems.allegiance,
      nearby_systems.security,
      nearby_systems.controllingPower AS power,
      metallic_body.name AS metallic_body,
      metallic_ring.name AS metallic_ring,
      metallic_body.reserveLevel AS reserves,
      COALESCE((metallic_ring.signals->>'Platinum')::int, 0) AS platinum_hotspots,
      TO_CHAR(metallic_ring.density * 1000000.0, 'FM999,999,990.000000') AS metallic_density_ton_km2,
      ROUND(metallic_body.distanceToArrival::numeric, 0) AS metallic_arrival_ls,
      icy_body.name AS icy_body,
      icy_ring.name AS icy_ring,
      COALESCE((icy_ring.signals->>'Void Opal')::int, 0) AS void_opal_hotspots,
      TO_CHAR(icy_ring.density * 1000000.0, 'FM999,999,990.000000') AS icy_density_ton_km2,
      ROUND(icy_body.distanceToArrival::numeric, 0) AS icy_arrival_ls
  FROM nearby_systems
  INNER JOIN bodies metallic_body ON metallic_body.system_id64 = nearby_systems.id64
        AND (metallic_body.reserveLevel IS NULL OR metallic_body.reserveLevel IN ('Pristine', 'Major'))
  INNER JOIN body_rings metallic_ring ON metallic_ring.body_id64 = metallic_body.id64
        AND metallic_ring.type = 'Metallic'
        AND COALESCE((metallic_ring.signals->>'Platinum')::int, 0) > 0
  INNER JOIN bodies icy_body ON icy_body.system_id64 = nearby_systems.id64
  INNER JOIN body_rings icy_ring ON icy_ring.body_id64 = icy_body.id64
        AND icy_ring.type = 'Icy'
        AND COALESCE((icy_ring.signals->>'Void Opal')::int, 0) > 0
  ORDER BY
      metallic_ring.density DESC NULLS LAST,
      icy_ring.density DESC NULLS LAST,
      nearby_systems.distance_ly ASC,
      platinum_hotspots DESC,
      void_opal_hotspots DESC;
  ```

---

## 📐 6. 3D Galactic Architecture & "Cartographic Extremes"

*Analyzing the macro-structure of the galaxy.*

### A. The "Crown & Root" of the Explored Galaxy (Extreme Coordinates)

* **The Concept:** Find the absolute highest ceiling (maximum Z), lowest floor (minimum Z), and outermost rim stars ever surveyed by players.
* **The Query:**

  ```sql
  (
      SELECT 'Highest Star (+Z)' AS extreme_type, name, coords, population, bodyCount
      FROM systems ORDER BY (coords ~> 3) DESC LIMIT 1
  )
  UNION ALL
  (
      SELECT 'Lowest Star (-Z)' AS extreme_type, name, coords, population, bodyCount
      FROM systems ORDER BY (coords ~> 3) ASC LIMIT 1
  )
  UNION ALL
  (
      SELECT 'Furthest East (+X)' AS extreme_type, name, coords, population, bodyCount
      FROM systems ORDER BY (coords ~> 1) DESC LIMIT 1
  )
  UNION ALL
  (
      SELECT 'Furthest West (-X)' AS extreme_type, name, coords, population, bodyCount
      FROM systems ORDER BY (coords ~> 1) ASC LIMIT 1
  )
  UNION ALL
  (
      SELECT 'Furthest North (+Y)' AS extreme_type, name, coords, population, bodyCount
      FROM systems ORDER BY (coords ~> 2) DESC LIMIT 1
  )
  UNION ALL
  (
      SELECT 'Furthest South (-Y)' AS extreme_type, name, coords, population, bodyCount
      FROM systems ORDER BY (coords ~> 2) ASC LIMIT 1
  );
  ```

---

### B. The "Neutron Star Highway" High-Density Hubs

* **The Concept:** Find spheres of space with the highest concentration of Neutron Stars or White Dwarfs within a 40 ly radius (ideal for chain supercharging FSD jumps).
* **Planner Optimization:** Pre-filters candidate systems with neutron/white dwarf stars in a CTE, then drives a **3D GiST Index Scan** (`idx_systems_coords_cube`) with `cube_enlarge` in a `CROSS JOIN LATERAL` block to count neighbors in milliseconds.
* **The Query:**

  ```sql
  WITH neutron_systems AS (
      -- Pre-filter systems containing Neutron Stars / White Dwarfs first
      SELECT DISTINCT systems.id64, systems.name, systems.coords
      FROM bodies
      INNER JOIN systems ON systems.id64 = bodies.system_id64
      WHERE bodies.subType IN ('Neutron Star', 'White Dwarf (DA) Star', 'White Dwarf (DAB) Star')
  )
  SELECT
      center.name AS center_system,
      nearby.neutron_neighbors_within_40ly,
      ROUND((center.coords <-> cube(ARRAY[0,0,0]::double precision[]))::numeric, 1) AS dist_from_sol_ly
  FROM neutron_systems center
  -- Uses 3D GiST bounding box index scan on coords for fast local cluster counting
  CROSS JOIN LATERAL (
      SELECT COUNT(*) AS neutron_neighbors_within_40ly
      FROM neutron_systems neighbor
      WHERE neighbor.id64 != center.id64
        AND neighbor.coords <@ cube_enlarge(center.coords, 40.0, 3)
        AND (center.coords <-> neighbor.coords) <= 40.0
  ) nearby
  WHERE nearby.neutron_neighbors_within_40ly >= 5
  ORDER BY nearby.neutron_neighbors_within_40ly DESC
  LIMIT 15;
  ```

---

## 🛸 7. "Hutton Orbital" Supercruise Marathon Index

*Memes, extreme supercruise commutes, and historical quirks.*

* **The Supercruise Marathon (Furthest Stations from Jump Point):**

  ```sql
  SELECT
      systems.name AS system_name,
      far_stations.name AS station_name,
      far_stations.type AS station_type,
      ROUND(far_stations.distanceToArrival::numeric, 0) AS distance_light_seconds,
      ROUND((far_stations.distanceToArrival / 31557600)::numeric, 3) AS distance_light_years,
      far_stations.pad_large
  FROM (
      -- Pre-filter top 15 furthest stations first to avoid joining systems table across all stations
      SELECT *
      FROM stations
      WHERE distanceToArrival > 1000000 -- > 1 million light-seconds (~0.03+ ly)
      ORDER BY distanceToArrival DESC
      LIMIT 15
  ) far_stations
  INNER JOIN systems ON systems.id64 = far_stations.system_id64;
  ```

---

## 🔧 8. Engineers & Workshop Modification Locators

*Find specialized Horizons and Odyssey workshops relative to your home base.*

### A. Nearest Engineers by Specialty (e.g. Frame Shift Drive from Cubeo)

* **The Concept:** Find all engineers specializing in a specific modification discipline (e.g. `frame_shift_drive`, `thrusters`, `shield_generator`, `plasma_accelerator`), their maximum modification grade, workshop base, unlock requirements, permit status, and exact 3D Euclidean distance in light-years from your reference location (e.g. Cubeo).
* **Planner Optimization:** Utilizes GIN index on `specialties` (`idx_engineers_specialties`) combined with scalar `InitPlan` coordinate lookup for sub-millisecond distance calculation. Names and bases are dynamically resolved via foreign keys.
* **The Query:**

  ```sql
  SELECT
      engineers.name AS engineer_name,
      engineers.engineer_type,
      stations.name AS workshop_base,
      systems.name AS system_name,
      COALESCE(
          (engineers.specialties->'major'->>'frame_shift_drive')::int,
          (engineers.specialties->'minor'->>'frame_shift_drive')::int
      ) AS fsd_max_grade,
      -- Use exact '=' for direct B-Tree lookup (idx_systems_name), or ILIKE for case-insensitive searches (idx_systems_name_trgm)
      ROUND((systems.coords <-> (SELECT coords FROM systems WHERE name = 'Cubeo' LIMIT 1))::numeric, 2) AS distance_ly,
      engineers.permit_required,
      engineers.referral_from,
      engineers.unlock_requirement,
      engineers.region,
      engineers.specialties
  FROM engineers
  INNER JOIN systems ON systems.id64 = engineers.system_id64
  LEFT JOIN stations ON stations.market_id = engineers.market_id
  WHERE (engineers.specialties->'major' ? 'frame_shift_drive')
     OR (engineers.specialties->'minor' ? 'frame_shift_drive')
  ORDER BY
      fsd_max_grade DESC,
      distance_ly ASC;
  ```

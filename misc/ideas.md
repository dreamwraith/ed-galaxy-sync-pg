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
      bodies.name AS body_name,
      bodies.subType,
      ROUND(bodies.gravity::numeric, 2) AS gravity_g,
      bodies.earthMasses,
      ROUND(bodies.radius::numeric, 0) AS radius_km,
      ROUND(bodies.distanceToArrival::numeric, 1) AS distance_ls
  FROM bodies
  JOIN systems ON systems.id64 = bodies.system_id64
  WHERE bodies.isLandable = TRUE 
    AND bodies.gravity > 4.0
  ORDER BY bodies.gravity DESC
  LIMIT 15;
  ```

---

### B. The "Skimming the Surface" Ultra-Close Binary Orbits

* **The Concept:** Planets or stars with sub-hour orbital periods or tiny semi-major axes orbiting black holes, neutron stars, or white dwarfs.
* **Why it's cool:** These create cinematic in-game views where celestial bodies visibly move across the skybox in real time.
* **The Query:**

  ```sql
  SELECT 
      systems.name AS system_name,
      bodies.name AS body_name,
      bodies.subType,
      ROUND((bodies.orbitalPeriod * 24 * 60)::numeric, 1) AS orbital_period_minutes,
      ROUND(bodies.semiMajorAxis::numeric, 0) AS semi_major_axis_km,
      bodies.orbitalEccentricity,
      parent_body.subType AS parent_subType
  FROM bodies
  JOIN systems ON systems.id64 = bodies.system_id64
  LEFT JOIN bodies parent_body ON parent_body.system_id64 = bodies.system_id64 
       AND (bodies.parents->0->>'Star')::bigint = parent_body.bodyId
  WHERE bodies.orbitalPeriod > 0 
    AND bodies.orbitalPeriod < 0.2  -- Under ~4.8 hours
  ORDER BY bodies.orbitalPeriod ASC
  LIMIT 20;
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
      body_rings.name AS ring_name,
      body_rings.type AS ring_type,
      ROUND((body_rings.outerRadius - body_rings.innerRadius)::numeric, 0) AS ring_span_km,
      ROUND((body_rings.outerRadius / 149597870.7)::numeric, 3) AS outer_radius_au,
      body_rings.mass AS mass_megatonnes
  FROM body_rings
  JOIN bodies ON bodies.id64 = body_rings.body_id64
  JOIN systems ON systems.id64 = bodies.system_id64
  ORDER BY (body_rings.outerRadius - body_rings.innerRadius) DESC
  LIMIT 15;
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
  JOIN bodies ON bodies.id64 = body_signals.body_id64
  JOIN systems ON systems.id64 = body_signals.system_id64
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
  JOIN bodies ON bodies.id64 = body_signals.body_id64
  JOIN systems ON systems.id64 = body_signals.system_id64
  WHERE (bodies.surfaceTemperature > 500 OR bodies.surfaceTemperature < 50)
    AND cardinality(body_signals.genuses) > 0
  ORDER BY bodies.surfaceTemperature DESC;
  ```

---

## 🏡 3. Real Estate Scout: "Paradise Worlds" & Scenic Skyline Index

*Finding dream candidate systems for colonization, scenic screenshots, or squad bases.*

### A. The "Multi-Earth-Like" & Terraforming Cluster

* **The Concept:** Systems containing 2+ Earth-like Worlds (ELWs) or 4+ Terraformable worlds in one star system.
* **The Query:**

  ```sql
  SELECT 
      systems.name AS system_name,
      systems.population,
      systems.allegiance,
      COUNT(*) FILTER (WHERE bodies.subType = 'Earth-like World') AS elw_count,
      COUNT(*) FILTER (WHERE bodies.terraformingState IN ('Terraformable', 'Terraforming', 'Terraformed')) AS terraformable_count,
      ROUND((systems.coords <-> cube(ARRAY[0,0,0]::double precision[]))::numeric, 1) AS distance_from_sol_ly
  FROM systems
  JOIN bodies ON bodies.system_id64 = systems.id64
  GROUP BY systems.id64, systems.name, systems.population, systems.allegiance, systems.coords
  HAVING COUNT(*) FILTER (WHERE bodies.subType = 'Earth-like World') >= 2
      OR COUNT(*) FILTER (WHERE bodies.terraformingState = 'Terraformable') >= 4
  ORDER BY elw_count DESC, terraformable_count DESC;
  ```

---

### B. The "Massive Skyfill" Scenic Screenshot Spot

* **The Concept:** A landable moon orbiting a ringed gas giant or water world at an extremely tight orbital radius (< 80,000 km).
* **Why it's cool:** The massive ringed giant fills almost the entire skybox when standing on the surface.
* **The Query:**

  ```sql
  SELECT 
      systems.name AS system_name,
      moon_body.name AS moon_name,
      parent_giant.name AS parent_giant_name,
      parent_giant.subType AS giant_type,
      ROUND(moon_body.semiMajorAxis::numeric, 0) AS moon_orbit_radius_km,
      ROUND(moon_body.gravity::numeric, 2) AS moon_gravity,
      EXISTS(SELECT 1 FROM body_rings WHERE body_rings.body_id64 = parent_giant.id64) AS parent_has_rings
  FROM bodies moon_body
  JOIN bodies parent_giant ON parent_giant.system_id64 = moon_body.system_id64 
       AND (moon_body.parents->0->>'Planet')::bigint = parent_giant.bodyId
  JOIN systems ON systems.id64 = moon_body.system_id64
  WHERE moon_body.isLandable = TRUE
    AND parent_giant.subType ILIKE '%gas giant%'
    AND moon_body.semiMajorAxis < 100000 -- Under 100,000 km
  ORDER BY moon_body.semiMajorAxis ASC
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
  WITH inhabited AS (
      SELECT id64, name, coords, population 
      FROM systems 
      WHERE population > 1000
  )
  SELECT 
      host_sys.name AS isolated_system,
      host_sys.population,
      ROUND((host_sys.coords <-> cube(ARRAY[0,0,0]::double precision[]))::numeric, 1) AS dist_to_sol_ly,
      ROUND(MIN(host_sys.coords <-> neighbor_sys.coords)::numeric, 1) AS nearest_neighbor_dist_ly
  FROM inhabited host_sys
  JOIN inhabited neighbor_sys ON host_sys.id64 != neighbor_sys.id64 AND (host_sys.coords <-> neighbor_sys.coords) < 1000
  GROUP BY host_sys.id64, host_sys.name, host_sys.coords, host_sys.population
  ORDER BY nearest_neighbor_dist_ly DESC
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
  JOIN systems ON systems.id64 = stations.system_id64
  WHERE systems.government = 'Anarchy'
    AND systems.security = 'Anarchy'
    AND 'Black Market' = ANY(stations.services_arr)
    AND 'Shipyard' = ANY(stations.services_arr)
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
  JOIN systems ON systems.id64 = stations.system_id64
  WHERE stations.state IN ('Damaged', 'UnderAttack', 'UnderRepairs')
     OR systems.thargoidWar IS NOT NULL
  ORDER BY war_progress ASC, systems.population DESC;
  ```

---

## 💎 5. High-Yield Mining & Market Arbitrage Triangulation

*Combining planetary ring hotspot scans with live commodity market demands.*

### A. The "Pristine Multi-Hotspot" Platinum / Tritium Fields

* **The Concept:** Pristine metallic or icy rings that contain multiple overlapping signals of lucrative ores (Platinum, Painite, Tritium, Void Opals).
* **The Query:**

  ```sql
  SELECT 
      systems.name AS system_name,
      bodies.name AS planet_name,
      body_rings.name AS ring_name,
      bodies.reserveLevel,
      COALESCE((body_rings.signals->'signals'->>'Platinum')::int, (body_rings.signals->>'Platinum')::int, 0) AS platinum_hotspots,
      COALESCE((body_rings.signals->'signals'->>'Tritium')::int, (body_rings.signals->>'Tritium')::int, 0) AS tritium_hotspots,
      ROUND(bodies.distanceToArrival::numeric, 1) AS distance_ls
  FROM body_rings
  JOIN bodies ON bodies.id64 = body_rings.body_id64
  JOIN systems ON systems.id64 = bodies.system_id64
  WHERE bodies.reserveLevel = 'Pristine'
    AND (
      COALESCE((body_rings.signals->'signals'->>'Platinum')::int, (body_rings.signals->>'Platinum')::int, 0) >= 2 OR 
      COALESCE((body_rings.signals->'signals'->>'Tritium')::int, (body_rings.signals->>'Tritium')::int, 0) >= 2
    )
  ORDER BY platinum_hotspots DESC, tritium_hotspots DESC
  LIMIT 25;
  ```

---

### B. High-Profit Spatial Trade Run (Within 25 Light-Years)

* **The Concept:** Find high-supply commodities at Station A and pair them with high-demand buy prices at Station B within a 1-to-2 jump radius (25 ly) with Large landing pad support.
* **The Query:**

  ```sql
  SELECT 
      sell_comm.name AS commodity,
      origin_sys.name AS origin_system,
      origin_station.name AS buy_station,
      sell_comm.buyPrice AS purchase_cost,
      sell_comm.supply AS available_supply,
      dest_sys.name AS destination_system,
      dest_station.name AS sell_station,
      buy_comm.sellPrice AS station_payout,
      (buy_comm.sellPrice - sell_comm.buyPrice) AS profit_per_ton,
      ROUND((origin_sys.coords <-> dest_sys.coords)::numeric, 1) AS distance_ly
  FROM station_commodities sell_comm
  JOIN stations origin_station ON origin_station.market_id = sell_comm.market_id AND origin_station.pad_large > 0
  JOIN systems origin_sys ON origin_sys.id64 = origin_station.system_id64
  JOIN station_commodities buy_comm ON LOWER(buy_comm.name) = LOWER(sell_comm.name) AND buy_comm.demand > 1000
  JOIN stations dest_station ON dest_station.market_id = buy_comm.market_id AND dest_station.pad_large > 0 AND dest_station.market_id != origin_station.market_id
  JOIN systems dest_sys ON dest_sys.id64 = dest_station.system_id64
  WHERE sell_comm.supply > 5000
    AND sell_comm.buyPrice > 0
    AND (buy_comm.sellPrice - sell_comm.buyPrice) > 25000  -- >25,000 credits/ton profit
    AND (origin_sys.coords <-> dest_sys.coords) < 25.0     -- Within 25 ly
  ORDER BY profit_per_ton DESC
  LIMIT 15;
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
* **The Query:**

  ```sql
  SELECT 
      center_sys.name AS center_system,
      COUNT(DISTINCT neighbor_sys.id64) AS neutron_neighbors_within_40ly,
      ROUND((center_sys.coords <-> cube(ARRAY[0,0,0]::double precision[]))::numeric, 1) AS dist_from_sol_ly
  FROM bodies center_body
  JOIN systems center_sys ON center_sys.id64 = center_body.system_id64
  JOIN systems neighbor_sys ON (center_sys.coords <-> neighbor_sys.coords) <= 40.0
  JOIN bodies neighbor_body ON neighbor_body.system_id64 = neighbor_sys.id64 
       AND neighbor_body.subType IN ('Neutron Star', 'White Dwarf (DA) Star', 'White Dwarf (DAB) Star')
  WHERE center_body.subType = 'Neutron Star'
  GROUP BY center_sys.id64, center_sys.name, center_sys.coords
  HAVING COUNT(DISTINCT neighbor_sys.id64) > 5
  ORDER BY neutron_neighbors_within_40ly DESC
  LIMIT 15;
  ```

---

## 🛸 7. "Hutton Orbital" Supercruise Marathon Index

*Memes, extreme supercruise commutes, and historical quirks.*

* **The Supercruise Marathon (Furthest Stations from Jump Point):**

  ```sql
  SELECT 
      systems.name AS system_name,
      stations.name AS station_name,
      stations.type AS station_type,
      ROUND(stations.distanceToArrival::numeric, 0) AS distance_light_seconds,
      ROUND((stations.distanceToArrival / 31557600)::numeric, 3) AS distance_light_years,
      stations.pad_large
  FROM stations
  JOIN systems ON systems.id64 = stations.system_id64
  WHERE stations.distanceToArrival > 1000000 -- > 1 million light-seconds (~0.03+ ly)
  ORDER BY stations.distanceToArrival DESC
  LIMIT 15;
  ```

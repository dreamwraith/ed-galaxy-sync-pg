# PostgreSQL Database Architecture & Runbook (`db_setup`)

Comprehensive technical reference, deployment orchestrator, and runbook for the `galaxy_sync` PostgreSQL database supporting the Elite Dangerous Galaxy Sync and Ingestion Pipeline.

---

## Directory Structure

```text
db_setup/
├── 00_init/
│   ├── 00_database.sql           # Database creation DDL (UTF-8, C collation)
│   ├── 01_extensions.sql         # Required extensions: cube, pg_trgm
│   ├── 02_users_roles.sql        # Core users: galaxy_searcher (read-only) & galaxy_updater (DML only)
│   └── 03_optional_pg_duckdb.sql # Optional pg_duckdb extension, duckdb_users role & grants
├── 01_tables/
│   ├── 01_systems.sql            # Systems domain table & comments
│   ├── 02_system_factions.sql    # System minor factions presence
│   ├── 03_bodies.sql             # Stars, planets, barycentres
│   ├── 04_body_rings.sql         # Planetary & stellar rings with hotspot signals
│   ├── 05_body_belts.sql         # Asteroid belts
│   ├── 06_body_signals.sql       # Surface DSS biological/geological signals
│   ├── 07_stations.sql           # Spaceports, planetary ports, outposts & fleet carriers
│   ├── 08_station_commodities.sql# Market commodity prices, supply/demand
│   ├── 09_station_ships.sql      # Shipyard inventory
│   ├── 10_station_modules.sql    # Outfitting modules inventory
│   ├── 11_station_materials.sql  # Fleet carrier Odyssey bartender / materials market
│   ├── 12_system_signals.sql     # System-level POIs & persistent FSS signals
│   ├── 13_body_pois.sql          # Planetary surface points of interest (ruins, settlements)
│   ├── 14__ingested_tables.sql   # Ingest pipeline chunk checkpoint table
│   ├── 15_eddn_unhandled_events.sql # Dead-Letter Queue (DLQ) catch-all staging table
│   ├── 16__raw_debug_log.sql     # Debug audit log capturing raw EDDN payloads matching filter rules
│   └── 17_engineers.sql          # Engineers reference table (Horizons & Odyssey workshops)
├── 02_indexes/
│   ├── create_all_indexes.sql    # Secondary, spatial GiST, trigram & GIN indexes
│   └── drop_all_indexes.sql      # Drop secondary indexes for high-speed bulk ingestion
├── 03_constraints/
│   ├── drop_constraints.sql      # Drop PK constraints during raw chunk loading
│   └── add_constraints.sql       # Restore PK constraints post-bulk load
├── 04_functions/
│   └── system_distance_3d.sql    # 3D Euclidean distance calculation function
├── 05_procedures/
│   ├── sp_normalize_galaxy_data.sql # Stored procedure for canonical data cleanup
│   └── sp_process_eddn_dlq.sql   # Stored procedure for processing/backfilling DLQ events
├── data/
│   └── engineers.yaml            # Static reference data for engineers (SCD batch deployments)
├── seed_data.py                  # Idempotent seeder for static reference data (engineers, etc.)
├── generate_cleanup_sp.py        # Generates sp_normalize_galaxy_data.sql from YAML configs
├── generate_dlq_sp.py            # Generates sp_process_eddn_dlq.sql from YAML + whitelist
├── db_setup.py                   # Deterministic CLI orchestrator for schema management
└── readme.md                     # Schema reference & operational runbook (this file)

```

---

## PostgreSQL Server Configuration (`postgresql.conf`)

To achieve maximum throughput during 500GB+ bulk data ingestion, continuous real-time EDDN streaming replication, and rapid 3D spatial searches, configure your PostgreSQL cluster (`postgresql.conf`) with the guidelines below.

### 1. Memory & Work Allocations

| Parameter | High-Throughput Setting (32GB Host) | Adjustments for Less RAM | Purpose |
|---|---|---|---|
| `shared_buffers` | `4GB` | Reduce to `1GB` (for 8GB RAM) or `2GB` (for 16GB RAM). | Shared memory buffer cache for database blocks. |
| `work_mem` | `64MB` | Reduce to `16MB`–`32MB` on memory-constrained systems. | Dedicated per-operation memory for sorting, hash joins, and aggregation queries. |
| `maintenance_work_mem` | `2GB` | Reduce to `512MB` (for 8GB RAM) or `1GB` (for 16GB RAM). | Dedicated memory for building secondary indexes (`CREATE INDEX`), constraint creation, and VACUUM. |
| `effective_cache_size` | `12GB` | Set to ~50%–75% of available RAM (e.g. `4GB` on 8GB host, `8GB` on 16GB host). | Planner heuristic for total memory available in PostgreSQL buffers + OS page cache. |

### 2. Write-Ahead Logging (WAL) & Ingestion Checkpoints

These settings smooth out disk write spikes and sustain continuous multi-gigabyte ingestion throughput:

```ini
wal_buffers = 16MB
min_wal_size = 2GB
max_wal_size = 16GB                  # Reduce to 4GB-8GB on storage-constrained disks
checkpoint_timeout = 15min           # Extends duration between checkpoints to minimize disk thrashing
checkpoint_completion_target = 0.9   # Spreads checkpoint I/O over 90% of the timeout interval
```

### 3. Autovacuum Tuning for High-Volume Upserts

Because live EDDN replication continuously inserts and updates telemetry tables, tune autovacuum to aggressively clean dead tuples:

```ini
autovacuum_max_workers = 6
autovacuum_worker_slots = 16
autovacuum_vacuum_cost_delay = 2ms   # Lowers delay to clean dead tuples more aggressively
autovacuum_vacuum_cost_limit = 2000  # Raises cost ceiling per round to keep up with write load
```

### 4. Logging & Diagnostics

```ini
logging_collector = on
log_destination = 'stderr, csvlog'
log_filename = 'postgresql-%a.log'
log_rotation_age = 1440
log_rotation_size = 100
log_truncate_on_rotation = on
log_line_prefix = '%m [%p] %q%u@%d '
```

### 5. `pg_duckdb` Acceleration Settings (Optional)

> [!NOTE]
> If you choose to **exclude** `pg_duckdb` from your database setup, you can leave all settings in this subsection alone / omit them entirely.

If using `pg_duckdb` for analytical query execution inside PostgreSQL:

```ini
shared_preload_libraries = 'pg_duckdb'    # Requires PostgreSQL service restart
duckdb.postgres_role = 'duckdb_users'
duckdb.memory_limit = '16GB'              # Set to ~50% of available system RAM; scale down on smaller hosts (e.g. 4GB on 8GB host, 8GB on 16GB host)
```

---

## Security & User Roles

| Role | Permissions | Security Boundary |
|---|---|---|
| `galaxy_searcher` | `SELECT` on all tables/views, `EXECUTE` on pure functions (`system_distance_3d`) | **Read-Only**: Cannot insert, update, delete, or run DDL / modifying stored procedures. |
| `galaxy_updater` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` on all tables, `USAGE/SELECT` on all sequences, `EXECUTE` on modifying stored procedures (`sp_normalize_galaxy_data`, `sp_process_eddn_dlq`) | **DML Only**: Cannot run `CREATE TABLE`, `DROP`, `ALTER`, or schema-level DDL (`CREATE` revoked on `public`). |
| `duckdb_users` | `SELECT` on all tables/views in `public`, `NOLOGIN`, inherited by `galaxy_searcher` and `galaxy_updater` | **pg_duckdb Query Role**: Execution role required when `duckdb.force_execution = true`. |

### Role Password Management & Interactive Prompts

When executing actions that initialize database roles (`--action init` or `--action all`), `db_setup` resolves credentials using the following fallback priority:

1. **Explicit CLI Flags**: `--searcher-password <pwd>` and `--updater-password <pwd>`
2. **Environment Variables**: `GALAXY_SEARCHER_PASSWORD` and `GALAXY_UPDATER_PASSWORD` (auto-loaded from `.env`)
3. **Interactive Terminal Prompt**: If running in an active terminal session, `db_setup` securely prompts the user:

   ```text
   🔑 Enter password for database role 'galaxy_searcher' [press Enter to auto-generate]: 
   🔑 Enter password for database role 'galaxy_updater' [press Enter to auto-generate]: 
   ```

4. **Secure Auto-Generation**: If the user presses **Enter** (blank input) or passes `--no-prompt` (e.g. in automated CI/CD pipelines), cryptographically secure 16-character random tokens are generated automatically and displayed in the output.

> [!NOTE]
> `db_setup` safely escapes and templates passwords into `00_init/02_users_roles.sql` in memory without modifying the SQL file on disk. If the roles already exist in the database, `db_setup` executes `ALTER ROLE ... WITH PASSWORD` to update their credentials.

---

## Database Setup & Schema Orchestration CLI (`db_setup.py`)

The `db_setup.py` script replaces monolithic schema files by executing modular scripts in deterministic order. It can be invoked via `uv run db_setup` or directly when the virtual environment is active.

> [!WARNING]
> **Credential Security**: Inline CLI connection flags (`--host`, `--port`, `--user`, `--password`, `--dbname`) and local `.env` files are supported strictly for local development, testing, and initial setup convenience. **Never store plaintext credentials in `.env` files or pass credentials via command-line arguments in production environments.**
>
> For production deployments, inject PostgreSQL environment variables dynamically at runtime (e.g., via Kubernetes Secrets, Docker Compose secrets, or systemd `LoadCredential=`), use PostgreSQL's native `~/.pgpass` (`%APPDATA%\postgresql\pgpass.conf`) password file, or authenticate via SSL client certificates.

### Usage Options

```powershell
uv run db_setup [OPTIONS]
```

| Flag | Description | Default |
|---|---|---|
| `--action` | Subsystem to apply (`all`, `init`, `tables`, `indexes`, `drop-indexes`, `rebuild-indexes`, `constraints`, `drop-constraints`, `rebuild-constraints`, `functions`, `procedures`, `seed`, `run-normalize`, `normalize`, `run-dlq`, `dlq`, `duckdb`, `pg-duckdb`) | `all` |
| `--datasets` | Optional specific dataset name(s) to seed when using `--action seed` (e.g. `--datasets engineers`) | *(all discovered)* |
| `--batch-size` | Batch size for stored procedure execution (`run-normalize`, `run-dlq`) | `250000` |
| `--dry-run` | Print the ordered execution plan without making any database changes | `False` |
| `--host` | PostgreSQL server hostname / IP (or env `PGHOST`) | `localhost` |
| `--port` | PostgreSQL server port (or env `PGPORT`) | `5432` |
| `--user` | PostgreSQL superuser/admin (or env `PGUSER`) | `postgres` |
| `--password` | PostgreSQL superuser/admin password (or env `PGPASSWORD`) | *(empty)* |
| `--dbname` | Target database name (or env `PGDATABASE`) | `galaxy_sync` |
| `--searcher-password` | Password for `galaxy_searcher` role (or env `GALAXY_SEARCHER_PASSWORD`) | *(prompt / auto-generated)* |
| `--updater-password` | Password for `galaxy_updater` role (or env `GALAXY_UPDATER_PASSWORD`) | *(prompt / auto-generated)* |
| `--no-prompt` | Disable interactive password prompts and auto-generate credentials if not provided | `False` |

> [!IMPORTANT]
> **Constraint Deployment vs. Bulk Load Recovery**:
>
> * `--action all` creates a **fresh schema**, including all primary keys and constraints defined **inline** within each table's DDL (`01_tables/*.sql`).
> * **Do not run `add_constraints.sql` or `--action constraints` after a normal `all` deployment** — constraints already exist from table creation.
> * `--action all` is **not** the post-bulk recovery command (running it on populated tables will fail on existing table creation).
> * The standalone constraint scripts (`03_constraints/add_constraints.sql` and `03_constraints/drop_constraints.sql`) exist **strictly for bulk-load recovery**.

### Common Operational Workflows

#### 1. Full Fresh Database Schema Deployment (Interactive)

Deploys extensions, roles, domain tables with inline primary keys, functions, secondary/search indexes, and stored procedures:

```powershell
uv run db_setup --action all
```

#### 2. Non-Interactive / Scripted Deployment with Custom Passwords

```powershell
# Option A: Via Environment Variables (Recommended for scripts)
$env:PGUSER = "postgres"
$env:PGPASSWORD = "YOUR_SUPERUSER_PASSWORD"
$env:GALAXY_SEARCHER_PASSWORD = "SearcherSecurePassword123!"
$env:GALAXY_UPDATER_PASSWORD = "UpdaterSecurePassword123!"

uv run db_setup --action all --no-prompt

# Option B: Via CLI Flags
uv run db_setup --action all --searcher-password "SearcherPass!" --updater-password "UpdaterPass!" --no-prompt
```

#### 3. Dry-Run Verification (Inspect Plan)

```powershell
uv run db_setup --action all --dry-run
```

#### 4. Initial Bulk Data Load & Post-Bulk Recovery Workflow

```powershell
# Step 1: Drop secondary indexes and constraints to maximize write throughput (10x-20x speedup)
uv run db_setup --action drop-indexes
uv run db_setup --action drop-constraints

# Step 2: Run bulk ingest pipeline
uv run galaxy_sync ingest --json "D:\galaxy_parts\*.ndjson" --mode bulk --threads 8 --batch-size 4

# Step 3: Post-bulk recovery (rebuild constraints first, then indexes)
uv run db_setup --action rebuild-constraints
uv run db_setup --action rebuild-indexes
```

#### 5. Regenerate & Deploy Stored Procedures

```powershell
# Regenerate SQL procedures from canonical normalizations
uv run python db_setup/generate_cleanup_sp.py
uv run python db_setup/generate_dlq_sp.py

# Apply procedures to database
uv run db_setup --action procedures
```

---

## Stored Procedures

### 1. `sp_normalize_galaxy_data(batch_size INT DEFAULT 50000)`

Batched normalization procedure generated dynamically from `eddn/normalizations/*.yaml`. Normalizes legacy text tokens (e.g. `$EXT_Industrial;` $\to$ `Industrial`, `$station_carrier;` $\to$ `Drake-Class Carrier`) across `systems`, `stations`, `body_rings`, `body_belts`, `system_factions`, `station_commodities`, `station_ships`, `station_modules`, and `station_materials`.

```sql
CALL sp_normalize_galaxy_data(50000);
```

### 2. `sp_process_eddn_dlq(batch_size INT DEFAULT 5000, force_sender TEXT DEFAULT NULL, purge_noise BOOLEAN DEFAULT FALSE, run_normalizations BOOLEAN DEFAULT TRUE)`

Procedural Dead-Letter Queue drainer and domain backfill processor.

* Validates sender against approved software whitelist (from `config.yaml`).
* Supports `force_sender` to replay messages from a specific client version.
* Purges noise schemas (`navroute`, `dockinggranted`, `/test%`) and legacy game versions when `purge_noise => TRUE`.
* Upserts valid events into domain tables (`systems`, `bodies`, `stations`, `system_signals`, etc.) and removes drained rows from `eddn_unhandled_events`.

```sql
-- Standard safe run (preserves unhandled events)
CALL sp_process_eddn_dlq(5000);

-- Force process events from a specific sender with noise purging enabled
CALL sp_process_eddn_dlq(5000, 'CustomEDDNClient/1.0', TRUE);
```

---

## Domain Tables Reference

### `systems`

One row per Elite Dangerous star system. Uniquely identified by Galactic `id64`. Coordinates are 3D light-years relative to Sol (0, 0, 0).

| Column | Type | Description |
|---|---|---|
| `id64` | `BIGINT` PK | Galactic ID64 — 64-bit unsigned integer encoding sector, mass-code, and body offset. |
| `name` | `TEXT` | Human-readable name of the star system. Trigram and lower indexed. |
| `coords` | `cube` | 3D galactic coordinates in light-years. GiST indexed (`idx_systems_coords_cube`). |
| `allegiance` | `TEXT` | Political allegiance (`Alliance`, `Empire`, `Federation`, `Independent`, etc.). |
| `government` | `TEXT` | Government type (`Democracy`, `Corporate`, `Anarchy`, `Feudal`, etc.). |
| `primaryEconomy` | `TEXT` | Primary economy type (`High Tech`, `Industrial`, `Refinery`, `Extraction`, etc.). |
| `secondaryEconomy` | `TEXT` | Secondary economy type. |
| `security` | `TEXT` | Security rating (`High`, `Medium`, `Low`, `Anarchy`). |
| `population` | `BIGINT` | Total human population. `0` for uninhabited systems. |
| `bodyCount` | `INTEGER` | Total number of surveyed celestial bodies. |
| `controllingPower` | `TEXT` | Controlling Powerplay power. Partial index (`idx_systems_controlling_power`). |
| `powerState` | `TEXT` | Powerplay state (`Exploited`, `Fortified`, `Stronghold`, `Unoccupied`). |
| `powers` | `JSONB` | Array of power names exerting influence. GIN indexed (`idx_systems_powers`). |
| `controllingFaction` | `JSONB` | Snapshot of the controlling minor faction. |
| `thargoidWar` | `JSONB` | Thargoid war state details (progress, remaining ports, states). |
| `timestamps` | `JSONB` | Field-level last updated timestamps. |
| `update_dtm` | `TIMESTAMP` | UTC timestamp of last update. |

### `system_factions`

One row per (system, faction) minor faction presence. Composite PK: `(system_id64, name)`.

| Column | Type | Description |
|---|---|---|
| `system_id64` | `BIGINT` PK | FK → `systems.id64`. |
| `name` | `TEXT` PK | Name of the minor faction. |
| `state` | `TEXT` | Active BGS state (`Boom`, `War`, `Civil War`, `Election`, `Expansion`, `Lockdown`, etc.). |
| `allegiance` | `TEXT` | Faction allegiance. |
| `government` | `TEXT` | Faction government type. |
| `influence` | `DOUBLE PRECISION` | Influence share (0.0–1.0). |
| `activeStates` | `JSONB` | Currently active BGS states. |
| `pendingStates` | `JSONB` | Pending (upcoming) BGS states. |
| `recoveringStates` | `JSONB` | Recovering BGS states. |
| `update_dtm` | `TIMESTAMP` | UTC timestamp of last update. |

### `bodies`

Celestial bodies (stars, planets, moons, barycentres). `id64` is globally unique across the galaxy and deterministically computed as `(system_id64 << 9) | (bodyId & 0x1FF)`, congruent with the Spansh and EDSM canonical identification standard.

| Column | Type | Description |
|---|---|---|
| `system_id64` | `BIGINT` | FK → `systems.id64`. B-Tree indexed (`idx_bodies_system`). |
| `id64` | `BIGINT` PK | Globally unique 64-bit Celestial ID: `(system_id64 << 9) \| (bodyId & 0x1FF)`. |
| `bodyId` | `BIGINT` | Frontier system-local integer index (0–511). Matches `Journal.BodyID`. |
| `name` | `TEXT` | Body name. |
| `type` | `TEXT` | High-level classification (`Planet`, `Star`, `Barycentre`). |
| `subType` | `TEXT` | Detailed subtype (`Earth-like world`, `Neutron Star`, `Class II gas giant`, etc.). |
| `distanceToArrival` | `DOUBLE PRECISION` | Distance from main star in light-seconds (ls). |
| `orbitalPeriod` | `DOUBLE PRECISION` | Orbital period in days. |
| `semiMajorAxis` | `DOUBLE PRECISION` | Semi-major axis in km. |
| `rotationalPeriod` | `DOUBLE PRECISION` | Rotational period in days. |
| `rotationalPeriodTidallyLocked`| `BOOLEAN` | `TRUE` if tidally locked. |
| `surfaceTemperature` | `DOUBLE PRECISION` | Surface temperature in Kelvin (K). |
| `radius` | `DOUBLE PRECISION` | Planets only: Equatorial radius in km. |
| `isLandable` | `BOOLEAN` | Planets only: `TRUE` if landable. |
| `gravity` | `DOUBLE PRECISION` | Planets only: Surface gravity in G (1.0 = 9.81 m/s²). Partial index (`idx_bodies_gravity`). |
| `earthMasses` | `DOUBLE PRECISION` | Planets only: Mass in Earth masses. |
| `surfacePressure` | `DOUBLE PRECISION` | Planets only: Surface atmospheric pressure in atm. |
| `atmosphereType` | `TEXT` | Dominant atmospheric composition label. |
| `terraformingState` | `TEXT` | Terraforming status (`Terraformable`, `Not terraformable`, `Terraformed`). |
| `reserveLevel` | `TEXT` | Mining reserve level (`Pristine`, `Major`, `Common`, `Low`, `Depleted`). B-Tree indexed (`idx_bodies_reserveLevel`). |
| `mainStar` | `BOOLEAN` | Stars only: `TRUE` if primary arrival star. |
| `spectralClass` | `TEXT` | Stars only: MKK spectral classification code. |
| `solarMasses` | `DOUBLE PRECISION` | Stars only: Mass in Sol masses. |
| `solarRadius` | `DOUBLE PRECISION` | Stars only: Radius in Sol radii. |
| `atmosphereComposition` | `JSONB` | GIN-indexed elemental breakdown (`idx_bodies_atmosphereComposition`). |
| `solidComposition` | `JSONB` | GIN-indexed solid material breakdown (`idx_bodies_solidComposition`). |
| `materials` | `JSONB` | GIN-indexed surface mineable elements (`idx_bodies_materials`). |
| `parents` | `JSONB` | Orbital hierarchy parent references. |
| `update_dtm` | `TIMESTAMP` | UTC timestamp of last update. |

### `body_rings` & `body_belts`

Planetary/stellar rings and asteroid belts. Composite PK: `(body_id64, name)`.

* `body_rings.type`: B-Tree indexed (`idx_body_rings_type`) and composite type + density indexed (`idx_body_rings_type_density`).
* `body_rings.signals`: GIN indexed (`idx_body_rings_signals`) for mining hotspot searches (e.g. Platinum, Painite, Void Opal).

### `body_signals`

Planetary surface biological, geological, and exobiology signals. Primary key: `body_id64`.

* `system_id64`: B-Tree indexed (`idx_body_signals_system`) for system-level bio/geo joins.
* `genuses`: GIN indexed (`idx_body_signals_genuses`) for exobiology genus array searches (e.g. `Stratum`, `Tubeworms`, `Fonticulua`).

### `stations`

All dockable space stations, surface ports, outposts, settlements, and Drake-Class Fleet Carriers. Primary key: `market_id`.

| Column | Type | Description |
|---|---|---|
| `market_id` | `BIGINT` PK | Frontier market identifier. Globally unique. |
| `system_id64` | `BIGINT` | FK → `systems.id64`. B-Tree indexed (`idx_stations_system`). |
| `body_source_id64` | `BIGINT` | Parent body identifier / index for planetary surface ports & settlements. Partial index (`idx_stations_body_source`). |
| `name` | `TEXT` | Station name. B-Tree & Trigram indexed (`idx_stations_name`, `idx_stations_name_trgm`). |
| `type` | `TEXT` | Physical type (`Coriolis Starport`, `Orbis Starport`, `Outpost`, `Planetary Port`, `Drake-Class Carrier`, `Settlement`). B-Tree indexed (`idx_stations_type`). |
| `state` | `TEXT` | Operational state (`Construction`, `Damaged`, `UnderRepairs`, `UnderAttack`). |
| `distanceToArrival` | `DOUBLE PRECISION` | Arrival distance in light-seconds (ls). |
| `latitude` / `longitude` | `DOUBLE PRECISION` | Surface coordinates for planetary ports/settlements. |
| `allegiance` / `government` | `TEXT` | Station political alignment. |
| `primaryEconomy` / `secondaryEconomy` | `TEXT` | Station economies. |
| `economies` | `JSONB` | Detailed economy breakdown. |
| `pad_large`, `pad_medium`, `pad_small` | `INTEGER` | Landing pad counts. |
| `services_arr` | `TEXT[]` | Supported services array (`Market`, `Shipyard`, `Outfitting`, `Restock`, `Refuel`, `Repair`, `Bartender`, `Vista Genomics`, etc.). GIN indexed (`idx_stations_services`). |
| `update_dtm` | `TIMESTAMP` | UTC timestamp of last update. |

### `station_commodities`, `station_ships`, `station_modules`, `station_materials`

* `station_commodities`: `(market_id, commodityId)` PK. Market prices, buy/sell values, supply/demand. B-Tree indexed on `name` (`idx_station_commodities_name`).
* `station_ships`: `(market_id, shipId)` PK. Shipyard inventory. B-Tree indexed on `name` (`idx_station_ships_name`).
* `station_modules`: `(market_id, moduleId)` PK. Outfitting module stock, class, rating. Composite B-Tree indexed on `(name, class, rating)` (`idx_station_modules_name_class_rating`).
* `station_materials`: `(market_id, material_id)` PK. Fleet carrier Odyssey bartender inventory and material trade pricing. Indexed on `name`, `symbol`, and `carrier_id`.

### `system_signals` & `body_pois`

* `system_signals`: `(system_id64, raw_name)` PK. Persistent FSS signals, Resource Extraction Sites, Nav Beacons, Conflict Zones, Megaships.
* `body_pois`: `(body_id64, raw_name)` PK. Planetary surface POIs (Guardian ruins, Thargoid structures, Crash sites, Surface settlements) with latitude/longitude.

### `engineers`

Reference dataset for Horizons ship engineers and Odyssey on-foot engineers. Primary key: `engineer_id`.

* **Source**: Populated from static dimensional reference data (`db_setup/data/engineers.yaml`).
* **Deployment & Lifecycle**: Managed via `uv run db_setup --action seed` (or `uv run db_setup --action seed --datasets engineers`) for initial deployments and slowly changing update maintenance (SCD).
* **Coverage**: Complete metadata for all 38 engineers across the galaxy (25 Horizons `Ship` and 13 Odyssey `OnFoot` workshops) including system ID64, body ID64, market ID, engineer type, `specialties` JSONB grade mappings, `permit_required`, `referral_from`, `unlock_requirement`, max grades, and galactic region. System, body, and base names are dynamically resolved via foreign keys (`systems.name`, `bodies.name`, `stations.name`).

### `eddn_unhandled_events` (DLQ) & `_raw_debug_log`

* `eddn_unhandled_events`: Dead-letter queue capturing unmapped, experimental, or unapproved software events with full `raw_message` JSONB payload.
* `_raw_debug_log`: Debug audit log capturing full raw EDDN payloads matching configured dot-notation filter rules (or ephemeral `uploader_id` SHA-256 hashes discovered via `probe-cmdr`).

---

## 3D Spatial Calculation Functions

### `system_distance_3d(system_a cube, system_b cube DEFAULT cube(ARRAY[0,0,0]::double precision[])) → double precision`

Computes 3D Euclidean distance in light-years using PostgreSQL native `cube` Euclidean distance operator `<->`.

* `IMMUTABLE` and `PARALLEL SAFE`.

```sql
-- Compute distance between Sol and Colonia
SELECT system_distance_3d(systems_sol.coords, systems_colonia.coords) AS dist_ly
FROM systems systems_sol, systems systems_colonia
WHERE systems_sol.name = 'Sol' AND systems_colonia.name = 'Colonia';

-- Find the 10 closest systems to Sol
SELECT name, system_distance_3d(coords) AS dist_ly
FROM systems
ORDER BY coords <-> cube(ARRAY[0,0,0]::double precision[])
LIMIT 10;
```

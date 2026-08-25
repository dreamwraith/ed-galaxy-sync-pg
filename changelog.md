# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-08-24

### Performance
* **3D Spatial Query Acceleration**: Anchored radial spatial trade runs, mining havens, and neutron star clusters via `nearby_systems` CTEs using **3D GiST bounding-box index scans** (`cube_enlarge` on `idx_systems_coords_cube`), eliminating galaxy-wide Cartesian joins (`misc/ideas.md`, `misc/meritmine.md`).
* **KNN Nearest Neighbor Scans**: Replaced $O(N^2)$ all-pairs distance joins with **`CROSS JOIN LATERAL` 3D GiST KNN nearest-neighbor scans** (`<->`) in isolated systems analysis (`misc/ideas.md`).
* **Subquery Pushdowns**: Pushed down `ORDER BY ... LIMIT` clauses into pre-filtered subqueries and CTEs across extreme exploration queries (Ring Titans, Pancake Death Trap, Skimming the Surface, Multi-ELW, Massive Skyfill, Hutton Orbital) to eliminate millions of unneeded join operations.
* **Performance Indexes**:
  * `idx_systems_controlling_power` (partial index `WHERE controllingPower IS NOT NULL`)
  * `idx_bodies_gravity` (partial descending index `(gravity DESC) WHERE gravity IS NOT NULL`)
  * `idx_body_rings_type_density` (composite index `(type, density DESC) WHERE density IS NOT NULL`)
  * `idx_body_signals_genuses` (GIN index on biological `genuses` array)
  * `idx_stations_services` (GIN index on `services_arr`)
  * `idx_station_modules_name_class_rating` (composite module search index)
  * `idx_engineers_specialties` (GIN index) & `idx_engineers_name_trgm` (trigram search)

### Added
* **Reference Data Seeding**: Added `db_setup/seed_data.py` (`DataSeeder`) and `--action seed` CLI workflow to dynamically validate and bulk upsert dimensional reference datasets from `db_setup/data/*.yaml`.
* **Engineers Dimensional Schema**: Added `17_engineers.sql` and `engineers.yaml` covering all 38 engineers (25 Horizons Ship and 13 Odyssey On-Foot workshops) with complete metadata, max modification grades, unlock requirements, base coordinates, and system linkages.
* **Reference Mapping Datasets**: Added canonical YAML reference mapping files derived from `FDevIDs` under `eddn/normalizations/disabled/direct/` for companion queries and offline analyses (`crimes.yaml`, `docking_denied_reasons.yaml`, `happiness.yaml`, `passenger_types.yaml`, `ranks_combat.yaml`, `ranks_trade.yaml`, `ranks_exploration.yaml`, `ranks_cqc.yaml`, `ranks_empire.yaml`, `ranks_federation.yaml`).
* **Normalization Mappings & Exobiology**: Expanded `genuses.yaml` and `species_variants_reference.yaml` with complete star-type variant matrices and Frontier symbol codes across all 55 genera and 151 species, purged unmapped placeholder keys (`Vitreus`, `Loricatus`, `Gyre Trees`), added Guardian and Thargoid POI tokens (`MegaBarnacle`, `WreckedUnknown`, `Unknown`) to `poi_types.yaml`, and updated allegiances, commodities, and module categories.
* **Automated Release Pipeline**: Added `.github/workflows/release.yml` to automatically build distributions with `uv build` and publish GitHub Releases on `v*` tags with attached wheel/sdist assets and versioned release notes.
* **Line Ending Normalization**: Added `.gitattributes` to enforce Unix LF line endings across Python, SQL, YAML, TOML, Markdown, and JSON files repository-wide.

### Changed
* **Database Setup CLI**: Refactored `apply_schema.py` to `db_setup.py` for naming consistency across the package and registered `db_setup` / `db-setup` console script entrypoints in `pyproject.toml`.
* **Credential Resolution**: Upgraded admin and role credential handling with strict priority fallbacks: Environment Variables $\to$ CLI Arguments $\to$ Interactive TTY Prompt $\to$ Secure Auto-Generation.
* **Ring Density Formatting**: Formatted ring density output to human-scale tonnes per square kilometer (`_ton_km2`) with 6-decimal precision formatting.
* **CI Quality Gates**: Enhanced `.github/workflows/ci.yml` with release branch and tag triggers, job concurrency with in-progress cancellation, automated license immutability SHA-256 validation, and Markdown linting with `rumdl`.
* **Documentation & Architecture**: Documented normalization directory structure and active vs. reference mappings in `eddn/normalizations/readme.md`, and updated `readme.md`, `usage.md`, and `db_setup/readme.md`.

### Fixed
* **Ring Hotspot Signals Flattening**: Flattened `body_rings.signals` JSONB structure to store clean key-value pairs (e.g. `{"Platinum": 3, "Void Opal": 1}`) directly, eliminating redundant nested metadata.
* **Commodity Hotspot Token Normalization**: Normalized ring hotspot signal tokens directly against `commodities.yaml` (e.g. mapping `$Opal_Name;` / `Opal` $\to$ `Void Opal`, `LowTemperatureDiamond` $\to$ `Low Temperature Diamonds`) before falling back to scenarios or raw sanitization.
* **Direct Ring Signals GIN Index**: Updated `create_all_indexes.sql` and `drop_all_indexes.sql` to index `body_rings.signals` directly with GIN (`idx_body_rings_signals`) instead of the legacy `(signals -> 'signals')` expression.
* **Dynamic Procedural Surface Signals**: Recognized procedural client-side `POIScene_` signal prefixes in `resolve_scenario` to dynamically resolve procedural surface POI spawns to `GenericPOI` without emitting unmapped metric errors.
* **Constraint Deployment Scope**: Clarified inline table constraint creation in `--action all` versus post-bulk recovery workflows (`--action rebuild-constraints` / `--action rebuild-indexes`).

### Testing
* **Test Suite Generalization**: Refactored `test_normalizers.py` to focus on core engine mechanics, structural integrity across all on-disk mapping files without duplicate keys, casing/spacing/punctuation invariance, token wrapper stripping, and multifield NamedTuple resolution.
* **Database Setup Tests**: Updated `test_db_setup.py` with dynamic file discovery matching on-disk SQL files across tables, functions, and procedures, dynamic reference dataset validation, isolated `DataSeeder` unit tests, and `resolve_admin_uri` credential precedence tests.

---

## [1.0.2] - 2026-08-24

### Fixed
* **Deterministic Celestial Body ID64**: Removed raw journal ID bypass in `JournalScanTransformer` to ensure all live EDDN scan events unconditionally compute the deterministic Spansh/EDSM bitshifted body ID: `(system_id64 << 9) | (bodyId & 0x1FF)`.
* **DDL Schema & Documentation**: Updated DDL schema comments in `03_bodies.sql` and `07_stations.sql` and runbook documentation in `db_setup/readme.md` to explicitly document the celestial body ID64 bitshift formula, system-local `bodyId`, and station parent body linkage.

### Added
* **Repository Ownership**: Added `.github/CODEOWNERS` for global repository ownership.

---

## [1.0.1] - 2026-08-23

### Added
* **Initial Release**: Initial public release of Elite Dangerous Galaxy Sync for PostgreSQL (`ed-galaxy-sync-pg`).
* **Cold-Start Bulk Ingestion**: Partitioned NDJSON dump parser streaming 500GB+ Spansh galaxy JSON dumps into PostgreSQL via embedded DuckDB vectorized engine (`galaxy_sync split` and `galaxy_sync ingest`).
* **Live EDDN Stream Replication**: Real-time ZeroMQ stream listener subscribing to `tcp://eddn.edcd.io:9500` with software whitelist verification, timestamp gating, micro-batching, and upsert handling (`galaxy_sync listen`).
* **Relational Schema**: 16 domain table definitions (`systems`, `bodies`, `stations`, `body_rings`, `body_belts`, `body_signals`, `station_commodities`, `station_ships`, `station_modules`, `station_materials`, `system_signals`, `body_pois`, `system_factions`, `_ingested_tables`, `eddn_unhandled_events`, `_raw_debug_log`).
* **3D Spatial Euclidean Indexing**: Native PostgreSQL `cube` GiST extension indexing for 3D coordinates relative to Sol `(0, 0, 0)`.
* **Canonical Token Normalization**: Modular YAML dictionaries for token normalization across allegiances, economies, governments, securities, ships, station types, and star/planet classes.
* **Stored Procedures**: Procedural routines for galaxy-wide normalization (`sp_normalize_galaxy_data`) and Dead-Letter Queue remediation (`sp_process_eddn_dlq`).
* **Role-Based Access Control (RBAC)**: Security boundaries for read-only query consumers (`galaxy_searcher`), DML-only ingest daemons (`galaxy_updater`), and `pg_duckdb` execution roles (`duckdb_users`).
* **Probe Sniffer**: Live ZeroMQ probe sniffer (`galaxy_sync probe-cmdr`) and debug audit log (`_raw_debug_log`) for active play session telemetry capture.

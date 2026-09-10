# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-09-10

### Added
* **First Footfall Tracking (`was_footfalled`)**: Added `was_footfalled BOOLEAN` column to bodies table DDL (`03_bodies.sql`) and updated `JournalScanTransformer` to extract `WasFootfalled` from live EDDN scan events (`tests/test_eddn_transformers.py`).
* **Timestamp & Drift Protection**: Added `EDDNUtils.is_valid_timestamp()` rejecting timestamps earlier than Elite Dangerous release date (2014-12-16) or greater than 24 hours into the future, routing invalid payloads to the DLQ and preventing permanent `update_dtm` clock-drift lockouts in PostgreSQL `GREATEST()` upserts.
* **Corrupted Packet Guards**: Added `SystemAddress <= 1` guard across `router.py`, `journal_jump.py`, `journal_scan.py`, `journal_station.py`, and `fss_signal.py`, and `market_id <= 0` guard across `commodity.py`, `shipyard.py`, and `fc_materials.py`.
* **Station & POI Name Sanitization**: Added `EDDNUtils.sanitize_station_name()` to automatically strip leading `$`, trailing `;`, and trailing settlement security indicators (`+`, `++`, `+++`) across `journal_station.py`, `commodity.py`, and `shipyard.py`.
* **Odyssey Watson Surface POIs**: Mapped 33 Odyssey Watson surface POI scenarios (`POIScenario_Watson_*`) in `scenarios.yaml` to canonical names (Minor Wreckage, Impact Site, Crash Site, Irregular Markers, Distress Beacon, Encrypted Signal) with appropriate severity ratings (Low, Medium, High).
* **Conflict Zone Operations**: Added `Operations` canonical signal type to `signal_types.yaml` and mapped On-Foot Extreme Conflict Zone sub-objectives (`Under Siege`, `Reclamation Point`, `Tactical Takedown`, `Operation Runner`) in `scenarios.yaml`.
* **Exobiology Genera & Variants**: Expanded `genuses.yaml` and `species_variants_reference.yaml` with mappings for `Aleoida Gravis (D)` (`Aleoida_05_D`, `Aleoids_05_D`), `Stratum Cucumisis (W)` (`Stratum_06_W`), `Recepta Umbrux (O)` (`Recepta_01_O`), `Cactoida Vermis (Y)` (`Cactoid_03_Y`), `Tussock Virgam (Y)` (`Tussocks_14_Y`), and added `Bacterias` alias under Bacterium.
* **Weapon Modules & Surface Mining**: Added aliases for engineered/experimental weapon variants (`Overloaded_Beam_Laser`, `Regenerative_Burst_Laser`, `Force_Impact_Cannon`, `Exposing_Missiles`), `_free` variants for Large Planetary Vehicle Hangars (sizes 2, 4, 6), new Rhino SRV bays, surface mining commodities, and `PlanetaryMiningLocation` surface signals.
* **StarPos Capture on Discovery**: Captured `StarPos` 3D spatial coordinates on `FSSDiscoveryScan` events in `journal_jump.py`.

### Changed
* **Database Schema Lowercase Standardization**: Standardized column names, secondary index definitions, and primary key constraints across all table DDL files (`01_systems.sql` through `11_station_materials.sql`, `create_all_indexes.sql`, `add_constraints.sql`) to explicit lowercase to harmonize with PostgreSQL default identifier folding.
* **DLQ Generator Column Mapping**: Refactored `generate_dlq_sp.py` to target lowercase SQL columns and aliases while maintaining case-sensitive key resolution for raw EDDN JSON payloads.
* **Station Type Normalization**: Mapped `DockablePlanetStation` to canonical `Planetary Port` in `station_types.yaml`.
* **Stored Procedures Synchronization**: Regenerated `sp_normalize_galaxy_data.sql` and `sp_process_eddn_dlq.sql` to incorporate updated normalizations and lowercase schema targets.

### Fixed
* **Ship Alias Miscategorizations**: Corrected misclassified ship model aliases in `ships.yaml`, moving `Explorer_Nx` under Mandalay and `Mediumtransport01` under Type-8 Transporter.
* **Commodity Noise Filtering**: Filtered unmarketable drone/limpet commodities (`Drones` / `NonMarketable`) from inserting into `station_commodities`.
* **Signal Clutter Elimination**: Filtered ephemeral personal mission USS signals (`$USS_Type_MissionTarget`) in `fss_signal.py` to prevent table bloat from single-instance player mission sites.
* **Biological Genus Deduplication**: Deduplicated biological genus arrays in `journal_scan.py` across `FSSBodySignals` and `SAASignalsFound` events.

### Testing
* **Validation & Guardrail Coverage**: Added unit test coverage in `tests/test_eddn_utils.py` (timestamp boundary checks and station name sanitization), `tests/test_eddn_router.py` (DLQ routing on invalid timestamps/system addresses), and `tests/test_eddn_transformers.py` (footfall parsing, market ID guards, limpet filtering, and genus deduplication).

---

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

"""DuckDB vectorized streaming bootstrap ingestion for Spansh galaxy data dumps.

Loads massive NDJSON chunk files through DuckDB's in-memory columnar engine,
pushes structured rows directly into PostgreSQL staging tables via the native
libpq postgres_scanner extension, and executes bulk inserts or incremental
``ON CONFLICT DO UPDATE`` upserts into the canonical domain schema.

Key capabilities:
    - Resume-safe per-table checkpointing via ``_ingested_tables``.
    - YAML-driven Frontier token normalization at ingest time.
    - Configurable ``bulk`` and ``upsert`` ingestion strategies.
    - Optional post-load ``sp_normalize_galaxy_data`` stored procedure invocation.
"""

import contextlib
import datetime
import logging
import os
import sys
import time
from pathlib import Path

import duckdb
import psycopg

from eddn.normalizers import NormalizerManager


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Full columns_sql STRUCT for read_json_auto — captures every field from
# galaxy.schema.json with no data dropped.
# ---------------------------------------------------------------------------
COLUMNS_SQL = """
    columns = {
        'id64':                     'UBIGINT',
        'name':                     'VARCHAR',
        'coords':                   'STRUCT(x DOUBLE, y DOUBLE, z DOUBLE)',
        'allegiance':               'VARCHAR',
        'government':               'VARCHAR',
        'primaryEconomy':           'VARCHAR',
        'secondaryEconomy':         'VARCHAR',
        'security':                 'VARCHAR',
        'population':               'BIGINT',
        'bodyCount':                'INTEGER',
        'date':                     'VARCHAR',
        'controllingPower':         'VARCHAR',
        'powerState':               'VARCHAR',
        'powerStateControlProgress': 'DOUBLE',
        'powerStateReinforcement':  'DOUBLE',
        'powerStateUndermining':    'DOUBLE',
        'powers':                   'VARCHAR[]',
        'controllingFaction':       'JSON',
        'powerConflictProgress':    'JSON',
        'thargoidWar':              'JSON',
        'timestamps':               'JSON',
        'factions':                 'JSON',
        'bodies': 'STRUCT(
            id64                        UBIGINT,
            bodyId                      UBIGINT,
            name                        VARCHAR,
            type                        VARCHAR,
            subType                     VARCHAR,
            distanceToArrival           DOUBLE,
            orbitalPeriod               DOUBLE,
            semiMajorAxis               DOUBLE,
            orbitalEccentricity         DOUBLE,
            orbitalInclination          DOUBLE,
            argOfPeriapsis              DOUBLE,
            meanAnomaly                 DOUBLE,
            ascendingNode               DOUBLE,
            rotationalPeriod            DOUBLE,
            rotationalPeriodTidallyLocked BOOLEAN,
            axialTilt                   DOUBLE,
            surfaceTemperature          DOUBLE,
            radius                      DOUBLE,
            isLandable                  BOOLEAN,
            gravity                     DOUBLE,
            earthMasses                 DOUBLE,
            surfacePressure             DOUBLE,
            volcanismType               VARCHAR,
            atmosphereType              VARCHAR,
            terraformingState           VARCHAR,
            reserveLevel                VARCHAR,
            mainStar                    BOOLEAN,
            age                         INTEGER,
            spectralClass               VARCHAR,
            luminosity                  VARCHAR,
            absoluteMagnitude           DOUBLE,
            solarMasses                 DOUBLE,
            solarRadius                 DOUBLE,
            atmosphereComposition       JSON,
            solidComposition            JSON,
            materials                   JSON,
            parents                     JSON,
            rings                       STRUCT(
                id64 UBIGINT,
                name VARCHAR,
                type VARCHAR,
                mass DOUBLE,
                innerRadius DOUBLE,
                outerRadius DOUBLE,
                signals JSON
            )[],
            belts                       STRUCT(
                id64 UBIGINT,
                name VARCHAR,
                type VARCHAR,
                mass DOUBLE,
                innerRadius DOUBLE,
                outerRadius DOUBLE
            )[],
            signals                     JSON,
            timestamps                  JSON,
            updateTime                  VARCHAR,
            stations                    STRUCT(
                id                          UBIGINT,
                name                        VARCHAR,
                realName                    VARCHAR,
                carrierName                 VARCHAR,
                type                        VARCHAR,
                state                       VARCHAR,
                distanceToArrival           DOUBLE,
                latitude                    DOUBLE,
                longitude                   DOUBLE,
                allegiance                  VARCHAR,
                government                  VARCHAR,
                controllingFaction          VARCHAR,
                controllingFactionState     VARCHAR,
                primaryEconomy              VARCHAR,
                secondaryEconomy            VARCHAR,
                economies                   JSON,
                landingPads                 STRUCT(large INTEGER, medium INTEGER, small INTEGER),
                carrierDockingAccess        VARCHAR,
                updateTime                  VARCHAR,
                services                    VARCHAR[],
                market                      STRUCT(
                    updateTime VARCHAR,
                    prohibitedCommodities VARCHAR[],
                    commodities STRUCT(
                        commodityId INTEGER,
                        name VARCHAR,
                        symbol VARCHAR,
                        category VARCHAR,
                        demand INTEGER,
                        supply INTEGER,
                        buyPrice INTEGER,
                        sellPrice INTEGER
                    )[]
                ),
                shipyard                    STRUCT(
                    updateTime VARCHAR,
                    ships STRUCT(
                        shipId INTEGER,
                        name VARCHAR,
                        symbol VARCHAR
                    )[]
                ),
                outfitting                  STRUCT(
                    updateTime VARCHAR,
                    modules STRUCT(
                        moduleId INTEGER,
                        name VARCHAR,
                        symbol VARCHAR,
                        category VARCHAR,
                        class INTEGER,
                        rating VARCHAR
                    )[]
                )
            )[]
        )[]',
        'stations': 'STRUCT(
            id                          UBIGINT,
            name                        VARCHAR,
            realName                    VARCHAR,
            carrierName                 VARCHAR,
            type                        VARCHAR,
            state                       VARCHAR,
            distanceToArrival           DOUBLE,
            latitude                    DOUBLE,
            longitude                   DOUBLE,
            allegiance                  VARCHAR,
            government                  VARCHAR,
            controllingFaction          VARCHAR,
            controllingFactionState     VARCHAR,
            primaryEconomy              VARCHAR,
            secondaryEconomy            VARCHAR,
            economies                   JSON,
            landingPads                 STRUCT(large INTEGER, medium INTEGER, small INTEGER),
            carrierDockingAccess        VARCHAR,
            updateTime                  VARCHAR,
            services                    VARCHAR[],
            market                      STRUCT(
                updateTime VARCHAR,
                prohibitedCommodities VARCHAR[],
                commodities STRUCT(
                    commodityId INTEGER,
                    name VARCHAR,
                    symbol VARCHAR,
                    category VARCHAR,
                    demand INTEGER,
                    supply INTEGER,
                    buyPrice INTEGER,
                    sellPrice INTEGER
                )[]
            ),
            shipyard                    STRUCT(
                updateTime VARCHAR,
                ships STRUCT(
                    shipId INTEGER,
                    name VARCHAR,
                    symbol VARCHAR
                )[]
            ),
            outfitting                  STRUCT(
                updateTime VARCHAR,
                modules STRUCT(
                    moduleId INTEGER,
                    name VARCHAR,
                    symbol VARCHAR,
                    category VARCHAR,
                    class INTEGER,
                    rating VARCHAR
                )[]
            )
        )[]'
    }
"""


def _insert_batch(
    conn: duckdb.DuckDBPyConnection,
    paths_sql_list: str,
    ignore_errors_str: str,
    mode: str,
    pending_table_map: dict,
    limit: int | None = None,
    force: bool = False,
) -> None:
    """Extracts nested JSON using DuckDB's vectorized engine and merges into PostgreSQL tables.

    Pushes formatted batch data into temporary PostgreSQL staging tables (`_stg_*`)
    and executes bulk inserts or incremental `ON CONFLICT DO UPDATE` upserts into target domain tables.

    Args:
        conn: DuckDB connection attached to PostgreSQL target database.
        paths_sql_list: Formatted SQL list string of chunk file paths.
        ignore_errors_str: DuckDB 'true' or 'false' string for JSON error handling.
        mode: Ingestion strategy ('bulk' or 'upsert').
        pending_table_map: Dictionary mapping file paths to lists of missing tables.
        limit: Optional record limit per file for schema validation.
        force: If True, relaxes update_dtm checks during upsert.
    """
    limit_clause = f"LIMIT {limit}" if limit else ""
    conn.execute("DROP VIEW IF EXISTS batch_raw;")

    logger.info("   --> Staging batch NDJSON view streaming source...")
    conn.execute(f"""
        CREATE TEMP VIEW batch_raw AS
        SELECT *, filename AS _src_file FROM read_json_auto(
            {paths_sql_list},
            {COLUMNS_SQL},
            format='newline_delimited',
            filename=true,
            maximum_object_size=268435456,
            ignore_errors={ignore_errors_str}
        )
        {limit_clause};
    """)
    read_expr = "batch_raw"
    now_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")  # Load YAML normalization mappings
    normalizer = NormalizerManager()
    ring_type_map = normalizer.maps.get("ring_types", {})
    station_type_map = normalizer.maps.get("station_types", {})
    economy_map = normalizer.maps.get("economies", {})
    security_map = normalizer.maps.get("securities", {})
    government_map = normalizer.maps.get("governments", {})
    allegiance_map = normalizer.maps.get("allegiances", {})
    faction_state_map = normalizer.maps.get("faction_states", {})
    docking_access_map = normalizer.maps.get("carrier_docking_access", {})
    ship_map = normalizer.maps.get("ships", {})
    commodity_map = normalizer.maps.get("commodities", {})
    commodity_category_map = normalizer.maps.get("commodity_categories", {})
    module_map = normalizer.maps.get("modules", {})
    module_category_map = normalizer.maps.get("module_categories", {})
    reserve_level_map = normalizer.maps.get("reserve_levels", {})
    terraform_state_map = normalizer.maps.get("terraform_states", {})
    planet_class_map = normalizer.maps.get("planet_classes", {})
    star_type_map = normalizer.maps.get("star_types", {})
    sub_type_map = {**planet_class_map, **star_type_map}

    def _duckdb_case(mapping: dict[str, str], column_expr: str) -> str:
        """Builds a DuckDB CASE WHEN expression from a normalization mapping dictionary."""
        if not mapping:
            return column_expr
        whens = [
            f"WHEN LOWER(TRIM(CAST({column_expr} AS VARCHAR))) = '{raw_var.replace("'", "''")}' THEN '{canonical.replace("'", "''")}'"
            for raw_var, canonical in mapping.items()
        ]
        return f"CASE {' '.join(whens)} ELSE {column_expr} END"

    def _where_dtm(table_name: str) -> str:
        """Returns a monotonic timestamp gating WHERE clause, or empty string if force mode."""
        if force:
            return ""
        return f"WHERE EXCLUDED.update_dtm >= {table_name}.update_dtm OR {table_name}.update_dtm IS NULL"

    def _execute_table(table_name, temp_table_name, select_sql, dedupe_qualify, upsert_sql, keep_staging=False, is_parent=False):
        """Stages, deduplicates, and upserts a single domain table from the batch view."""
        needed_files = [file_name for file_name, missing_tables in pending_table_map.items() if table_name in missing_tables]

        run_upsert = True
        files_to_stage = needed_files

        if not needed_files:
            if is_parent and mode == "upsert":
                logger.info(
                    f"   [Skipping '{table_name}' Upsert] Already ingested, but building staging table for child cleanup..."
                )
                files_to_stage = list(pending_table_map.keys())
                run_upsert = False
            else:
                logger.info(f"   [Skipping '{table_name}'] Already ingested for all files in this batch.")
                return

        sys_files_sql = "[" + ", ".join([f"'{file_name.replace("'", "''")}'" for file_name in files_to_stage]) + "]"
        query = select_sql.format(sys_files_sql=sys_files_sql)
        if dedupe_qualify:
            query += f"\n{dedupe_qualify}"

        try:
            logger.info(f"   Parsing '{table_name}' into staging table...")
            conn.execute(f"CREATE TEMP TABLE {temp_table_name} AS {query};")

            if mode == "bulk":
                logger.info(f"   Bulk loading '{table_name}' to PostgreSQL...")
                conn.execute(f"CALL postgres_execute('pg', 'DROP TABLE IF EXISTS _stg_{table_name};');")
                conn.execute(f"CREATE TABLE pg._stg_{table_name} AS SELECT * FROM {temp_table_name};")
                conn.execute(f"DROP TABLE {temp_table_name};")

                if run_upsert:
                    bulk_sql = upsert_sql.split("ON CONFLICT")[0].strip() + ";"
                    conn.execute(f"CALL postgres_execute('pg', $${bulk_sql}$$);")

                if not keep_staging:
                    conn.execute(f"CALL postgres_execute('pg', 'DROP TABLE IF EXISTS _stg_{table_name};');")

                for file_name in needed_files:
                    safe_file = file_name.replace("'", "''")
                    safe_table = table_name.replace("'", "''")
                    conn.execute(
                        f"INSERT INTO pg._ingested_tables (filename, table_name, ingested_at) VALUES ('{safe_file}', '{safe_table}', '{now_str}') ON CONFLICT DO NOTHING;"
                    )
                logger.info(f"   ✅ Table '{table_name}' committed successfully.")
            elif mode == "upsert":
                logger.info(f"   Upserting '{table_name}' to PostgreSQL...")
                conn.execute(f"CALL postgres_execute('pg', 'DROP TABLE IF EXISTS _stg_{table_name};');")
                conn.execute(f"CREATE TABLE pg._stg_{table_name} AS SELECT * FROM {temp_table_name};")
                conn.execute(f"DROP TABLE {temp_table_name};")

                if run_upsert:
                    conn.execute(f"CALL postgres_execute('pg', $${upsert_sql}$$);")

                if not keep_staging:
                    conn.execute(f"CALL postgres_execute('pg', 'DROP TABLE IF EXISTS _stg_{table_name};');")

                for file_name in needed_files:
                    safe_file = file_name.replace("'", "''")
                    safe_table = table_name.replace("'", "''")
                    conn.execute(
                        f"INSERT INTO pg._ingested_tables (filename, table_name, ingested_at) VALUES ('{safe_file}', '{safe_table}', '{now_str}') ON CONFLICT DO NOTHING;"
                    )
                logger.info(f"   ✅ Table '{table_name}' committed successfully.")

        except Exception as error:
            logger.error(f"   ❌ Failed to process table '{table_name}': {error}")
            raise

    # 1. systems
    sys_select = f"""
        SELECT 
            id64, name, 
            CASE WHEN coords IS NOT NULL THEN '(' || coords.x || ', ' || coords.y || ', ' || coords.z || ')' ELSE NULL END AS coords, 
            {_duckdb_case(allegiance_map, "allegiance")} AS allegiance, 
            {_duckdb_case(government_map, "government")} AS government,
            {_duckdb_case(economy_map, "primaryEconomy")} AS primaryEconomy,
            {_duckdb_case(economy_map, "secondaryEconomy")} AS secondaryEconomy,
            {_duckdb_case(security_map, "security")} AS security,
            population, 
            bodyCount, controllingPower, powerState, powerStateControlProgress, 
            powerStateReinforcement, powerStateUndermining, CAST(to_json(powers) AS VARCHAR) AS powers, 
            CAST(controllingFaction AS VARCHAR) AS controllingFaction, 
            CAST(powerConflictProgress AS VARCHAR) AS powerConflictProgress, 
            CAST(thargoidWar AS VARCHAR) AS thargoidWar, CAST(timestamps AS VARCHAR) AS timestamps,
            TRY_CAST(date AS TIMESTAMP) AS update_dtm
        FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}
    """
    sys_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY id64 ORDER BY TRY_CAST(date AS TIMESTAMP) DESC NULLS LAST) = 1"
    sys_upsert = f"""
        INSERT INTO systems (
            id64, name, coords, allegiance, 
            government, primaryEconomy, secondaryEconomy, security, population, 
            bodyCount, controllingPower, powerState, powerStateControlProgress, 
            powerStateReinforcement, powerStateUndermining, powers, 
            controllingFaction, powerConflictProgress, thargoidWar, timestamps, update_dtm
        )
        SELECT 
            "id64", "name", "coords"::cube, "allegiance", 
            "government", "primaryEconomy", "secondaryEconomy", "security", "population", 
            "bodyCount", "controllingPower", "powerState", "powerStateControlProgress", 
            "powerStateReinforcement", "powerStateUndermining", "powers"::jsonb, 
            "controllingFaction"::jsonb, "powerConflictProgress"::jsonb, "thargoidWar"::jsonb, "timestamps"::jsonb, "update_dtm"
        FROM _stg_systems 
        ON CONFLICT (id64) DO UPDATE SET 
            name=EXCLUDED.name, coords=EXCLUDED.coords, allegiance=EXCLUDED.allegiance, 
            government=EXCLUDED.government, primaryEconomy=EXCLUDED.primaryEconomy, secondaryEconomy=EXCLUDED.secondaryEconomy, 
            security=EXCLUDED.security, population=EXCLUDED.population, bodyCount=EXCLUDED.bodyCount, 
            controllingPower=EXCLUDED.controllingPower, powerState=EXCLUDED.powerState, powerStateControlProgress=EXCLUDED.powerStateControlProgress, 
            powerStateReinforcement=EXCLUDED.powerStateReinforcement, powerStateUndermining=EXCLUDED.powerStateUndermining, powers=EXCLUDED.powers, 
            controllingFaction=EXCLUDED.controllingFaction, powerConflictProgress=EXCLUDED.powerConflictProgress, thargoidWar=EXCLUDED.thargoidWar, timestamps=EXCLUDED.timestamps,
            update_dtm=EXCLUDED.update_dtm
        {_where_dtm("systems")};
    """
    _execute_table("systems", "_inc_sys", sys_select, sys_dedupe, sys_upsert)

    # 2. system_factions
    fac_select = f"""
        SELECT system_id64, name, state, allegiance, government, influence, activeStates, pendingStates, recoveringStates, update_dtm FROM (
            SELECT 
                s.id64 AS system_id64, f->>'name' AS name, f->>'state' AS state,
                {_duckdb_case(allegiance_map, "f->>'allegiance'")} AS allegiance, 
                {_duckdb_case(government_map, "f->>'government'")} AS government,
                (f->>'influence')::DOUBLE AS influence, 
                CAST(f->'activeStates' AS VARCHAR) AS activeStates, CAST(f->'pendingStates' AS VARCHAR) AS pendingStates, 
                CAST(f->'recoveringStates' AS VARCHAR) AS recoveringStates,
                TRY_CAST(s.date AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, factions, _src_file, date FROM {read_expr} WHERE factions IS NOT NULL AND list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(json_extract_string(s.factions::VARCHAR, '$[*]')::JSON[]) AS t(f) WHERE f->>'name' IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (PARTITION BY s.id64, f->>'name' ORDER BY TRY_CAST(s.date AS TIMESTAMP) DESC NULLS LAST) = 1
        )
    """
    fac_dedupe = ""  # Handled in subquery
    fac_upsert = f"""
        INSERT INTO system_factions (system_id64, name, state, allegiance, government, influence, activeStates, pendingStates, recoveringStates, update_dtm)
        SELECT "system_id64", "name", "state", "allegiance", "government", "influence", "activeStates"::jsonb, "pendingStates"::jsonb, "recoveringStates"::jsonb, "update_dtm" FROM _stg_system_factions 
        ON CONFLICT (system_id64, name) DO UPDATE SET 
            state=EXCLUDED.state, allegiance=EXCLUDED.allegiance, government=EXCLUDED.government, influence=EXCLUDED.influence, 
            activeStates=EXCLUDED.activeStates, pendingStates=EXCLUDED.pendingStates, recoveringStates=EXCLUDED.recoveringStates,
            update_dtm=EXCLUDED.update_dtm
        {_where_dtm("system_factions")};
    """
    _execute_table("system_factions", "_inc_fac", fac_select, fac_dedupe, fac_upsert)

    # 3. bodies
    bod_select = f"""
        SELECT 
            s.id64 AS system_id64, b.id64, b.bodyId, b.name, b.type, 
            {_duckdb_case(sub_type_map, "b.subType")} AS subType, 
            b.distanceToArrival, b.orbitalPeriod, b.semiMajorAxis, b.orbitalEccentricity, b.orbitalInclination, 
            b.argOfPeriapsis, b.meanAnomaly, b.ascendingNode, b.rotationalPeriod, b.rotationalPeriodTidallyLocked, b.axialTilt, 
            b.surfaceTemperature, b.radius, b.isLandable, b.gravity, b.earthMasses, b.surfacePressure, b.volcanismType, 
            b.atmosphereType, 
            {_duckdb_case(terraform_state_map, "b.terraformingState")} AS terraformingState, 
            {_duckdb_case(reserve_level_map, "b.reserveLevel")} AS reserveLevel, 
            b.mainStar, b.age, b.spectralClass, b.luminosity, 
            b.absoluteMagnitude, b.solarMasses, b.solarRadius, CAST(b.atmosphereComposition AS VARCHAR) AS atmosphereComposition, 
            CAST(b.solidComposition AS VARCHAR) AS solidComposition, CAST(b.materials AS VARCHAR) AS materials, 
            CAST(b.parents AS VARCHAR) AS parents, CAST(b.timestamps AS VARCHAR) AS timestamps,
            TRY_CAST(b.updateTime AS TIMESTAMP) AS update_dtm
        FROM (SELECT id64, bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
        UNNEST(s.bodies) AS t(b) WHERE b.id64 IS NOT NULL
    """
    bod_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY b.id64 ORDER BY TRY_CAST(b.updateTime AS TIMESTAMP) DESC NULLS LAST) = 1"
    bod_upsert = f"""
        INSERT INTO bodies (
            system_id64, id64, bodyId, name, type, subType, 
            distanceToArrival, orbitalPeriod, semiMajorAxis, orbitalEccentricity, orbitalInclination, 
            argOfPeriapsis, meanAnomaly, ascendingNode, rotationalPeriod, rotationalPeriodTidallyLocked, 
            axialTilt, surfaceTemperature, radius, isLandable, gravity, earthMasses, surfacePressure, 
            volcanismType, atmosphereType, terraformingState, reserveLevel, mainStar, age, spectralClass, 
            luminosity, absoluteMagnitude, solarMasses, solarRadius, atmosphereComposition, 
            solidComposition, materials, parents, timestamps, update_dtm
        )
        SELECT 
            "system_id64", "id64", "bodyId", "name", "type", "subType", 
            "distanceToArrival", "orbitalPeriod", "semiMajorAxis", "orbitalEccentricity", "orbitalInclination", 
            "argOfPeriapsis", "meanAnomaly", "ascendingNode", "rotationalPeriod", "rotationalPeriodTidallyLocked", 
            "axialTilt", "surfaceTemperature", "radius", "isLandable", "gravity", "earthMasses", "surfacePressure", 
            "volcanismType", "atmosphereType", "terraformingState", "reserveLevel", "mainStar", "age", "spectralClass", 
            "luminosity", "absoluteMagnitude", "solarMasses", "solarRadius", "atmosphereComposition"::jsonb, 
            "solidComposition"::jsonb, "materials"::jsonb, "parents"::jsonb, "timestamps"::jsonb, "update_dtm"
        FROM _stg_bodies 
        ON CONFLICT (id64) DO UPDATE SET 
            system_id64=EXCLUDED.system_id64, bodyId=EXCLUDED.bodyId, name=EXCLUDED.name, type=EXCLUDED.type, subType=EXCLUDED.subType, 
            distanceToArrival=EXCLUDED.distanceToArrival, orbitalPeriod=EXCLUDED.orbitalPeriod, 
            semiMajorAxis=EXCLUDED.semiMajorAxis, orbitalEccentricity=EXCLUDED.orbitalEccentricity, orbitalInclination=EXCLUDED.orbitalInclination, 
            argOfPeriapsis=EXCLUDED.argOfPeriapsis, meanAnomaly=EXCLUDED.meanAnomaly, ascendingNode=EXCLUDED.ascendingNode, 
            rotationalPeriod=EXCLUDED.rotationalPeriod, rotationalPeriodTidallyLocked=EXCLUDED.rotationalPeriodTidallyLocked, 
            axialTilt=EXCLUDED.axialTilt, surfaceTemperature=EXCLUDED.surfaceTemperature, radius=EXCLUDED.radius, isLandable=EXCLUDED.isLandable, 
            gravity=EXCLUDED.gravity, earthMasses=EXCLUDED.earthMasses, surfacePressure=EXCLUDED.surfacePressure, volcanismType=EXCLUDED.volcanismType, 
            atmosphereType=EXCLUDED.atmosphereType, terraformingState=EXCLUDED.terraformingState, reserveLevel=EXCLUDED.reserveLevel, mainStar=EXCLUDED.mainStar, 
            age=EXCLUDED.age, spectralClass=EXCLUDED.spectralClass, luminosity=EXCLUDED.luminosity, absoluteMagnitude=EXCLUDED.absoluteMagnitude, 
            solarMasses=EXCLUDED.solarMasses, solarRadius=EXCLUDED.solarRadius, atmosphereComposition=EXCLUDED.atmosphereComposition, 
            solidComposition=EXCLUDED.solidComposition, materials=EXCLUDED.materials, parents=EXCLUDED.parents, 
            timestamps=EXCLUDED.timestamps, update_dtm=EXCLUDED.update_dtm 
        {_where_dtm("bodies")};
    """
    _execute_table("bodies", "_inc_bod", bod_select, bod_dedupe, bod_upsert)

    # 3.1 body_rings
    ring_select = f"""
        SELECT body_id64, id64, name, type, mass, innerRadius, outerRadius, density, signals, update_dtm FROM (
            SELECT 
                b.id64 AS body_id64, r.id64 AS id64, 
                r.name AS name,
                {_duckdb_case(ring_type_map, "r.type")} AS type, 
                r.mass AS mass, 
                r.innerRadius AS innerRadius, 
                r.outerRadius AS outerRadius,
                r.mass / NULLIF(ABS(PI() * POW(r.outerRadius, 2) - PI() * POW(r.innerRadius, 2)), 0) AS density,
                CAST(r.signals AS VARCHAR) AS signals,
                TRY_CAST(b.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.bodies) AS t(b), UNNEST(b.rings) AS x(r)
            WHERE b.id64 IS NOT NULL AND r.name IS NOT NULL
        )
    """
    ring_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY body_id64, name ORDER BY body_id64) = 1"
    ring_upsert = f"""
        INSERT INTO body_rings (body_id64, id64, name, type, mass, innerRadius, outerRadius, density, signals, update_dtm)
        SELECT "body_id64", "id64", "name", "type", "mass", "innerRadius", "outerRadius", "density", "signals"::jsonb, "update_dtm" FROM _stg_body_rings
        ON CONFLICT (body_id64, name) DO UPDATE SET 
            id64=EXCLUDED.id64, type=EXCLUDED.type, mass=EXCLUDED.mass, innerRadius=EXCLUDED.innerRadius, 
            outerRadius=EXCLUDED.outerRadius, density=EXCLUDED.density, signals=EXCLUDED.signals,
            update_dtm=EXCLUDED.update_dtm
        {_where_dtm("body_rings")};
    """
    _execute_table("body_rings", "_inc_ring", ring_select, ring_dedupe, ring_upsert)

    # 3.2 body_belts
    belt_select = f"""
        SELECT body_id64, name, type, mass, innerRadius, outerRadius, density, update_dtm FROM (
            SELECT 
                b.id64 AS body_id64, 
                r.name AS name,
                {_duckdb_case(ring_type_map, "r.type")} AS type, 
                r.mass AS mass, 
                r.innerRadius AS innerRadius, 
                r.outerRadius AS outerRadius,
                r.mass / NULLIF(ABS(PI() * POW(r.outerRadius, 2) - PI() * POW(r.innerRadius, 2)), 0) AS density,
                TRY_CAST(b.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.bodies) AS t(b), UNNEST(b.belts) AS x(r)
            WHERE b.id64 IS NOT NULL AND r.name IS NOT NULL
        )
    """
    belt_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY body_id64, name ORDER BY body_id64) = 1"
    belt_upsert = f"""
        INSERT INTO body_belts (body_id64, name, type, mass, innerRadius, outerRadius, density, update_dtm)
        SELECT "body_id64", "name", "type", "mass", "innerRadius", "outerRadius", "density", "update_dtm" FROM _stg_body_belts
        ON CONFLICT (body_id64, name) DO UPDATE SET 
            type=EXCLUDED.type, mass=EXCLUDED.mass, innerRadius=EXCLUDED.innerRadius, 
            outerRadius=EXCLUDED.outerRadius, density=EXCLUDED.density,
            update_dtm=EXCLUDED.update_dtm
        {_where_dtm("body_belts")};
    """
    _execute_table("body_belts", "_inc_belt", belt_select, belt_dedupe, belt_upsert)

    # 4. body_signals
    sig_select = f"""
        SELECT 
            s.id64 AS system_id64, b.id64 AS body_id64, CAST(json_extract(b.signals, '$.signals') AS VARCHAR) AS signals, 
            CAST(json_transform(json_extract(b.signals, '$.genuses'), '["VARCHAR"]') AS VARCHAR[]) AS genuses, 
            TRY_CAST(b.signals->>'updateTime' AS TIMESTAMP) AS update_dtm
        FROM (SELECT id64, bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
        UNNEST(s.bodies) AS t(b) WHERE b.id64 IS NOT NULL AND b.signals IS NOT NULL
    """
    sig_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY body_id64 ORDER BY TRY_CAST(b.signals->>'updateTime' AS TIMESTAMP) DESC NULLS LAST) = 1"
    sig_upsert = f"""
        INSERT INTO body_signals (system_id64, body_id64, signals, genuses, update_dtm)
        SELECT "system_id64", "body_id64", "signals"::jsonb, "genuses", "update_dtm" FROM _stg_body_signals 
        ON CONFLICT (body_id64) DO UPDATE SET 
            system_id64=EXCLUDED.system_id64, signals=EXCLUDED.signals, genuses=EXCLUDED.genuses,
            update_dtm=EXCLUDED.update_dtm
        {_where_dtm("body_signals")};
    """
    _execute_table("body_signals", "_inc_sig", sig_select, sig_dedupe, sig_upsert)

    # 5. stations
    sta_select = f"""
        WITH all_stations AS (
            SELECT 
                'system' AS source, s.id64 AS system_id64, NULL::UBIGINT AS body_source_id64, st.id AS market_id, 
                st.name, st.realName, st.carrierName,
                {_duckdb_case(station_type_map, "st.type")} AS type,
                {_duckdb_case(faction_state_map, "st.state")} AS state, 
                st.distanceToArrival, st.latitude, st.longitude, 
                {_duckdb_case(allegiance_map, "st.allegiance")} AS allegiance,
                {_duckdb_case(government_map, "st.government")} AS government,
                st.controllingFaction, 
                {_duckdb_case(faction_state_map, "st.controllingFactionState")} AS controllingFactionState,
                {_duckdb_case(economy_map, "st.primaryEconomy")} AS primaryEconomy, 
                {_duckdb_case(economy_map, "st.secondaryEconomy")} AS secondaryEconomy,
                CAST(to_json(st.economies) AS VARCHAR) AS economies, 
                {_duckdb_case(docking_access_map, "st.carrierDockingAccess")} AS carrierDockingAccess, 
                (st.landingPads.large)::INTEGER AS pad_large,
                (st.landingPads.medium)::INTEGER AS pad_medium,
                (st.landingPads.small)::INTEGER AS pad_small,
                st.services AS services_arr,
                list_transform(st.market.prohibitedCommodities, x -> x::VARCHAR)::VARCHAR[] AS prohibited_commodities,
                TRY_CAST(st.market.updateTime AS TIMESTAMP) AS market_updated_at,
                TRY_CAST(st.shipyard.updateTime AS TIMESTAMP) AS shipyard_updated_at,
                TRY_CAST(st.outfitting.updateTime AS TIMESTAMP) AS outfitting_updated_at,
                TRY_CAST(st.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, stations, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.stations) AS t(st) WHERE st.name IS NOT NULL
            UNION ALL
            SELECT 
                'body' AS source, s.id64 AS system_id64, b.id64 AS body_source_id64, st.id AS market_id, 
                st.name, st.realName, st.carrierName,
                {_duckdb_case(station_type_map, "st.type")} AS type,
                {_duckdb_case(faction_state_map, "st.state")} AS state, 
                st.distanceToArrival, st.latitude, st.longitude, 
                {_duckdb_case(allegiance_map, "st.allegiance")} AS allegiance,
                {_duckdb_case(government_map, "st.government")} AS government,
                st.controllingFaction, 
                {_duckdb_case(faction_state_map, "st.controllingFactionState")} AS controllingFactionState,
                {_duckdb_case(economy_map, "st.primaryEconomy")} AS primaryEconomy, 
                {_duckdb_case(economy_map, "st.secondaryEconomy")} AS secondaryEconomy,
                CAST(to_json(st.economies) AS VARCHAR) AS economies, 
                {_duckdb_case(docking_access_map, "st.carrierDockingAccess")} AS carrierDockingAccess, 
                (st.landingPads.large)::INTEGER AS pad_large,
                (st.landingPads.medium)::INTEGER AS pad_medium,
                (st.landingPads.small)::INTEGER AS pad_small,
                st.services AS services_arr,
                list_transform(st.market.prohibitedCommodities, x -> x::VARCHAR)::VARCHAR[] AS prohibited_commodities,
                TRY_CAST(st.market.updateTime AS TIMESTAMP) AS market_updated_at,
                TRY_CAST(st.shipyard.updateTime AS TIMESTAMP) AS shipyard_updated_at,
                TRY_CAST(st.outfitting.updateTime AS TIMESTAMP) AS outfitting_updated_at,
                TRY_CAST(st.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.bodies) AS t(b), UNNEST(b.stations) AS t2(st) WHERE b.id64 IS NOT NULL AND b.stations IS NOT NULL AND st.name IS NOT NULL
        ) 
        SELECT source, system_id64, body_source_id64, market_id, name, realName, carrierName, type, state, distanceToArrival, latitude, longitude, allegiance, government, controllingFaction, controllingFactionState, primaryEconomy, secondaryEconomy, economies, carrierDockingAccess, pad_large, pad_medium, pad_small, services_arr, prohibited_commodities, market_updated_at, shipyard_updated_at, outfitting_updated_at, update_dtm FROM all_stations 
    """
    sta_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY update_dtm DESC NULLS LAST) = 1"
    sta_upsert = f"""
        INSERT INTO stations (source, system_id64, body_source_id64, market_id, name, realName, carrierName, type, state, distanceToArrival, latitude, longitude, allegiance, government, controllingFaction, controllingFactionState, primaryEconomy, secondaryEconomy, economies, carrierDockingAccess, pad_large, pad_medium, pad_small, services_arr, prohibited_commodities, market_updated_at, shipyard_updated_at, outfitting_updated_at, update_dtm)
        SELECT "source", "system_id64", "body_source_id64", "market_id", "name", "realName", "carrierName", "type", "state", "distanceToArrival", "latitude", "longitude", "allegiance", "government", "controllingFaction", "controllingFactionState", "primaryEconomy", "secondaryEconomy", "economies"::jsonb, "carrierDockingAccess", "pad_large", "pad_medium", "pad_small", "services_arr", "prohibited_commodities", "market_updated_at", "shipyard_updated_at", "outfitting_updated_at", "update_dtm" FROM _stg_stations 
        ON CONFLICT (market_id) DO UPDATE SET 
            source=EXCLUDED.source, system_id64=EXCLUDED.system_id64, body_source_id64=EXCLUDED.body_source_id64, name=EXCLUDED.name, 
            realName=EXCLUDED.realName, carrierName=EXCLUDED.carrierName, type=EXCLUDED.type, state=EXCLUDED.state, 
            distanceToArrival=EXCLUDED.distanceToArrival, latitude=EXCLUDED.latitude, longitude=EXCLUDED.longitude, 
            allegiance=EXCLUDED.allegiance, government=EXCLUDED.government, controllingFaction=EXCLUDED.controllingFaction, 
            controllingFactionState=EXCLUDED.controllingFactionState, primaryEconomy=EXCLUDED.primaryEconomy, 
            secondaryEconomy=EXCLUDED.secondaryEconomy, economies=EXCLUDED.economies,
            carrierDockingAccess=EXCLUDED.carrierDockingAccess, 
            pad_large=EXCLUDED.pad_large, pad_medium=EXCLUDED.pad_medium, pad_small=EXCLUDED.pad_small, 
            services_arr=EXCLUDED.services_arr, prohibited_commodities=EXCLUDED.prohibited_commodities, 
            market_updated_at=EXCLUDED.market_updated_at, shipyard_updated_at=EXCLUDED.shipyard_updated_at, outfitting_updated_at=EXCLUDED.outfitting_updated_at,
            update_dtm=EXCLUDED.update_dtm
        {_where_dtm("stations")};
    """
    _execute_table("stations", "_inc_sta", sta_select, sta_dedupe, sta_upsert, keep_staging=True, is_parent=True)

    # 5a. station_commodities
    sta_comm_select = f"""
        SELECT market_id, name, symbol, category, commodityId, demand, supply, buyPrice, sellPrice, update_dtm FROM (
            SELECT 
                st.id AS market_id, 
                {_duckdb_case(commodity_map, "c.name")} AS name, 
                c.symbol, 
                {_duckdb_case(commodity_category_map, "c.category")} AS category, 
                (c.commodityId)::INTEGER AS commodityId, 
                (c.demand)::INTEGER AS demand, (c.supply)::INTEGER AS supply, 
                (c.buyPrice)::INTEGER AS buyPrice, (c.sellPrice)::INTEGER AS sellPrice,
                TRY_CAST(st.market.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, stations, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.stations) AS t(st), UNNEST(st.market.commodities) AS t3(c) WHERE st.name IS NOT NULL AND st.market IS NOT NULL
            UNION ALL
            SELECT 
                st.id AS market_id, 
                {_duckdb_case(commodity_map, "c.name")} AS name, 
                c.symbol, 
                {_duckdb_case(commodity_category_map, "c.category")} AS category, 
                (c.commodityId)::INTEGER AS commodityId, 
                (c.demand)::INTEGER AS demand, (c.supply)::INTEGER AS supply, 
                (c.buyPrice)::INTEGER AS buyPrice, (c.sellPrice)::INTEGER AS sellPrice,
                TRY_CAST(st.market.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.bodies) AS t(b), UNNEST(b.stations) AS t2(st), UNNEST(st.market.commodities) AS t3(c) WHERE b.id64 IS NOT NULL AND b.stations IS NOT NULL AND st.name IS NOT NULL AND st.market IS NOT NULL
        )
    """
    sta_comm_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id, commodityId ORDER BY update_dtm DESC NULLS LAST) = 1"
    sta_comm_upsert = f"""
        INSERT INTO station_commodities (market_id, name, symbol, category, commodityId, demand, supply, buyPrice, sellPrice, update_dtm) 
        SELECT "market_id", "name", "symbol", "category", "commodityId", "demand", "supply", "buyPrice", "sellPrice", "update_dtm" FROM _stg_station_commodities 
        ON CONFLICT (market_id, commodityid) DO UPDATE SET 
            symbol=EXCLUDED.symbol, category=EXCLUDED.category, name=EXCLUDED.name, 
            demand=EXCLUDED.demand, supply=EXCLUDED.supply, buyPrice=EXCLUDED.buyPrice, sellPrice=EXCLUDED.sellPrice,
            update_dtm=EXCLUDED.update_dtm
        {_where_dtm("station_commodities")};
    """
    _execute_table("station_commodities", "_inc_sta_comm", sta_comm_select, sta_comm_dedupe, sta_comm_upsert)
    conn.execute("""CALL postgres_execute('pg', $$
        DELETE FROM station_commodities sc USING _stg_stations stg
        WHERE sc.market_id = stg."market_id" 
        AND stg."market_updated_at" IS NOT NULL AND sc.update_dtm < stg."market_updated_at";
    $$);""")

    # 5b. station_ships
    sta_ship_select = f"""
        SELECT market_id, name, symbol, shipId, update_dtm FROM (
            SELECT 
                st.id AS market_id, 
                {_duckdb_case(ship_map, "sh.name")} AS name, 
                sh.symbol, (sh.shipId)::INTEGER AS shipId,
                TRY_CAST(st.shipyard.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, stations, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.stations) AS t(st), UNNEST(st.shipyard.ships) AS t3(sh) WHERE st.name IS NOT NULL AND st.shipyard IS NOT NULL
            UNION ALL
            SELECT 
                st.id AS market_id, 
                {_duckdb_case(ship_map, "sh.name")} AS name, 
                sh.symbol, (sh.shipId)::INTEGER AS shipId,
                TRY_CAST(st.shipyard.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.bodies) AS t(b), UNNEST(b.stations) AS t2(st), UNNEST(st.shipyard.ships) AS t3(sh) WHERE b.id64 IS NOT NULL AND b.stations IS NOT NULL AND st.name IS NOT NULL AND st.shipyard IS NOT NULL
        )
    """
    sta_ship_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id, shipId ORDER BY update_dtm DESC NULLS LAST) = 1"
    sta_ship_upsert = f"""
        INSERT INTO station_ships (market_id, name, symbol, shipId, update_dtm) 
        SELECT "market_id", "name", "symbol", "shipId", "update_dtm" FROM _stg_station_ships 
        ON CONFLICT (market_id, shipid) DO UPDATE SET 
            symbol=EXCLUDED.symbol, name=EXCLUDED.name, update_dtm=EXCLUDED.update_dtm
        {_where_dtm("station_ships")};
    """
    _execute_table("station_ships", "_inc_sta_ship", sta_ship_select, sta_ship_dedupe, sta_ship_upsert)
    conn.execute("""CALL postgres_execute('pg', $$
        DELETE FROM station_ships sc USING _stg_stations stg
        WHERE sc.market_id = stg."market_id" 
        AND stg."shipyard_updated_at" IS NOT NULL AND sc.update_dtm < stg."shipyard_updated_at";
    $$);""")

    # 5c. station_modules
    sta_mod_select = f"""
        SELECT market_id, name, symbol, moduleId, class, rating, category, update_dtm FROM (
            SELECT 
                st.id AS market_id, 
                {_duckdb_case(module_map, "m.name")} AS name, 
                m.symbol, (m.moduleId)::INTEGER AS moduleId, 
                (m.class)::INTEGER AS class, m.rating, 
                {_duckdb_case(module_category_map, "m.category")} AS category,
                TRY_CAST(st.outfitting.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, stations, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.stations) AS t(st), UNNEST(st.outfitting.modules) AS t3(m) WHERE st.name IS NOT NULL AND st.outfitting IS NOT NULL
            UNION ALL
            SELECT 
                st.id AS market_id, 
                {_duckdb_case(module_map, "m.name")} AS name, 
                m.symbol, (m.moduleId)::INTEGER AS moduleId, 
                (m.class)::INTEGER AS class, m.rating, 
                {_duckdb_case(module_category_map, "m.category")} AS category,
                TRY_CAST(st.outfitting.updateTime AS TIMESTAMP) AS update_dtm
            FROM (SELECT id64, bodies, _src_file FROM {read_expr} WHERE list_extract(string_split(_src_file, '/'), -1) IN {{sys_files_sql}}) s, 
            UNNEST(s.bodies) AS t(b), UNNEST(b.stations) AS t2(st), UNNEST(st.outfitting.modules) AS t3(m) WHERE b.id64 IS NOT NULL AND b.stations IS NOT NULL AND st.name IS NOT NULL AND st.outfitting IS NOT NULL
        )
    """
    sta_mod_dedupe = "QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id, moduleId ORDER BY update_dtm DESC NULLS LAST) = 1"
    sta_mod_upsert = f"""
        INSERT INTO station_modules (market_id, name, symbol, moduleId, class, rating, category, update_dtm) 
        SELECT "market_id", "name", "symbol", "moduleId", "class", "rating", "category", "update_dtm" FROM _stg_station_modules 
        ON CONFLICT (market_id, moduleid) DO UPDATE SET 
            symbol=EXCLUDED.symbol, name=EXCLUDED.name, class=EXCLUDED.class, 
            rating=EXCLUDED.rating, category=EXCLUDED.category, update_dtm=EXCLUDED.update_dtm
        {_where_dtm("station_modules")};
    """
    _execute_table("station_modules", "_inc_sta_mod", sta_mod_select, sta_mod_dedupe, sta_mod_upsert)
    conn.execute("""CALL postgres_execute('pg', $$
        DELETE FROM station_modules sc USING _stg_stations stg
        WHERE sc.market_id = stg."market_id" 
        AND stg."outfitting_updated_at" IS NOT NULL AND sc.update_dtm < stg."outfitting_updated_at";
    $$);""")

    conn.execute("CALL postgres_execute('pg', 'DROP TABLE IF EXISTS _stg_stations;');")
    conn.execute("DROP VIEW IF EXISTS batch_raw;")


class GalaxyIngestor:
    """Bootstraps the PostgreSQL galaxy database from Spansh NDJSON chunk files via DuckDB.

    DuckDB operates purely in-memory as a high-speed columnar JSON parser and pushes
    structured rows natively over libpq into PostgreSQL staging tables. Supports two
    ingestion strategies:

    - **upsert** (default): ``ON CONFLICT DO UPDATE`` with monotonic timestamp gating
      for zero-data-loss incremental loading.
    - **bulk**: Direct ``INSERT INTO`` for seeding completely empty databases from scratch.

    Provides crash-resumable per-table checkpointing, configurable parallelism,
    and optional post-ingest canonical normalization.
    """

    def __init__(
        self,
        json_path: str,
        pg_uri: str,
        max_memory: str = "16GB",
        temp_dir: str = "./.duckdb_temp",
        batch_size: int = 4,
        threads: int | None = None,
        ignore_errors: bool = False,
        mode: str = "upsert",
        limit: int | None = None,
        force: bool = False,
        normalize: bool = False,
        normalize_batch_size: int = 50000,
    ) -> None:
        """Initializes the GalaxyIngestor instance.

        Args:
            json_path: Path to NDJSON chunk file(s). Supports glob patterns (e.g. 'chunks/*.ndjson').
            pg_uri: PostgreSQL connection URI (e.g. 'postgresql://user:pass@localhost:5432/galaxy_sync').
            max_memory: Maximum RAM allocation for DuckDB streaming engine (default: '16GB').
            temp_dir: Directory for DuckDB disk spilling when memory is exceeded (default: './.duckdb_temp').
            batch_size: Number of chunk files to ingest concurrently per transaction batch (default: 4).
            threads: Number of CPU cores to allocate to DuckDB (default: all available cores).
            ignore_errors: If True, skip malformed or corrupted JSON records instead of aborting.
            mode: Ingestion strategy — 'bulk' for empty databases, 'upsert' for incremental (default: 'upsert').
            limit: Optional record limit per file for schema testing and validation.
            force: If True, bypasses ``_ingested_tables`` tracking and relaxes ``update_dtm`` checks.
            normalize: If True, invokes ``sp_normalize_galaxy_data`` after ingestion completes.
            normalize_batch_size: Row batch size for the post-ingest normalization procedure (default: 50000).
        """
        self.json_path = json_path
        self.pg_uri = pg_uri
        self.max_memory = max_memory
        self.temp_dir = temp_dir
        self.batch_size = batch_size
        self.threads = threads
        self.ignore_errors = ignore_errors
        self.mode = mode
        self.limit = limit
        self.force = force
        self.normalize = normalize
        self.normalize_batch_size = normalize_batch_size
        self.logger = logging.getLogger(__name__)

    def _on_pg_notice(self, notice: psycopg.errors.Diagnostic) -> None:
        """Callback to route PostgreSQL RAISE NOTICE outputs directly to logger."""
        notice_message = (notice.message_primary or str(notice)).strip()
        self.logger.info(f"   [Postgres] {notice_message}")

    def _run_normalization(self) -> None:
        """Executes the canonical normalization stored procedure (sp_normalize_galaxy_data)."""
        logger = self.logger
        logger.info("\n==================================================")
        logger.info("Starting Post-Ingest Canonical Data Normalization")
        logger.info(f"Procedure        : sp_normalize_galaxy_data({self.normalize_batch_size})")
        logger.info("==================================================")
        start_time = time.time()
        try:
            with psycopg.connect(self.pg_uri, autocommit=True) as pg_conn:
                pg_conn.add_notice_handler(self._on_pg_notice)
                with pg_conn.cursor() as cursor:
                    cursor.execute(f"CALL sp_normalize_galaxy_data({self.normalize_batch_size});")
            logger.info(f"✅ Canonical normalization completed successfully in {time.time() - start_time:.1f}s.")
        except Exception as error:
            logger.error(f"❌ Failed to run post-ingest normalization procedure: {error}")
            raise

    def run(self) -> None:
        """Executes the full ingestion pipeline.

        Discovers pending NDJSON files, attaches DuckDB to PostgreSQL, streams
        vectorized batch data through staging tables, commits upserts per domain
        table, and optionally triggers post-ingest normalization.

        Raises:
            SystemExit: On missing input files or unrecoverable database errors.
        """
        start_time = time.time()
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(line_buffering=True)

        logger = self.logger

        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

        target_path = Path(self.json_path)
        if any(char in self.json_path for char in ("*", "?", "[")):
            parent_dir = target_path.parent if str(target_path.parent) else Path()
            matched_files = sorted(str(matched_file) for matched_file in parent_dir.glob(target_path.name))
        elif target_path.exists():
            matched_files = [str(target_path)]
        else:
            matched_files = []

        if not matched_files:
            logger.error(f"Error: Target JSON file or pattern '{self.json_path}' not found.")
            sys.exit(1)

        active_threads = self.threads or os.cpu_count() or 4

        logger.info("==================================================")
        logger.info("Starting Galaxy Postgres Ingest Pipeline")
        logger.info(f"Input Files Count     : {len(matched_files)} chunk files")
        logger.info(f"Parallel Batch Size   : {self.batch_size} files per batch")
        logger.info("Target Database       : PostgreSQL via pg_duckdb")
        logger.info(f"Ingestion Mode        : {self.mode.upper()}")
        if self.force:
            logger.info("Force Overwrite       : ENABLED (ignoring timestamps & tracking)")
        logger.info(f"CPU Threads Allocated : {active_threads} / {os.cpu_count()} cores")
        logger.info(f"Memory Limit          : {self.max_memory}")
        logger.info(f"Temp Directory        : {self.temp_dir}")
        if self.limit:
            logger.info(f"Record Limit (test)   : {self.limit}")
        logger.info(
            f"Post-Load Normalize   : {'ENABLED (batch size ' + str(self.normalize_batch_size) + ')' if self.normalize else 'DISABLED'}"
        )
        logger.info("==================================================")

        # Ensure DuckDB temp spill directory exists
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

        # Initialize DuckDB purely in memory
        conn = duckdb.connect(":memory:")
        conn.execute(f"SET threads TO {active_threads};")
        conn.execute(f"SET max_memory = '{self.max_memory}';")
        conn.execute(f"SET temp_directory = '{self.temp_dir}';")
        conn.execute("SET preserve_insertion_order = false;")
        conn.execute("SET enable_progress_bar = true;")

        logger.info("Loading Postgres extension...")
        conn.execute("INSTALL postgres;")
        conn.execute("LOAD postgres;")

        logger.info("Attaching PostgreSQL server...")
        try:
            conn.execute(f"ATTACH '{self.pg_uri}' AS pg (TYPE postgres);")
            try:
                conn.execute("CALL postgres_execute('pg', 'SET duckdb.execution = false;');")
                logger.info("Disabled pg_duckdb query interception on remote PostgreSQL server.")
            except Exception as error:
                logger.warning(
                    f"Could not SET duckdb.execution = false on Postgres side (safe to ignore if extension is not installed): {error}"
                )
        except Exception as error:
            logger.error(f"Failed to attach PostgreSQL database: {error}")
            sys.exit(1)

        # Fetch completion state from PostgreSQL directly
        if self.force:
            logger.info("   ⚠️ Force mode enabled: bypassing _ingested_tables tracking and relaxing update_dtm timestamp checks.")
            completed_map = {}
        else:
            try:
                completed_tables = conn.execute(
                    "SELECT filename, list(table_name) FROM pg._ingested_tables GROUP BY filename;"
                ).fetchall()
                completed_map = {row[0]: set(row[1]) for row in completed_tables}
            except Exception as error:
                logger.warning(f"Could not read _ingested_tables tracking from PostgreSQL, assuming 0 files processed. ({error})")
                completed_map = {}

        all_tables = {
            "systems",
            "system_factions",
            "bodies",
            "body_rings",
            "body_belts",
            "body_signals",
            "stations",
            "station_commodities",
            "station_ships",
            "station_modules",
        }
        pending_files = []
        pending_table_map = {}

        for file_path in matched_files:
            basename = Path(file_path).name
            completed = completed_map.get(basename, set())
            missing = all_tables - completed
            if missing:
                pending_files.append(file_path)
                pending_table_map[basename] = missing

        if not pending_files:
            logger.info("\nAll target files have already been fully ingested. Nothing to do.")
        else:
            partially_completed = sum(
                1 for file_path in pending_files if len(pending_table_map[Path(file_path).name]) < len(all_tables)
            )
            completely_skipped = len(matched_files) - len(pending_files)
            if completely_skipped or partially_completed:
                logger.info(
                    f"\n[Resume] {completely_skipped} files fully ingested, {partially_completed} files partially ingested. Resuming {len(pending_files)} files..."
                )

            if self.limit:
                pending_files = pending_files[:1]

            file_batches = [
                pending_files[batch_start : batch_start + self.batch_size]
                for batch_start in range(0, len(pending_files), self.batch_size)
            ]

            logger.info(f"\n[1/1] Streaming {len(pending_files)} file(s) into PostgreSQL...")

            ignore_errors_str = "true" if self.ignore_errors else "false"

            for batch_index, current_batch in enumerate(file_batches, 1):
                batch_start_time = time.time()
                clean_batch_paths = [file_path.replace("\\", "/") for file_path in current_batch]
                batch_basenames = [Path(file_path).name for file_path in current_batch]
                batch_size_mb = sum(Path(file_path).stat().st_size for file_path in current_batch) / (1024**2)

                file_summary = f"{batch_basenames[0]} .. {batch_basenames[-1]}" if len(batch_basenames) > 1 else batch_basenames[0]
                logger.info(
                    f"   [Batch {batch_index}/{len(file_batches)}] {len(current_batch)} files ({file_summary} - {batch_size_mb:.1f} MB)..."
                )

                paths_sql_list = "[" + ", ".join([f"'{p.replace("'", "''")}'" for p in clean_batch_paths]) + "]"

                try:
                    _insert_batch(
                        conn,
                        paths_sql_list,
                        ignore_errors_str,
                        mode=self.mode,
                        pending_table_map={
                            Path(file_path).name: pending_table_map[Path(file_path).name] for file_path in current_batch
                        },
                        limit=self.limit,
                        force=self.force,
                    )
                except Exception as error:
                    logger.error(f"Batch failed: {error}")
                    sys.exit(1)

                logger.info(f"   ✓ Batch {batch_index} complete in {time.time() - batch_start_time:.1f}s.")

        conn.close()

        if self.normalize and (pending_files or self.force):
            self._run_normalization()

        logger.info(f"\nPipeline finished completely in {time.time() - start_time:.1f}s.")

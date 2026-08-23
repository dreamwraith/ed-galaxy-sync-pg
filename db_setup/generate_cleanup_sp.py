"""
DDL Generator for PostgreSQL Elite Dangerous Galaxy Sync Normalization Stored Procedure.
Reads canonical mappings from eddn/normalizations/*.yaml and generates
a high-performance, batched stored procedure in db_setup/05_procedures/sp_normalize_galaxy_data.sql.

Uses an in-database temporary lookup table (_norm_mappings) indexed on (category, raw_token)
to replace O(N*M) CASE WHEN string scans with microsecond O(1) Hash/Index Joins.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


# Enable standalone execution
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_mappings(config_dir: str | Path | None = None) -> dict[str, dict[str, list[str]]]:
    """Loads modular YAML normalization files and extracts raw variant mappings.

    Args:
        config_dir: Optional path to the normalizations directory containing YAML files.
            If None, candidate default directory paths are automatically probed.

    Returns:
        dict[str, dict[str, list[str]]]: Nested dictionary structured as
            {category: {canonical_name: [raw_variants]}}.
    """
    if config_dir is None:
        candidates = [
            Path("eddn/normalizations/direct"),
            Path(__file__).parent.parent / "eddn" / "normalizations" / "direct",
            Path(__file__).parent / "eddn" / "normalizations" / "direct",
            Path("eddn/normalizations"),
            Path(__file__).parent.parent / "eddn" / "normalizations",
        ]
        target_dir = None
        for candidate_path in candidates:
            if candidate_path.is_dir():
                target_dir = candidate_path
                break
        if target_dir is None:
            target_dir = Path("eddn/normalizations/direct")
    else:
        target_dir = Path(config_dir)
        if (target_dir / "direct").is_dir():
            target_dir = target_dir / "direct"

    mappings: dict[str, dict[str, list[str]]] = {}
    yaml_files = list(target_dir.glob("*.yaml")) + list(target_dir.glob("*.yml"))

    for yaml_file in yaml_files:
        category = yaml_file.stem
        if category == "scenarios":
            continue
        try:
            yaml_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}

            category_map: dict[str, list[str]] = {}
            for canonical_name, variants in yaml_data.items():
                canonical_name_str = str(canonical_name).strip()
                if isinstance(variants, list):
                    category_map[canonical_name_str] = [str(variant).strip() for variant in variants if variant is not None]
                elif isinstance(variants, str):
                    category_map[canonical_name_str] = [str(variants).strip()]
                else:
                    category_map[canonical_name_str] = [canonical_name_str]
            mappings[category] = category_map
        except Exception as error:
            print(f"Error loading '{yaml_file}': {error}", file=sys.stderr)

    return mappings


def load_scenarios(config_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Loads modular YAML scenarios mapping file.

    Args:
        config_dir: Optional path to the normalizations directory containing YAML files.

    Returns:
        dict[str, dict[str, Any]]: Dictionary mapping raw scenario token to dict of
            {name: str, signal_type: str, severity: str | None}.
    """
    if config_dir is None:
        candidates = [
            Path("eddn/normalizations/multifield"),
            Path(__file__).parent.parent / "eddn" / "normalizations" / "multifield",
            Path(__file__).parent / "eddn" / "normalizations" / "multifield",
            Path("eddn/normalizations"),
            Path(__file__).parent.parent / "eddn" / "normalizations",
        ]
        target_dir = None
        for candidate_path in candidates:
            if candidate_path.is_dir():
                target_dir = candidate_path
                break
        if target_dir is None:
            target_dir = Path("eddn/normalizations/multifield")
    else:
        target_dir = Path(config_dir)
        if (target_dir / "multifield").is_dir():
            target_dir = target_dir / "multifield"

    scenarios_file = target_dir / "scenarios.yaml"
    if not scenarios_file.is_file():
        scenarios_file = target_dir / "scenarios.yml"
    if not scenarios_file.is_file():
        return {}

    try:
        yaml_data = yaml.safe_load(scenarios_file.read_text(encoding="utf-8")) or {}
        return {str(token).strip(): scenario_data for token, scenario_data in yaml_data.items() if isinstance(scenario_data, dict)}
    except Exception as error:
        print(f"Error loading scenarios file: {error}", file=sys.stderr)
        return {}


def build_mapping_rows(
    mappings: dict[str, dict[str, list[str]]],
    scenarios: dict[str, dict[str, Any]],
) -> list[tuple[str, str, str, str | None, str | None]]:
    """Builds a list of (category, raw_token_lower, canonical_name, signal_type, severity) tuples.

    Deduplicates (category, raw_token) entries for fast temp table population.
    """
    rows: list[tuple[str, str, str, str | None, str | None]] = []
    seen: set[tuple[str, str]] = set()

    for category, category_map in mappings.items():
        cat_key = "sub_types" if category in ("planet_classes", "star_types") else category
        for canonical_name, variants in category_map.items():
            canonical_name_str = str(canonical_name).strip()
            for variant in variants:
                variant_str = str(variant).strip()
                variant_lower = variant_str.lower()
                key = (cat_key, variant_lower)
                if key not in seen and (variant_lower != canonical_name_str.lower() or variant_str.startswith("$")):
                    seen.add(key)
                    rows.append((cat_key, variant_lower, canonical_name_str, None, None))

    station_types = mappings.get("station_types", {})
    signal_types = mappings.get("signal_types", {})
    for canonical_name, variants_list in {**station_types, **signal_types}.items():
        canonical_name_str = str(canonical_name).strip()
        for variant in variants_list:
            variant_str = str(variant).strip()
            variant_lower = variant_str.lower()
            key = ("signal_types", variant_lower)
            if key not in seen and (variant_lower != canonical_name_str.lower() or variant_str.startswith("$")):
                seen.add(key)
                rows.append(("signal_types", variant_lower, canonical_name_str, None, None))

    for raw_token, scenario_item in scenarios.items():
        raw_token_str = str(raw_token).strip()
        display_name = scenario_item.get("name") or raw_token_str
        signal_type = scenario_item.get("signal_type")
        canonical_signal_type = signal_type
        if signal_type:
            for canonical_name, variants_list in {**station_types, **signal_types}.items():
                if (
                    signal_type.lower() in [variant.lower() for variant in variants_list]
                    or signal_type.lower() == canonical_name.lower()
                ):
                    canonical_signal_type = canonical_name
                    break
        severity = scenario_item.get("severity")

        sanitized_token = str(raw_token_str).lstrip("$").rstrip(";").strip()
        token_variants = {
            raw_token_str.lower(),
            f"${raw_token_str.lower()};",
            sanitized_token.lower(),
            f"${sanitized_token.lower()};",
        }

        for variant_str in token_variants:
            key = ("scenarios", variant_str)
            if key not in seen:
                seen.add(key)
                rows.append(("scenarios", variant_str, display_name, canonical_signal_type, severity))

    return rows


def format_insert_statements(rows: list[tuple[str, str, str, str | None, str | None]]) -> str:
    """Formats mapping tuples into batched multi-row INSERT statements."""
    statements = []
    chunk_size = 1000
    for chunk_index in range(0, len(rows), chunk_size):
        chunk = rows[chunk_index : chunk_index + chunk_size]
        value_strings = []
        for category_name, raw_token, canonical_name, signal_type, severity in chunk:
            escaped_category = category_name.replace("'", "''")
            escaped_raw_token = raw_token.replace("'", "''")
            escaped_canonical_name = canonical_name.replace("'", "''")
            escaped_signal_type = f"'{signal_type.replace("'", "''")}'" if signal_type else "NULL"
            escaped_severity = f"'{severity.replace("'", "''")}'" if severity else "NULL"
            value_strings.append(
                f"('{escaped_category}', '{escaped_raw_token}', '{escaped_canonical_name}', {escaped_signal_type}, {escaped_severity})"
            )
        values_sql = ",\n    ".join(value_strings)
        statement = f"""    INSERT INTO _norm_mappings (category, raw_token, canonical_name, signal_type, severity)
    VALUES
    {values_sql}
    ON CONFLICT (category, raw_token) DO NOTHING;"""
        statements.append(statement)
    return "\n\n".join(statements)


def generate_sql(config_dir: str | Path | None = None) -> str:
    """Generates the full procedural PL/pgSQL stored procedure for sp_normalize_galaxy_data.

    Args:
        config_dir: Optional path to directory with YAML normalizations.

    Returns:
        str: Complete DDL definition of the stored procedure.
    """
    mappings = load_mappings(config_dir)
    scenarios = load_scenarios(config_dir)

    rows = build_mapping_rows(mappings, scenarios)
    inserts_sql = format_insert_statements(rows)

    return f"""-- ==============================================================================
-- ELITE DANGEROUS GALAXY SYNC (POSTGRESQL) - CANONICAL DATA NORMALIZATION
-- Generated automatically from eddn/normalizations/*.yaml
-- Uses an in-database temporary lookup table (_norm_mappings) for O(1) Hash/Index Joins
-- ==============================================================================

CREATE OR REPLACE PROCEDURE sp_normalize_galaxy_data(batch_size INT DEFAULT 50000)
LANGUAGE plpgsql
AS $$
DECLARE
    rows_affected BIGINT;
    step_total BIGINT;
    grand_total BIGINT := 0;
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Starting Galaxy Data Normalization Cleanup Procedure';
    RAISE NOTICE 'Batch Size: %', batch_size;
    RAISE NOTICE '==================================================';

    -- --------------------------------------------------------------------------
    -- 0. Initialize Temporary Normalization Mapping Lookup Table
    -- --------------------------------------------------------------------------
    CREATE TEMP TABLE IF NOT EXISTS _norm_mappings (
        category TEXT NOT NULL,
        raw_token TEXT NOT NULL,
        canonical_name TEXT NOT NULL,
        signal_type TEXT,
        severity TEXT,
        PRIMARY KEY (category, raw_token)
    ) ON COMMIT PRESERVE ROWS;

    TRUNCATE TABLE _norm_mappings;

{inserts_sql}

    CREATE INDEX IF NOT EXISTS idx_stg_norm_mappings ON _norm_mappings (category, raw_token);
    ANALYZE _norm_mappings;

    -- --------------------------------------------------------------------------
    -- 1. Normalize body_rings.type
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[1/14] Normalizing body_rings.type...';
    LOOP
        WITH cte AS (
            SELECT s.ctid, m.canonical_name
            FROM body_rings s
            JOIN _norm_mappings m ON m.category = 'ring_types' AND m.raw_token = LOWER(TRIM(s.type))
            WHERE s.type IS DISTINCT FROM m.canonical_name
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE body_rings s
        SET type = cte.canonical_name
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed body_rings: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 2. Normalize body_belts.type
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[2/14] Normalizing body_belts.type...';
    LOOP
        WITH cte AS (
            SELECT s.ctid, m.canonical_name
            FROM body_belts s
            JOIN _norm_mappings m ON m.category = 'ring_types' AND m.raw_token = LOWER(TRIM(s.type))
            WHERE s.type IS DISTINCT FROM m.canonical_name
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE body_belts s
        SET type = cte.canonical_name
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed body_belts: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 3. Normalize stations.type (Fleet Carrier, Starports, Outposts, etc.)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[3/14] Normalizing stations.type...';
    LOOP
        WITH cte AS (
            SELECT s.ctid, m.canonical_name
            FROM stations s
            JOIN _norm_mappings m ON m.category = 'station_types' AND m.raw_token = LOWER(TRIM(s.type))
            WHERE s.type IS DISTINCT FROM m.canonical_name
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE stations s
        SET type = cte.canonical_name
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed stations.type: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 4. Normalize stations attributes (economies, government, allegiance, states, docking)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[4/14] Normalizing stations attributes...';
    LOOP
        WITH cte AS (
            SELECT s.ctid,
                   m1.canonical_name AS new_pri_econ,
                   m2.canonical_name AS new_sec_econ,
                   m3.canonical_name AS new_gov,
                   m4.canonical_name AS new_all,
                   m5.canonical_name AS new_state,
                   m6.canonical_name AS new_fac_state,
                   m7.canonical_name AS new_dock
            FROM stations s
            LEFT JOIN _norm_mappings m1 ON m1.category = 'economies' AND m1.raw_token = LOWER(TRIM(s.primaryeconomy)) AND s.primaryeconomy IS DISTINCT FROM m1.canonical_name
            LEFT JOIN _norm_mappings m2 ON m2.category = 'economies' AND m2.raw_token = LOWER(TRIM(s.secondaryeconomy)) AND s.secondaryeconomy IS DISTINCT FROM m2.canonical_name
            LEFT JOIN _norm_mappings m3 ON m3.category = 'governments' AND m3.raw_token = LOWER(TRIM(s.government)) AND s.government IS DISTINCT FROM m3.canonical_name
            LEFT JOIN _norm_mappings m4 ON m4.category = 'allegiances' AND m4.raw_token = LOWER(TRIM(s.allegiance)) AND s.allegiance IS DISTINCT FROM m4.canonical_name
            LEFT JOIN _norm_mappings m5 ON m5.category = 'faction_states' AND m5.raw_token = LOWER(TRIM(s.state)) AND s.state IS DISTINCT FROM m5.canonical_name
            LEFT JOIN _norm_mappings m6 ON m6.category = 'faction_states' AND m6.raw_token = LOWER(TRIM(s.controllingfactionstate)) AND s.controllingfactionstate IS DISTINCT FROM m6.canonical_name
            LEFT JOIN _norm_mappings m7 ON m7.category = 'carrier_docking_access' AND m7.raw_token = LOWER(TRIM(s.carrierdockingaccess)) AND s.carrierdockingaccess IS DISTINCT FROM m7.canonical_name
            WHERE m1.canonical_name IS NOT NULL
               OR m2.canonical_name IS NOT NULL
               OR m3.canonical_name IS NOT NULL
               OR m4.canonical_name IS NOT NULL
               OR m5.canonical_name IS NOT NULL
               OR m6.canonical_name IS NOT NULL
               OR m7.canonical_name IS NOT NULL
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE stations s
        SET primaryeconomy          = COALESCE(cte.new_pri_econ, s.primaryeconomy),
            secondaryeconomy        = COALESCE(cte.new_sec_econ, s.secondaryeconomy),
            government              = COALESCE(cte.new_gov, s.government),
            allegiance              = COALESCE(cte.new_all, s.allegiance),
            state                   = COALESCE(cte.new_state, s.state),
            controllingfactionstate = COALESCE(cte.new_fac_state, s.controllingfactionstate),
            carrierdockingaccess    = COALESCE(cte.new_dock, s.carrierdockingaccess)
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed stations attributes: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 5. Normalize systems attributes (economies, security, government, allegiance)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[5/14] Normalizing systems attributes...';
    LOOP
        WITH cte AS (
            SELECT s.ctid,
                   m1.canonical_name AS new_pri_econ,
                   m2.canonical_name AS new_sec_econ,
                   m3.canonical_name AS new_sec,
                   m4.canonical_name AS new_gov,
                   m5.canonical_name AS new_all
            FROM systems s
            LEFT JOIN _norm_mappings m1 ON m1.category = 'economies' AND m1.raw_token = LOWER(TRIM(s.primaryeconomy)) AND s.primaryeconomy IS DISTINCT FROM m1.canonical_name
            LEFT JOIN _norm_mappings m2 ON m2.category = 'economies' AND m2.raw_token = LOWER(TRIM(s.secondaryeconomy)) AND s.secondaryeconomy IS DISTINCT FROM m2.canonical_name
            LEFT JOIN _norm_mappings m3 ON m3.category = 'securities' AND m3.raw_token = LOWER(TRIM(s.security)) AND s.security IS DISTINCT FROM m3.canonical_name
            LEFT JOIN _norm_mappings m4 ON m4.category = 'governments' AND m4.raw_token = LOWER(TRIM(s.government)) AND s.government IS DISTINCT FROM m4.canonical_name
            LEFT JOIN _norm_mappings m5 ON m5.category = 'allegiances' AND m5.raw_token = LOWER(TRIM(s.allegiance)) AND s.allegiance IS DISTINCT FROM m5.canonical_name
            WHERE m1.canonical_name IS NOT NULL
               OR m2.canonical_name IS NOT NULL
               OR m3.canonical_name IS NOT NULL
               OR m4.canonical_name IS NOT NULL
               OR m5.canonical_name IS NOT NULL
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE systems s
        SET primaryeconomy   = COALESCE(cte.new_pri_econ, s.primaryeconomy),
            secondaryeconomy = COALESCE(cte.new_sec_econ, s.secondaryeconomy),
            security         = COALESCE(cte.new_sec, s.security),
            government       = COALESCE(cte.new_gov, s.government),
            allegiance       = COALESCE(cte.new_all, s.allegiance)
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed systems attributes: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 6. Normalize system_factions (government, allegiance, state)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[6/14] Normalizing system_factions...';
    LOOP
        WITH cte AS (
            SELECT s.ctid,
                   m1.canonical_name AS new_gov,
                   m2.canonical_name AS new_all,
                   m3.canonical_name AS new_state
            FROM system_factions s
            LEFT JOIN _norm_mappings m1 ON m1.category = 'governments' AND m1.raw_token = LOWER(TRIM(s.government)) AND s.government IS DISTINCT FROM m1.canonical_name
            LEFT JOIN _norm_mappings m2 ON m2.category = 'allegiances' AND m2.raw_token = LOWER(TRIM(s.allegiance)) AND s.allegiance IS DISTINCT FROM m2.canonical_name
            LEFT JOIN _norm_mappings m3 ON m3.category = 'faction_states' AND m3.raw_token = LOWER(TRIM(s.state)) AND s.state IS DISTINCT FROM m3.canonical_name
            WHERE m1.canonical_name IS NOT NULL
               OR m2.canonical_name IS NOT NULL
               OR m3.canonical_name IS NOT NULL
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE system_factions s
        SET government = COALESCE(cte.new_gov, s.government),
            allegiance = COALESCE(cte.new_all, s.allegiance),
            state      = COALESCE(cte.new_state, s.state)
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed system_factions: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 7. Normalize bodies attributes (reservelevel, terraformingstate, subtype)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[7/14] Normalizing bodies attributes...';
    LOOP
        WITH cte AS (
            SELECT s.ctid,
                   m1.canonical_name AS new_reserve,
                   m2.canonical_name AS new_tf,
                   m3.canonical_name AS new_sub
            FROM bodies s
            LEFT JOIN _norm_mappings m1 ON m1.category = 'reserve_levels' AND m1.raw_token = LOWER(TRIM(s.reservelevel)) AND s.reservelevel IS DISTINCT FROM m1.canonical_name
            LEFT JOIN _norm_mappings m2 ON m2.category = 'terraform_states' AND m2.raw_token = LOWER(TRIM(s.terraformingstate)) AND s.terraformingstate IS DISTINCT FROM m2.canonical_name
            LEFT JOIN _norm_mappings m3 ON m3.category = 'sub_types' AND m3.raw_token = LOWER(TRIM(s.subtype)) AND s.subtype IS DISTINCT FROM m3.canonical_name
            WHERE m1.canonical_name IS NOT NULL
               OR m2.canonical_name IS NOT NULL
               OR m3.canonical_name IS NOT NULL
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE bodies s
        SET reservelevel      = COALESCE(cte.new_reserve, s.reservelevel),
            terraformingstate = COALESCE(cte.new_tf, s.terraformingstate),
            subtype           = COALESCE(cte.new_sub, s.subtype)
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed bodies attributes: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 8. Normalize station_ships.name
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[8/14] Normalizing station_ships.name...';
    LOOP
        WITH cte AS (
            SELECT s.ctid, m.canonical_name
            FROM station_ships s
            JOIN _norm_mappings m ON m.category = 'ships' AND m.raw_token = LOWER(TRIM(s.name))
            WHERE s.name IS DISTINCT FROM m.canonical_name
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE station_ships s
        SET name = cte.canonical_name
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed station_ships: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 9. Normalize station_commodities (name, category)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[9/14] Normalizing station_commodities...';
    LOOP
        WITH cte AS (
            SELECT s.ctid,
                   m1.canonical_name AS new_name,
                   m2.canonical_name AS new_cat
            FROM station_commodities s
            LEFT JOIN _norm_mappings m1 ON m1.category = 'commodities' AND m1.raw_token = LOWER(TRIM(s.name)) AND s.name IS DISTINCT FROM m1.canonical_name
            LEFT JOIN _norm_mappings m2 ON m2.category = 'commodity_categories' AND m2.raw_token = LOWER(TRIM(s.category)) AND s.category IS DISTINCT FROM m2.canonical_name
            WHERE m1.canonical_name IS NOT NULL
               OR m2.canonical_name IS NOT NULL
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE station_commodities s
        SET name     = COALESCE(cte.new_name, s.name),
            category = COALESCE(cte.new_cat, s.category)
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed station_commodities: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 10. Normalize station_modules (name, category)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[10/14] Normalizing station_modules...';
    LOOP
        WITH cte AS (
            SELECT s.ctid,
                   m1.canonical_name AS new_name,
                   m2.canonical_name AS new_cat
            FROM station_modules s
            LEFT JOIN _norm_mappings m1 ON m1.category = 'modules' AND m1.raw_token = LOWER(TRIM(s.name)) AND s.name IS DISTINCT FROM m1.canonical_name
            LEFT JOIN _norm_mappings m2 ON m2.category = 'module_categories' AND m2.raw_token = LOWER(TRIM(s.category)) AND s.category IS DISTINCT FROM m2.canonical_name
            WHERE m1.canonical_name IS NOT NULL
               OR m2.canonical_name IS NOT NULL
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE station_modules s
        SET name     = COALESCE(cte.new_name, s.name),
            category = COALESCE(cte.new_cat, s.category)
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed station_modules: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 11. Normalize station_materials.name
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[11/14] Normalizing station_materials.name...';
    LOOP
        WITH cte AS (
            SELECT s.ctid, m.canonical_name
            FROM station_materials s
            JOIN _norm_mappings m ON m.category = 'materials' AND m.raw_token = LOWER(TRIM(s.name))
            WHERE s.name IS DISTINCT FROM m.canonical_name
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE station_materials s
        SET name = cte.canonical_name
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed station_materials: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 12. Normalize system_signals (name, signal_type, severity, spawning_state)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[12/14] Normalizing system_signals...';
    LOOP
        WITH cte AS (
            SELECT s.ctid,
                   COALESCE(ms.canonical_name, s.name) AS new_name,
                   COALESCE(ms.signal_type, mt.canonical_name, s.signal_type) AS new_signal_type,
                   COALESCE(ms.severity, s.severity) AS new_severity,
                   COALESCE(mf.canonical_name, s.spawning_state) AS new_spawning_state
            FROM system_signals s
            LEFT JOIN _norm_mappings ms ON ms.category = 'scenarios' AND ms.raw_token = LOWER(TRIM(s.raw_name))
            LEFT JOIN _norm_mappings mt ON mt.category = 'signal_types' AND mt.raw_token = LOWER(TRIM(s.signal_type)) AND s.signal_type IS DISTINCT FROM mt.canonical_name
            LEFT JOIN _norm_mappings mf ON mf.category = 'faction_states' AND mf.raw_token = LOWER(TRIM(s.spawning_state)) AND s.spawning_state IS DISTINCT FROM mf.canonical_name
            WHERE (ms.canonical_name IS NOT NULL AND ms.canonical_name IS DISTINCT FROM s.name)
               OR (ms.signal_type IS NOT NULL AND ms.signal_type IS DISTINCT FROM s.signal_type)
               OR (mt.canonical_name IS NOT NULL AND mt.canonical_name IS DISTINCT FROM s.signal_type)
               OR (ms.severity IS NOT NULL AND ms.severity IS DISTINCT FROM s.severity)
               OR (mf.canonical_name IS NOT NULL AND mf.canonical_name IS DISTINCT FROM s.spawning_state)
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE system_signals s
        SET name           = cte.new_name,
            signal_type    = cte.new_signal_type,
            severity       = cte.new_severity,
            spawning_state = cte.new_spawning_state
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed system_signals: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 13. Normalize body_pois.poi_type
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[13/14] Normalizing body_pois.poi_type...';
    LOOP
        WITH cte AS (
            SELECT s.ctid, m.canonical_name
            FROM body_pois s
            JOIN _norm_mappings m ON m.category = 'poi_types' AND m.raw_token = LOWER(TRIM(s.poi_type))
            WHERE s.poi_type IS DISTINCT FROM m.canonical_name
            LIMIT batch_size
            FOR UPDATE OF s
        )
        UPDATE body_pois s
        SET poi_type = cte.canonical_name
        FROM cte
        WHERE s.ctid = cte.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed body_pois: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 14. Normalize body_signals.genuses (array column)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[14/14] Normalizing body_signals.genuses...';
    LOOP
        WITH changed_bodies AS (
            SELECT s.ctid
            FROM body_signals s
            WHERE EXISTS (
                SELECT 1 FROM unnest(s.genuses) AS g
                JOIN _norm_mappings m ON m.category = 'genuses' AND m.raw_token = LOWER(TRIM(g))
                WHERE m.canonical_name IS DISTINCT FROM g
            )
            LIMIT batch_size
            FOR UPDATE OF s
        ),
        sub AS (
            SELECT s.ctid,
                   array_agg(COALESCE(m.canonical_name, g) ORDER BY ord) AS new_genuses
            FROM body_signals s
            JOIN changed_bodies cb ON cb.ctid = s.ctid,
                 LATERAL unnest(s.genuses) WITH ORDINALITY AS t(g, ord)
            LEFT JOIN _norm_mappings m ON m.category = 'genuses' AND m.raw_token = LOWER(TRIM(g))
            GROUP BY s.ctid
        )
        UPDATE body_signals s
        SET genuses = sub.new_genuses
        FROM sub
        WHERE s.ctid = sub.ctid;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   Completed body_signals: % rows updated.', step_total;
    grand_total := grand_total + step_total;

    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Galaxy Normalization Completed! Total Rows Updated: %', grand_total;
    RAISE NOTICE '==================================================';
END;
$$;

-- ------------------------------------------------------------------------------
-- Procedure Security Grants
-- ------------------------------------------------------------------------------
REVOKE EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) FROM PUBLIC;
REVOKE EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) FROM galaxy_searcher;
GRANT EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) TO galaxy_updater;
"""


def main() -> None:
    """CLI entry point to generate sp_normalize_galaxy_data.sql."""
    parser = argparse.ArgumentParser(description="Generate sp_normalize_galaxy_data.sql DDL from YAML normalizations.")
    parser.add_argument("--config-dir", default=None, help="Directory containing normalizations YAML files")
    parser.add_argument(
        "--output",
        default=r"db_setup/05_procedures/sp_normalize_galaxy_data.sql",
        help="Target SQL output file path",
    )
    arguments = parser.parse_args()

    sql_content = generate_sql(arguments.config_dir)
    output_path = Path(arguments.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(sql_content, encoding="utf-8")
    print(f"[SUCCESS] Generated stored procedure DDL in '{output_path}' ({len(sql_content):,} bytes)")


if __name__ == "__main__":
    main()

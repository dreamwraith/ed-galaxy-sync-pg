"""
DDL Generator for PostgreSQL EDDN Dead-Letter Queue (DLQ) Backfill Stored Procedure.
Reads approved senders from config.yaml and normalization rules from eddn/normalizations/*.yaml
to generate a batched, production-ready stored procedure in db_setup/05_procedures/sp_process_eddn_dlq.sql.

Uses the shared _norm_mappings temporary table model for high-speed O(1) Hash/Index Joins.
"""

import argparse
import sys
from pathlib import Path

import yaml


# Enable standalone execution
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_setup.generate_cleanup_sp import (
    build_mapping_rows,
    format_insert_statements,
    load_mappings,
    load_scenarios,
)


def load_approved_senders(config_path: Path | None = None) -> list[str]:
    """Loads approved software senders from config.yaml for DLQ backfill filtering."""
    if config_path is None:
        candidates = [
            Path("config.yaml"),
            Path(__file__).parent.parent / "config.yaml",
            Path(__file__).parent / "config.yaml",
        ]
        target_config_path = None
        for candidate_path in candidates:
            if candidate_path.is_file():
                target_config_path = candidate_path
                break
        if target_config_path is None:
            target_config_path = Path("config.yaml")
    else:
        target_config_path = Path(config_path)

    if not target_config_path.is_file():
        return [
            "E:D Market Connector [Windows]",
            "E:D Market Connector [Linux]",
            "E:D Market Connector [Mac]",
            "EDMarketConnector",
            "EDDiscovery",
            "EDDI",
            "EDDLite",
            "JournalX",
            "ED-Astro",
            "ED-Astro.com Fleet Activity",
            "ED-Astro.com System Map",
            "EDOMaterialsHelper",
            "Elite Observatory",
            "ObservatoryCore",
            "Icarus Terminal",
            "GameGlass",
            "Spansh Router",
            "Spansh",
        ]

    try:
        yaml_data = yaml.safe_load(target_config_path.read_text(encoding="utf-8")) or {}
        senders = yaml_data.get("allowed_senders", [])
        result = []
        for sender in senders:
            if isinstance(sender, dict):
                name = sender.get("name", "").strip()
                if name:
                    result.append(name)
            elif isinstance(sender, str) and sender.strip():
                result.append(sender.strip())
        return result
    except Exception as error:
        print(f"Warning: Could not read allowed_senders from {target_config_path}: {error}", file=sys.stderr)
        return []


def generate_dlq_sp_sql(
    config_file: str | Path | None = None,
    normalizations_dir: str | Path | None = None,
) -> str:
    """Generates the procedural PL/pgSQL stored procedure DDL for sp_process_eddn_dlq."""
    senders = load_approved_senders(Path(config_file) if config_file else None)
    mappings = load_mappings(normalizations_dir)
    scenarios = load_scenarios(normalizations_dir)

    rows = build_mapping_rows(mappings, scenarios)
    inserts_sql = format_insert_statements(rows)

    senders_sql_values = ",\n    ".join([f"('{sender_name.replace("'", "''")}')" for sender_name in senders])

    def make_norm_lookup(category_name: str, column_reference: str, fallback_column: str | None = None) -> str:
        fallback = fallback_column or column_reference
        return f"COALESCE((SELECT m.canonical_name FROM _norm_mappings m WHERE m.category = '{category_name}' AND m.raw_token = LOWER(TRIM({column_reference}))), {fallback})"

    station_type_expr = make_norm_lookup("station_types", "c.raw_message->>'StationType'")
    sys_econ_pri_expr = make_norm_lookup("economies", "c.raw_message->>'SystemEconomy'")
    sys_econ_sec_expr = make_norm_lookup("economies", "c.raw_message->>'SystemSecondEconomy'")
    sys_gov_expr = make_norm_lookup("governments", "c.raw_message->>'SystemGovernment'")
    sys_all_expr = make_norm_lookup("allegiances", "c.raw_message->>'SystemAllegiance'")
    sys_sec_expr = make_norm_lookup("securities", "c.raw_message->>'SystemSecurity'")

    sta_econ_pri_expr = make_norm_lookup("economies", "c.raw_message->>'StationEconomy'")
    sta_gov_expr = make_norm_lookup("governments", "c.raw_message->>'StationGovernment'")
    sta_all_expr = make_norm_lookup("allegiances", "c.raw_message->>'StationAllegiance'")
    sta_state_expr = make_norm_lookup(
        "faction_states", "COALESCE(c.raw_message->>'StationState', c.raw_message->'StationFaction'->>'FactionState')"
    )
    sta_fac_state_expr = make_norm_lookup("faction_states", "c.raw_message->'StationFaction'->>'FactionState'")
    sta_dock_expr = make_norm_lookup(
        "carrier_docking_access", "COALESCE(c.raw_message->>'CarrierDockingAccess', c.raw_message->>'DockingAccess')"
    )

    fac_gov_expr = make_norm_lookup("governments", "fac->>'Government'")
    fac_all_expr = make_norm_lookup("allegiances", "fac->>'Allegiance'")
    fac_state_expr = make_norm_lookup("faction_states", "fac->>'FactionState'")

    body_tf_expr = make_norm_lookup("terraform_states", "c.raw_message->>'TerraformState'")
    body_reserve_expr = make_norm_lookup("reserve_levels", "c.raw_message->>'ReserveLevel'")
    body_sub_expr = make_norm_lookup("sub_types", "COALESCE(c.raw_message->>'StarType', c.raw_message->>'PlanetClass')")

    sig_state_expr = make_norm_lookup("faction_states", "sig->>'SpawningState'")

    ship_name_expr = make_norm_lookup("ships", "item->>'name'")
    comm_name_expr = make_norm_lookup("commodities", "item->>'name'")
    material_name_expr = make_norm_lookup("materials", "COALESCE(item->>'Name', item->>'name')")
    comm_cat_expr = make_norm_lookup("commodity_categories", "item->>'category'")
    mod_cat_expr = make_norm_lookup("module_categories", "COALESCE(item->>'category', 'standard')")
    poi_type_expr = make_norm_lookup(
        "poi_types",
        "COALESCE(c.raw_message->>'Name', c.raw_message->>'SubCategory_Localised', c.raw_message->>'SubCategory', c.raw_message->>'Category_Localised', c.raw_message->>'Category')",
        fallback_column="'Settlement'",
    )

    return f"""-- ==============================================================================
-- sp_process_eddn_dlq.sql: Stored Procedure for EDDN DLQ Draining, Backfilling & Remediation
-- Generated automatically from config.yaml and eddn/normalizations/*.yaml
-- Uses shared _norm_mappings temporary table model for high-speed O(1) Hash/Index Joins
-- ==============================================================================

CREATE OR REPLACE PROCEDURE sp_process_eddn_dlq(
    batch_size INT DEFAULT 5000,
    force_sender TEXT DEFAULT NULL,
    purge_noise BOOLEAN DEFAULT FALSE,
    run_normalizations BOOLEAN DEFAULT TRUE
)
LANGUAGE plpgsql
AS $$
DECLARE
    purged_count BIGINT := 0;
    rows_affected BIGINT := 0;
    step_total BIGINT := 0;
    grand_total BIGINT := 0;
BEGIN
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Starting EDDN Dead-Letter Queue (DLQ) Processing';
    RAISE NOTICE 'Batch Size          : %', batch_size;
    RAISE NOTICE 'Force Sender        : %', COALESCE(force_sender, '<None>');
    RAISE NOTICE 'Purge Noise         : %', purge_noise;
    RAISE NOTICE 'Run Normalizations  : %', run_normalizations;
    RAISE NOTICE '==================================================';

    -- --------------------------------------------------------------------------
    -- 0. Temporary Tables (_approved_senders & _norm_mappings)
    -- --------------------------------------------------------------------------
    CREATE TEMP TABLE IF NOT EXISTS _approved_senders (
        sender_name TEXT PRIMARY KEY
    ) ON COMMIT PRESERVE ROWS;

    TRUNCATE _approved_senders;

    INSERT INTO _approved_senders (sender_name) VALUES
    {senders_sql_values}
    ON CONFLICT (sender_name) DO NOTHING;

    IF force_sender IS NOT NULL AND TRIM(force_sender) != '' THEN
        INSERT INTO _approved_senders (sender_name) VALUES (TRIM(force_sender))
        ON CONFLICT (sender_name) DO NOTHING;
        RAISE NOTICE '   ✓ Force-included sender: %', TRIM(force_sender);
    END IF;

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
    -- 1. Purge Ephemeral Noise & Legacy Versions (Optional)
    -- --------------------------------------------------------------------------
    IF purge_noise THEN
        RAISE NOTICE '[1/12] Purging ephemeral noise and legacy game version events...';
        
        WITH purged AS (
            DELETE FROM eddn_unhandled_events
            WHERE schema_ref ILIKE ANY (ARRAY[
                '%/test%',
                '%navroute%',
                '%dockinggranted%',
                '%dockingdenied%',
                '%fssallbodiesfound%',
                '%navbeaconscan%',
                '%scanbarycentre%'
            ])
            OR event_name ILIKE ANY (ARRAY[
                'NavRoute',
                'DockingGranted',
                'DockingDenied',
                'FSSAllBodiesFound',
                'NavBeaconScan',
                'ScanBaryCentre'
            ])
            OR (raw_message->'header'->>'gameversion') ILIKE ANY (ARRAY[
                '3.%',
                '2.%',
                '1.%'
            ])
            OR (
                (schema_ref ILIKE '%codexentry%' OR event_name = 'CodexEntry')
                AND (
                    raw_message->>'Category' IN ('$Codex_Category_Civilisations;', '$Codex_Category_StellarBodies;')
                    OR raw_message->>'SubCategory' IN ('$Codex_SubCategory_Guardian;', '$Codex_SubCategory_Thargoid;', '$Codex_SubCategory_Geology_and_Anomalies;', '$Codex_SubCategory_Terrestrial_Planets;', '$Codex_SubCategory_Gas_Giants;')
                )
            )
            RETURNING id
        )
        SELECT COUNT(*) INTO purged_count FROM purged;
        RAISE NOTICE '   ✓ Purged % ephemeral / legacy DLQ events.', purged_count;
    END IF;

    -- --------------------------------------------------------------------------
    -- 2. Process Systems & Factions (FSDJump & Location Events)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[2/12] Backfilling systems & factions from FSDJump / Location events...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name IN ('FSDJump', 'Location')
                OR e.raw_message->>'event' IN ('FSDJump', 'Location')
                OR e.schema_ref ILIKE '%journal/1%' AND e.raw_message->>'event' IN ('FSDJump', 'Location')
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_sys AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' THEN (c.raw_message->>'SystemAddress')::BIGINT ELSE NULL END AS id64,
                c.raw_message->>'StarSystem' AS name,
                CASE 
                    WHEN c.raw_message->'StarPos' IS NOT NULL AND jsonb_array_length(c.raw_message->'StarPos') = 3 
                    THEN '(' || (c.raw_message->'StarPos'->0) || ', ' || (c.raw_message->'StarPos'->1) || ', ' || (c.raw_message->'StarPos'->2) || ')'
                    ELSE NULL 
                END AS coords,
                {sys_all_expr} AS allegiance,
                {sys_gov_expr} AS government,
                {sys_econ_pri_expr} AS primaryeconomy,
                {sys_econ_sec_expr} AS secondaryeconomy,
                {sys_sec_expr} AS security,
                CASE WHEN c.raw_message->>'Population' ~ '^[0-9]+$' THEN (c.raw_message->>'Population')::BIGINT ELSE NULL END AS population,
                c.raw_message->>'ControllingPower' AS controllingpower,
                c.raw_message->>'PowerplayState' AS powerstate,
                c.raw_message->'Powers' AS powers,
                c.raw_message->'SystemFaction' AS controllingfaction,
                c.raw_message->'Factions' AS factions,
                CASE 
                    WHEN (c.raw_message->>'timestamp') IS NOT NULL AND (c.raw_message->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c
        ),
        ins_sys AS (
            INSERT INTO systems (
                id64, name, coords, allegiance, government, primaryeconomy, secondaryeconomy,
                security, population, controllingpower, powerstate, powers, controllingfaction, update_dtm
            )
            SELECT 
                p.id64, p.name, p.coords, p.allegiance, p.government, p.primaryeconomy, p.secondaryeconomy,
                p.security, p.population, p.controllingpower, p.powerstate, p.powers, p.controllingfaction, p.msg_dtm
            FROM parsed_sys p
            WHERE p.id64 IS NOT NULL
            ON CONFLICT (id64) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, systems.name),
                coords = COALESCE(EXCLUDED.coords, systems.coords),
                allegiance = COALESCE(EXCLUDED.allegiance, systems.allegiance),
                government = COALESCE(EXCLUDED.government, systems.government),
                primaryeconomy = COALESCE(EXCLUDED.primaryeconomy, systems.primaryeconomy),
                secondaryeconomy = COALESCE(EXCLUDED.secondaryeconomy, systems.secondaryeconomy),
                security = COALESCE(EXCLUDED.security, systems.security),
                population = COALESCE(EXCLUDED.population, systems.population),
                controllingpower = COALESCE(EXCLUDED.controllingpower, systems.controllingpower),
                powerstate = COALESCE(EXCLUDED.powerstate, systems.powerstate),
                powers = COALESCE(EXCLUDED.powers, systems.powers),
                controllingfaction = COALESCE(EXCLUDED.controllingfaction, systems.controllingfaction),
                update_dtm = GREATEST(systems.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= systems.update_dtm
            RETURNING id64
        ),
        ins_fac AS (
            INSERT INTO system_factions (
                system_id64, name, state, allegiance, government, influence, update_dtm
            )
            SELECT 
                p.id64,
                fac->>'Name' AS name,
                {fac_state_expr} AS state,
                {fac_all_expr} AS allegiance,
                {fac_gov_expr} AS government,
                CASE WHEN fac->>'Influence' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (fac->>'Influence')::DOUBLE PRECISION ELSE NULL END AS influence,
                p.msg_dtm
            FROM parsed_sys p,
            LATERAL jsonb_array_elements(COALESCE(p.factions, '[]'::jsonb)) AS fac
            WHERE p.id64 IS NOT NULL AND fac->>'Name' IS NOT NULL
            ON CONFLICT (system_id64, name) DO UPDATE SET
                state = COALESCE(EXCLUDED.state, system_factions.state),
                allegiance = COALESCE(EXCLUDED.allegiance, system_factions.allegiance),
                government = COALESCE(EXCLUDED.government, system_factions.government),
                influence = COALESCE(EXCLUDED.influence, system_factions.influence),
                update_dtm = GREATEST(system_factions.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= system_factions.update_dtm
            RETURNING system_id64
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % systems/factions records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 3. Process Celestial Bodies (Scan Events)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[3/12] Backfilling bodies from Scan events...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name = 'Scan'
                OR e.raw_message->>'event' = 'Scan'
                OR e.schema_ref ILIKE '%journal/1%' AND e.raw_message->>'event' = 'Scan'
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_body AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' THEN (c.raw_message->>'SystemAddress')::BIGINT ELSE NULL END AS system_id64,
                CASE WHEN c.raw_message->>'BodyID' ~ '^[0-9]+$' THEN (c.raw_message->>'BodyID')::BIGINT ELSE NULL END AS bodyid,
                CASE 
                    WHEN c.raw_message->>'id64' ~ '^[0-9]+$' THEN (c.raw_message->>'id64')::BIGINT
                    WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' AND c.raw_message->>'BodyID' ~ '^[0-9]+$' 
                    THEN (((c.raw_message->>'SystemAddress')::BIGINT << 9) | (c.raw_message->>'BodyID')::BIGINT)
                    ELSE NULL 
                END AS id64,
                c.raw_message->>'BodyName' AS name,
                c.raw_message->>'StarType' AS starType,
                c.raw_message->>'PlanetClass' AS planetClass,
                {body_sub_expr} AS subtype,
                CASE WHEN c.raw_message->>'DistanceFromArrivalLS' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'DistanceFromArrivalLS')::DOUBLE PRECISION ELSE NULL END AS distancetoarrival,
                CASE WHEN c.raw_message->>'OrbitalPeriod' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'OrbitalPeriod')::DOUBLE PRECISION / 86400.0 ELSE NULL END AS orbitalperiod,
                CASE WHEN c.raw_message->>'SemiMajorAxis' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'SemiMajorAxis')::DOUBLE PRECISION / 1000.0 ELSE NULL END AS semimajoraxis,
                CASE WHEN c.raw_message->>'RotationPeriod' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'RotationPeriod')::DOUBLE PRECISION / 86400.0 ELSE NULL END AS rotationalperiod,
                CASE WHEN c.raw_message->>'SurfaceTemperature' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'SurfaceTemperature')::DOUBLE PRECISION ELSE NULL END AS surfacetemperature,
                CASE WHEN c.raw_message->>'Radius' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'Radius')::DOUBLE PRECISION / 1000.0 ELSE NULL END AS radius,
                COALESCE((c.raw_message->>'Landable')::BOOLEAN, FALSE) AS islandable,
                CASE WHEN c.raw_message->>'SurfaceGravity' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'SurfaceGravity')::DOUBLE PRECISION / 9.80665 ELSE NULL END AS gravity,
                CASE WHEN c.raw_message->>'MassEM' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'MassEM')::DOUBLE PRECISION ELSE NULL END AS earthmasses,
                CASE WHEN c.raw_message->>'SurfacePressure' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'SurfacePressure')::DOUBLE PRECISION / 101325.0 ELSE NULL END AS surfacepressure,
                CASE WHEN c.raw_message->>'StellarMass' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'StellarMass')::DOUBLE PRECISION ELSE NULL END AS solarmasses,
                CASE WHEN c.raw_message->>'StarType' IS NOT NULL AND c.raw_message->>'Radius' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'Radius')::DOUBLE PRECISION / 695700000.0 ELSE NULL END AS solarradius,
                c.raw_message->>'AtmosphereType' AS atmospheretype,
                {body_tf_expr} AS terraformingstate,
                {body_reserve_expr} AS reservelevel,
                c.raw_message->'AtmosphereComposition' AS atmospherecomposition,
                c.raw_message->'SolidComposition' AS solidcomposition,
                c.raw_message->'Materials' AS materials,
                c.raw_message->'Parents' AS parents,
                CASE 
                    WHEN (c.raw_message->>'timestamp') IS NOT NULL AND (c.raw_message->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c
        ),
        ins_bodies AS (
            INSERT INTO bodies (
                system_id64, id64, bodyid, name, type, subtype, distancetoarrival,
                orbitalperiod, semimajoraxis, rotationalperiod, surfacetemperature, radius, islandable, gravity, earthmasses,
                surfacepressure, solarmasses, solarradius, atmospheretype, terraformingstate, reservelevel, atmospherecomposition,
                solidcomposition, materials, parents, update_dtm
            )
            SELECT 
                p.system_id64, p.id64, p.bodyid, p.name,
                CASE WHEN p.starType IS NOT NULL THEN 'Star' ELSE 'Planet' END,
                p.subtype,
                p.distancetoarrival, p.orbitalperiod, p.semimajoraxis, p.rotationalperiod, p.surfacetemperature, p.radius, p.islandable,
                p.gravity, p.earthmasses, p.surfacepressure, p.solarmasses, p.solarradius, p.atmospheretype, p.terraformingstate,
                p.reservelevel, p.atmospherecomposition, p.solidcomposition, p.materials, p.parents, p.msg_dtm
            FROM parsed_body p
            WHERE p.id64 IS NOT NULL
            ON CONFLICT (id64) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, bodies.name),
                type = COALESCE(EXCLUDED.type, bodies.type),
                subtype = COALESCE(EXCLUDED.subtype, bodies.subtype),
                distancetoarrival = COALESCE(EXCLUDED.distancetoarrival, bodies.distancetoarrival),
                orbitalperiod = COALESCE(EXCLUDED.orbitalperiod, bodies.orbitalperiod),
                semimajoraxis = COALESCE(EXCLUDED.semimajoraxis, bodies.semimajoraxis),
                rotationalperiod = COALESCE(EXCLUDED.rotationalperiod, bodies.rotationalperiod),
                surfacetemperature = COALESCE(EXCLUDED.surfacetemperature, bodies.surfacetemperature),
                radius = COALESCE(EXCLUDED.radius, bodies.radius),
                islandable = COALESCE(EXCLUDED.islandable, bodies.islandable),
                gravity = COALESCE(EXCLUDED.gravity, bodies.gravity),
                earthmasses = COALESCE(EXCLUDED.earthmasses, bodies.earthmasses),
                surfacepressure = COALESCE(EXCLUDED.surfacepressure, bodies.surfacepressure),
                solarmasses = COALESCE(EXCLUDED.solarmasses, bodies.solarmasses),
                solarradius = COALESCE(EXCLUDED.solarradius, bodies.solarradius),
                atmospheretype = COALESCE(EXCLUDED.atmospheretype, bodies.atmospheretype),
                terraformingstate = COALESCE(EXCLUDED.terraformingstate, bodies.terraformingstate),
                reservelevel = COALESCE(EXCLUDED.reservelevel, bodies.reservelevel),
                atmospherecomposition = COALESCE(EXCLUDED.atmospherecomposition, bodies.atmospherecomposition),
                solidcomposition = COALESCE(EXCLUDED.solidcomposition, bodies.solidcomposition),
                materials = COALESCE(EXCLUDED.materials, bodies.materials),
                parents = COALESCE(EXCLUDED.parents, bodies.parents),
                update_dtm = GREATEST(bodies.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= bodies.update_dtm
            RETURNING id64
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % bodies records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 4. Process Stations (Docked & ApproachSettlement with Market Events)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[4/12] Backfilling stations from Docked / ApproachSettlement events...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name IN ('Docked', 'ApproachSettlement')
                OR e.raw_message->>'event' IN ('Docked', 'ApproachSettlement')
                OR e.schema_ref ILIKE '%journal/1%' AND e.raw_message->>'event' IN ('Docked', 'ApproachSettlement')
            )
            AND e.raw_message->>'MarketID' IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_station AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' THEN (c.raw_message->>'SystemAddress')::BIGINT ELSE NULL END AS system_id64,
                CASE WHEN c.raw_message->>'MarketID' ~ '^[0-9]+$' THEN (c.raw_message->>'MarketID')::BIGINT ELSE NULL END AS market_id,
                c.raw_message->>'StationName' AS name,
                {station_type_expr} AS type,
                {sta_all_expr} AS allegiance,
                {sta_gov_expr} AS government,
                {sta_econ_pri_expr} AS primaryeconomy,
                COALESCE(c.raw_message->>'DistFromStarLS', c.raw_message->>'DistanceFromArrivalLS')::DOUBLE PRECISION AS distancetoarrival,
                {sta_state_expr} AS state,
                {sta_fac_state_expr} AS controllingfactionstate,
                {sta_dock_expr} AS carrierdockingaccess,
                c.raw_message->'StationFaction'->>'Name' AS controllingfaction,
                c.raw_message->'StationServices' AS services,
                CASE WHEN c.raw_message->'LandingPads'->>'Large' ~ '^[0-9]+$' THEN (c.raw_message->'LandingPads'->>'Large')::INTEGER ELSE NULL END AS pad_large,
                CASE WHEN c.raw_message->'LandingPads'->>'Medium' ~ '^[0-9]+$' THEN (c.raw_message->'LandingPads'->>'Medium')::INTEGER ELSE NULL END AS pad_medium,
                CASE WHEN c.raw_message->'LandingPads'->>'Small' ~ '^[0-9]+$' THEN (c.raw_message->'LandingPads'->>'Small')::INTEGER ELSE NULL END AS pad_small,
                CASE 
                    WHEN (c.raw_message->>'timestamp') IS NOT NULL AND (c.raw_message->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c
        ),
        ins_stations AS (
            INSERT INTO stations (
                system_id64, market_id, name, type, allegiance, government, primaryeconomy,
                distancetoarrival, state, controllingfactionstate, carrierdockingaccess, controllingfaction,
                pad_large, pad_medium, pad_small, update_dtm
            )
            SELECT 
                p.system_id64, p.market_id, p.name, p.type, p.allegiance, p.government, p.primaryeconomy,
                p.distancetoarrival, p.state, p.controllingfactionstate, p.carrierdockingaccess, p.controllingfaction,
                p.pad_large, p.pad_medium, p.pad_small, p.msg_dtm
            FROM parsed_station p
            WHERE p.system_id64 IS NOT NULL AND p.market_id IS NOT NULL AND p.name IS NOT NULL
            ON CONFLICT (market_id) DO UPDATE SET
                system_id64 = EXCLUDED.system_id64,
                name = COALESCE(EXCLUDED.name, stations.name),
                type = COALESCE(EXCLUDED.type, stations.type),
                allegiance = COALESCE(EXCLUDED.allegiance, stations.allegiance),
                government = COALESCE(EXCLUDED.government, stations.government),
                primaryeconomy = COALESCE(EXCLUDED.primaryeconomy, stations.primaryeconomy),
                distancetoarrival = COALESCE(EXCLUDED.distancetoarrival, stations.distancetoarrival),
                state = COALESCE(EXCLUDED.state, stations.state),
                controllingfactionstate = COALESCE(EXCLUDED.controllingfactionstate, stations.controllingfactionstate),
                carrierdockingaccess = COALESCE(EXCLUDED.carrierdockingaccess, stations.carrierdockingaccess),
                controllingfaction = COALESCE(EXCLUDED.controllingfaction, stations.controllingfaction),
                pad_large = COALESCE(EXCLUDED.pad_large, stations.pad_large),
                pad_medium = COALESCE(EXCLUDED.pad_medium, stations.pad_medium),
                pad_small = COALESCE(EXCLUDED.pad_small, stations.pad_small),
                update_dtm = GREATEST(stations.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= stations.update_dtm
            RETURNING market_id
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % stations records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 5. Process Commodity Market Feeds
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[5/12] Backfilling commodity markets...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name = 'Commodity'
                OR e.schema_ref ILIKE '%commodity/3%'
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_comm AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->'message'->>'marketId' ~ '^[0-9]+$' THEN (c.raw_message->'message'->>'marketId')::BIGINT ELSE NULL END AS market_id,
                item->>'name' AS raw_name,
                {comm_name_expr} AS name,
                {comm_cat_expr} AS category,
                CASE WHEN item->>'buyPrice' ~ '^[0-9]+$' THEN (item->>'buyPrice')::INTEGER ELSE 0 END AS buyprice,
                CASE WHEN item->>'sellPrice' ~ '^[0-9]+$' THEN (item->>'sellPrice')::INTEGER ELSE 0 END AS sellprice,
                CASE WHEN item->>'meanPrice' ~ '^[0-9]+$' THEN (item->>'meanPrice')::INTEGER ELSE 0 END AS meanprice,
                CASE WHEN item->>'demand' ~ '^[0-9]+$' THEN (item->>'demand')::INTEGER ELSE 0 END AS demand,
                CASE WHEN item->>'stock' ~ '^[0-9]+$' THEN (item->>'stock')::INTEGER ELSE 0 END AS stock,
                CASE 
                    WHEN (c.raw_message->'message'->>'timestamp') IS NOT NULL AND (c.raw_message->'message'->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->'message'->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c,
            LATERAL jsonb_array_elements(COALESCE(c.raw_message->'message'->'commodities', '[]'::jsonb)) AS item
        ),
        ins_comm AS (
            INSERT INTO station_commodities (
                market_id, name, category, buyprice, sellprice, meanprice, demand, stock, update_dtm
            )
            SELECT 
                p.market_id, p.name, p.category, p.buyprice, p.sellprice, p.meanprice, p.demand, p.stock, p.msg_dtm
            FROM parsed_comm p
            WHERE p.market_id IS NOT NULL AND p.name IS NOT NULL
            ON CONFLICT (market_id, name) DO UPDATE SET
                category = COALESCE(EXCLUDED.category, station_commodities.category),
                buyprice = EXCLUDED.buyprice,
                sellprice = EXCLUDED.sellprice,
                meanprice = EXCLUDED.meanprice,
                demand = EXCLUDED.demand,
                stock = EXCLUDED.stock,
                update_dtm = GREATEST(station_commodities.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= station_commodities.update_dtm
            RETURNING market_id
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % commodity market records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 6. Process Shipyard Feeds
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[6/12] Backfilling shipyard feeds...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name = 'Shipyard'
                OR e.schema_ref ILIKE '%shipyard/2%'
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_ship AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->'message'->>'marketId' ~ '^[0-9]+$' THEN (c.raw_message->'message'->>'marketId')::BIGINT ELSE NULL END AS market_id,
                {ship_name_expr} AS name,
                CASE 
                    WHEN (c.raw_message->'message'->>'timestamp') IS NOT NULL AND (c.raw_message->'message'->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->'message'->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c,
            LATERAL jsonb_array_elements(COALESCE(c.raw_message->'message'->'ships', '[]'::jsonb)) AS item
        ),
        ins_ships AS (
            INSERT INTO station_ships (
                market_id, name, update_dtm
            )
            SELECT 
                p.market_id, p.name, p.msg_dtm
            FROM parsed_ship p
            WHERE p.market_id IS NOT NULL AND p.name IS NOT NULL
            ON CONFLICT (market_id, name) DO UPDATE SET
                update_dtm = GREATEST(station_ships.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= station_ships.update_dtm
            RETURNING market_id
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % shipyard records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 7. Process Outfitting Feeds
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[7/12] Backfilling outfitting feeds...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name = 'Outfitting'
                OR e.schema_ref ILIKE '%outfitting/2%'
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_mod AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->'message'->>'marketId' ~ '^[0-9]+$' THEN (c.raw_message->'message'->>'marketId')::BIGINT ELSE NULL END AS market_id,
                COALESCE((SELECT m.canonical_name FROM _norm_mappings m WHERE m.category = 'modules' AND m.raw_token = LOWER(TRIM(item->>'name'))), item->>'name') AS name,
                item->>'name' AS symbol,
                {mod_cat_expr} AS category,
                CASE 
                    WHEN (c.raw_message->'message'->>'timestamp') IS NOT NULL AND (c.raw_message->'message'->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->'message'->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c,
            LATERAL jsonb_array_elements(COALESCE(c.raw_message->'message'->'modules', '[]'::jsonb)) AS item
        ),
        ins_mods AS (
            INSERT INTO station_modules (
                market_id, name, symbol, category, update_dtm
            )
            SELECT 
                p.market_id, p.name, p.symbol, p.category, p.msg_dtm
            FROM parsed_mod p
            WHERE p.market_id IS NOT NULL AND p.name IS NOT NULL
            ON CONFLICT (market_id, symbol) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, station_modules.name),
                category = COALESCE(EXCLUDED.category, station_modules.category),
                update_dtm = GREATEST(station_modules.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= station_modules.update_dtm
            RETURNING market_id
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % outfitting records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 8. Process System Signals (FSSSignalDiscovered & Space Codex Scans)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[8/12] Backfilling system_signals...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name = 'FSSSignalDiscovered'
                OR e.raw_message->>'event' = 'FSSSignalDiscovered'
                OR e.schema_ref ILIKE '%fsssignaldiscovered%'
                OR (
                    (e.schema_ref ILIKE '%codexentry%' OR e.event_name = 'CodexEntry')
                    AND (
                        e.raw_message->>'Category' = '$Codex_Category_StellarPhenomena;'
                        OR e.raw_message->>'SubCategory' = '$Codex_SubCategory_Storms;'
                        OR e.raw_message->>'NearestDestination' ILIKE '%Life_Cloud%'
                        OR (e.raw_message->>'SubCategory' = '$Codex_SubCategory_Organic_Structures;' AND e.raw_message->>'Latitude' IS NULL)
                    )
                )
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_sig AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' THEN (c.raw_message->>'SystemAddress')::BIGINT ELSE NULL END AS system_id64,
                COALESCE(sig->>'SignalName', sig->>'Name') AS raw_name,
                COALESCE(
                    (SELECT m.canonical_name FROM _norm_mappings m WHERE m.category = 'scenarios' AND m.raw_token = LOWER(TRIM(COALESCE(sig->>'SignalName', sig->>'Name')))),
                    sig->>'SignalName_Localised',
                    sig->>'Name_Localised',
                    sig->>'SignalName',
                    sig->>'Name'
                ) AS name,
                COALESCE(
                    (SELECT m.signal_type FROM _norm_mappings m WHERE m.category = 'scenarios' AND m.raw_token = LOWER(TRIM(COALESCE(sig->>'SignalName', sig->>'Name')))),
                    (SELECT m.canonical_name FROM _norm_mappings m WHERE m.category = 'signal_types' AND m.raw_token = LOWER(TRIM(COALESCE(sig->>'SignalType', sig->>'Category')))),
                    'Notable Stellar Phenomena'
                ) AS signal_type,
                COALESCE(
                    (SELECT m.severity FROM _norm_mappings m WHERE m.category = 'scenarios' AND m.raw_token = LOWER(TRIM(COALESCE(sig->>'SignalName', sig->>'Name')))),
                    NULL
                ) AS severity,
                CASE WHEN sig->>'ThreatLevel' ~ '^[0-9]+$' THEN (sig->>'ThreatLevel')::INTEGER ELSE NULL END AS threat_level,
                sig->>'SpawningFaction' AS spawning_faction,
                {sig_state_expr} AS spawning_state,
                COALESCE((sig->>'IsStation')::BOOLEAN, FALSE) AS is_station,
                CASE 
                    WHEN (c.raw_message->>'timestamp') IS NOT NULL AND (c.raw_message->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c,
            LATERAL jsonb_array_elements(
                CASE 
                    WHEN jsonb_typeof(c.raw_message->'signals') = 'array' THEN c.raw_message->'signals'
                    WHEN c.raw_message->>'SignalName' IS NOT NULL OR c.raw_message->>'Name' IS NOT NULL THEN jsonb_build_array(c.raw_message)
                    ELSE '[]'::jsonb
                END
            ) AS sig
        ),
        ins_sigs AS (
            INSERT INTO system_signals (
                system_id64, signal_type, name, raw_name, severity, threat_level, spawning_faction, spawning_state, is_station, update_dtm
            )
            SELECT 
                p.system_id64, p.signal_type, p.name, p.raw_name, p.severity, p.threat_level, p.spawning_faction, p.spawning_state, p.is_station, p.msg_dtm
            FROM parsed_sig p
            WHERE p.system_id64 IS NOT NULL AND p.raw_name IS NOT NULL
            ON CONFLICT (system_id64, raw_name) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, system_signals.name),
                signal_type = COALESCE(EXCLUDED.signal_type, system_signals.signal_type),
                severity = COALESCE(EXCLUDED.severity, system_signals.severity),
                threat_level = COALESCE(EXCLUDED.threat_level, system_signals.threat_level),
                spawning_faction = COALESCE(EXCLUDED.spawning_faction, system_signals.spawning_faction),
                spawning_state = COALESCE(EXCLUDED.spawning_state, system_signals.spawning_state),
                is_station = COALESCE(EXCLUDED.is_station, system_signals.is_station),
                update_dtm = GREATEST(system_signals.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= system_signals.update_dtm
            RETURNING system_id64
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % system_signals records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 9. Process SAASignalsFound & Planetary Surface Codex Flora (body_signals)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[9/12] Backfilling body_signals from SAASignalsFound & Codex Flora...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name = 'SAASignalsFound'
                OR e.raw_message->>'event' = 'SAASignalsFound'
                OR e.schema_ref ILIKE '%saasignalsfound%'
                OR (
                    (e.schema_ref ILIKE '%codexentry%' OR e.event_name = 'CodexEntry')
                    AND e.raw_message->>'Category' = '$Codex_Category_Biology;'
                    AND e.raw_message->>'BodyID' IS NOT NULL
                    AND (e.raw_message->>'Latitude' IS NOT NULL OR e.raw_message->>'SubCategory' != '$Codex_SubCategory_Organic_Structures;')
                )
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_bsig AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' THEN (c.raw_message->>'SystemAddress')::BIGINT ELSE NULL END AS system_id64,
                CASE 
                    WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' AND c.raw_message->>'BodyID' ~ '^[0-9]+$' 
                    THEN (((c.raw_message->>'SystemAddress')::BIGINT << 9) | (c.raw_message->>'BodyID')::BIGINT)
                    ELSE NULL 
                END AS body_id64,
                CASE 
                    WHEN c.raw_message->'Signals' IS NOT NULL THEN (
                        SELECT jsonb_object_agg(
                            COALESCE((SELECT m.canonical_name FROM _norm_mappings m WHERE m.category = 'signal_types' AND m.raw_token = LOWER(TRIM(s->>'Type'))), s->>'Type'),
                            CASE WHEN s->>'Count' ~ '^[0-9]+$' THEN (s->>'Count')::INTEGER ELSE 1 END
                        )
                        FROM jsonb_array_elements(c.raw_message->'Signals') s
                    )
                    ELSE NULL
                END AS signals,
                CASE 
                    WHEN c.raw_message->'Genuses' IS NOT NULL THEN (
                        SELECT array_agg(DISTINCT COALESCE((SELECT m.canonical_name FROM _norm_mappings m WHERE m.category = 'genuses' AND m.raw_token = LOWER(TRIM(g->>'Genus'))), g->>'Genus'))
                        FROM jsonb_array_elements(c.raw_message->'Genuses') g
                    )
                    WHEN c.raw_message->>'Genus' IS NOT NULL OR c.raw_message->>'Name' IS NOT NULL THEN (
                        SELECT ARRAY[COALESCE((SELECT m.canonical_name FROM _norm_mappings m WHERE m.category = 'genuses' AND m.raw_token = LOWER(TRIM(COALESCE(c.raw_message->>'Genus', c.raw_message->>'Name')))), c.raw_message->>'Genus_Localised', c.raw_message->>'Name_Localised', c.raw_message->>'Genus', c.raw_message->>'Name')]
                    )
                    ELSE NULL
                END AS genuses,
                CASE 
                    WHEN (c.raw_message->>'timestamp') IS NOT NULL AND (c.raw_message->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c
        ),
        ins_bsigs AS (
            INSERT INTO body_signals (
                system_id64, body_id64, signals, genuses, update_dtm
            )
            SELECT 
                p.system_id64, p.body_id64, p.signals, p.genuses, p.msg_dtm
            FROM parsed_bsig p
            WHERE p.system_id64 IS NOT NULL AND p.body_id64 IS NOT NULL
            ON CONFLICT (body_id64) DO UPDATE SET
                signals = COALESCE(EXCLUDED.signals, body_signals.signals),
                genuses = COALESCE(EXCLUDED.genuses, body_signals.genuses),
                update_dtm = GREATEST(body_signals.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= body_signals.update_dtm
            RETURNING body_id64
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % body_signals records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 10. Process Carrier Material Sales (station_materials)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[10/12] Backfilling station_materials from CarrierDetail / FCMaterials...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name IN ('CarrierDetail', 'FCMaterials')
                OR e.schema_ref ILIKE '%fcmaterials%' OR e.schema_ref ILIKE '%carrierdetail%'
            )
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_mat AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->>'MarketID' ~ '^[0-9]+$' THEN (c.raw_message->>'MarketID')::BIGINT ELSE NULL END AS market_id,
                c.raw_message->>'CarrierID' AS carrier_id,
                CASE WHEN item->>'id' ~ '^[0-9]+$' THEN (item->>'id')::INTEGER ELSE (abs(hashtext(COALESCE(item->>'Name', item->>'name', '0'))) % 2147483647) END AS material_id,
                {material_name_expr} AS name,
                COALESCE(item->>'Name', item->>'name') AS symbol,
                item->>'category' AS category,
                CASE WHEN item->>'stock' ~ '^[0-9]+$' THEN (item->>'stock')::INTEGER ELSE 0 END AS stock,
                CASE WHEN item->>'demand' ~ '^[0-9]+$' THEN (item->>'demand')::INTEGER ELSE 0 END AS demand,
                CASE WHEN item->>'price' ~ '^[0-9]+$' THEN (item->>'price')::INTEGER ELSE 0 END AS buyprice,
                CASE 
                    WHEN (c.raw_message->>'timestamp') IS NOT NULL AND (c.raw_message->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c,
            LATERAL jsonb_array_elements(COALESCE(c.raw_message->'Materials', c.raw_message->'microresources', '[]'::jsonb)) AS item
        ),
        ins_mats AS (
            INSERT INTO station_materials (
                market_id, carrier_id, material_id, name, symbol, category, stock, demand, buyprice, update_dtm
            )
            SELECT 
                p.market_id, p.carrier_id, p.material_id, p.name, p.symbol, p.category, p.stock, p.demand, p.buyprice, p.msg_dtm
            FROM parsed_mat p
            WHERE p.market_id IS NOT NULL AND p.material_id IS NOT NULL AND p.name IS NOT NULL
            ON CONFLICT (market_id, material_id) DO UPDATE SET
                carrier_id = COALESCE(EXCLUDED.carrier_id, station_materials.carrier_id),
                name = COALESCE(EXCLUDED.name, station_materials.name),
                symbol = COALESCE(EXCLUDED.symbol, station_materials.symbol),
                category = COALESCE(EXCLUDED.category, station_materials.category),
                stock = EXCLUDED.stock,
                demand = EXCLUDED.demand,
                buyprice = EXCLUDED.buyprice,
                update_dtm = GREATEST(station_materials.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= station_materials.update_dtm
            RETURNING market_id
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % station_materials records.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 11. Process Surface POIs / Settlements (body_pois from Non-Market Settlements)
    -- --------------------------------------------------------------------------
    step_total := 0;
    RAISE NOTICE '[11/12] Backfilling body_pois from ApproachSettlement events...';
    LOOP
        WITH candidates AS (
            SELECT e.id, e.raw_message
            FROM eddn_unhandled_events e
            WHERE (
                e.event_name = 'ApproachSettlement'
                OR e.raw_message->>'event' = 'ApproachSettlement'
                OR e.schema_ref ILIKE '%approachsettlement%'
            )
            AND e.raw_message->>'MarketID' IS NULL
            AND EXISTS (
                SELECT 1 FROM _approved_senders a
                WHERE LOWER(TRIM(COALESCE(e.app_name, e.raw_message->'header'->>'softwareName', e.raw_message->'header'->>'appName', ''))) = LOWER(TRIM(a.sender_name))
            )
            LIMIT batch_size
            FOR UPDATE SKIP LOCKED
        ),
        parsed_poi AS (
            SELECT 
                c.id,
                CASE WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' THEN (c.raw_message->>'SystemAddress')::BIGINT ELSE NULL END AS system_id64,
                CASE 
                    WHEN c.raw_message->>'SystemAddress' ~ '^[0-9]+$' AND c.raw_message->>'BodyID' ~ '^[0-9]+$' 
                    THEN (((c.raw_message->>'SystemAddress')::BIGINT << 9) | (c.raw_message->>'BodyID')::BIGINT)
                    ELSE NULL 
                END AS body_id64,
                c.raw_message->>'BodyName' AS body_name,
                {poi_type_expr} AS poi_type,
                COALESCE(c.raw_message->>'Name_Localised', c.raw_message->>'Name') AS name,
                c.raw_message->>'Name' AS raw_name,
                CASE WHEN c.raw_message->>'Latitude' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'Latitude')::DOUBLE PRECISION ELSE NULL END AS latitude,
                CASE WHEN c.raw_message->>'Longitude' ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (c.raw_message->>'Longitude')::DOUBLE PRECISION ELSE NULL END AS longitude,
                CASE 
                    WHEN (c.raw_message->>'timestamp') IS NOT NULL AND (c.raw_message->>'timestamp') ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' 
                    THEN (c.raw_message->>'timestamp')::TIMESTAMP 
                    ELSE (now() AT TIME ZONE 'utc') 
                END AS msg_dtm
            FROM candidates c
        ),
        ins_pois AS (
            INSERT INTO body_pois (
                system_id64, body_id64, body_name, poi_type, name, raw_name, latitude, longitude, update_dtm
            )
            SELECT 
                p.system_id64, p.body_id64, p.body_name, p.poi_type, p.name, p.raw_name, p.latitude, p.longitude, p.msg_dtm
            FROM parsed_poi p
            WHERE p.system_id64 IS NOT NULL AND p.body_id64 IS NOT NULL AND p.raw_name IS NOT NULL
            ON CONFLICT (body_id64, raw_name) DO UPDATE SET
                body_name = COALESCE(EXCLUDED.body_name, body_pois.body_name),
                poi_type = COALESCE(EXCLUDED.poi_type, body_pois.poi_type),
                name = COALESCE(EXCLUDED.name, body_pois.name),
                latitude = COALESCE(EXCLUDED.latitude, body_pois.latitude),
                longitude = COALESCE(EXCLUDED.longitude, body_pois.longitude),
                update_dtm = GREATEST(body_pois.update_dtm, EXCLUDED.update_dtm)
            WHERE EXCLUDED.update_dtm >= body_pois.update_dtm
            RETURNING body_id64
        ),
        del_candidates AS (
            DELETE FROM eddn_unhandled_events
            WHERE id IN (SELECT id FROM candidates)
            RETURNING id
        )
        SELECT COUNT(*) INTO rows_affected FROM del_candidates;

        step_total := step_total + rows_affected;
        COMMIT;
        EXIT WHEN rows_affected = 0;
    END LOOP;
    RAISE NOTICE '   ✓ Backfilled % POI / Settlement events.', step_total;
    grand_total := grand_total + step_total;

    -- --------------------------------------------------------------------------
    -- 12. Run Normalizations & Remediation Pass
    -- --------------------------------------------------------------------------
    IF run_normalizations THEN
        RAISE NOTICE '[12/12] Running full database normalization & remediation pass...';
        CALL sp_normalize_galaxy_data(batch_size);
        RAISE NOTICE '   ✓ Completed normalization sweep across all tables.';
    END IF;

    RAISE NOTICE '==================================================';
    RAISE NOTICE 'EDDN DLQ Drain Complete! Total Events Backfilled: %', grand_total;
    RAISE NOTICE '==================================================';
END;
$$;

-- ------------------------------------------------------------------------------
-- Procedure Security Grants
-- ------------------------------------------------------------------------------
REVOKE EXECUTE ON PROCEDURE sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN) FROM PUBLIC;
REVOKE EXECUTE ON PROCEDURE sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN) FROM galaxy_searcher;
GRANT EXECUTE ON PROCEDURE sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN) TO galaxy_updater;
"""


def main() -> None:
    """CLI entry point for generating the DLQ processing stored procedure DDL."""
    default_output_path = Path(__file__).parent / "05_procedures" / "sp_process_eddn_dlq.sql"
    parser = argparse.ArgumentParser(
        description="Generate PostgreSQL EDDN DLQ processing stored procedure from config & YAML normalizations."
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml (default: autodiscover config.yaml)")
    parser.add_argument("--normalizations-dir", default=None, help="Path to normalizations YAML dir (default: eddn/normalizations)")
    parser.add_argument("--output", default=str(default_output_path), help=f"Output SQL file path (default: {default_output_path})")
    arguments = parser.parse_args()

    sql_content = generate_dlq_sp_sql(arguments.config, arguments.normalizations_dir)
    output_path = Path(arguments.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(sql_content, encoding="utf-8")
    print(f"[SUCCESS] Generated DLQ stored procedure DDL successfully: '{arguments.output}'")


if __name__ == "__main__":
    main()

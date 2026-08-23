"""Unit tests for EDDNRouter whitelisting, version filtering, DLQ dispatch, and debug logging."""

import pytest
import yaml

from eddn.metrics import EDDNMetrics
from eddn.router import EDDNRouter
from eddn.utils import EDDNUtils


@pytest.mark.parametrize(
    "software_name",
    [
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
        "E:D Market Connector [Windows]",
        "E:D Market Connector [Linux]",
        "E:D Market Connector [Mac]",
    ],
    ids=[
        "edmc",
        "eddiscovery",
        "eddi",
        "eddlite",
        "journalx",
        "edastro",
        "edastro_fleet",
        "edastro_sysmap",
        "edomaterials",
        "elite_observatory",
        "observatory_core",
        "icarus",
        "gameglass",
        "spansh_router",
        "spansh",
        "edmc_win",
        "edmc_linux",
        "edmc_mac",
    ],
)
def test_router_software_whitelist_accepted(software_name: str, sample_fsd_jump_payload: dict) -> None:
    """Validates that all approved community sender software tools pass the router whitelist."""
    metrics = EDDNMetrics()
    router = EDDNRouter(config_data=EDDNUtils.load_config("config.yaml"), metrics=metrics)

    payload = dict(sample_fsd_jump_payload)
    payload["header"] = dict(sample_fsd_jump_payload["header"])
    payload["header"]["softwareName"] = software_name

    records = router.route(payload)
    assert len(records) > 0
    assert all(r.table_name != "eddn_unhandled_events" for r in records)
    assert metrics.filtered_senders_count == 0


def test_router_unapproved_sender_routes_to_dlq(sample_fsd_jump_payload: dict) -> None:
    """Validates that unapproved sender applications are intercepted and routed to the DLQ."""
    metrics = EDDNMetrics()
    router = EDDNRouter(config_data=EDDNUtils.load_config("config.yaml"), metrics=metrics)

    payload = dict(sample_fsd_jump_payload)
    payload["header"] = dict(sample_fsd_jump_payload["header"])
    payload["header"]["softwareName"] = "UnapprovedCustomBot"

    records = router.route(payload)
    assert len(records) == 1
    assert records[0].table_name == "eddn_unhandled_events"
    assert records[0].data["dlq_reason"] == "unapproved_sender"
    assert metrics.filtered_senders_count == 1


def test_router_missing_software_name_routes_to_dlq(sample_fsd_jump_payload: dict) -> None:
    """Validates that headers missing softwareName route to DLQ as unapproved sender when whitelist is active."""
    metrics = EDDNMetrics()
    router = EDDNRouter(config_data=EDDNUtils.load_config("config.yaml"), metrics=metrics)

    payload = dict(sample_fsd_jump_payload)
    payload["header"] = dict(sample_fsd_jump_payload["header"])
    payload["header"]["softwareName"] = "   "
    payload["header"]["gameversion"] = "   "

    records = router.route(payload)
    assert len(records) == 1
    assert records[0].table_name == "eddn_unhandled_events"
    assert records[0].data["dlq_reason"] == "unapproved_sender"
    assert metrics.filtered_senders_count == 1


def test_router_sender_bypass_version_check(tmp_path) -> None:
    """Validates bypass_version_check flag allows designated tools with legacy or missing versions."""
    metrics = EDDNMetrics()
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "min_game_version": "4.0",
                "allowed_senders": [
                    {"name": "EDMarketConnector", "bypass_version_check": False},
                    {"name": "LegacyArchiver", "bypass_version_check": True},
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded_cfg = EDDNUtils.load_config(str(config_file))
    router = EDDNRouter(config_data=loaded_cfg, metrics=metrics)

    # 1. Non-bypassed tool with Legacy version -> dropped (0 records)
    legacy_standard = {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {"uploaderID": "Cmdr", "softwareName": "EDMarketConnector", "gameversion": "3.8.0.1400"},
        "message": {"event": "FSDJump", "timestamp": "2026-08-18T14:30:00Z", "SystemAddress": 10477373803, "StarSystem": "Sol"},
    }
    assert len(router.route(legacy_standard)) == 0

    # 2. Bypassed tool with Legacy version -> accepted
    legacy_bypassed = {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {"uploaderID": "Cmdr", "softwareName": "LegacyArchiver", "gameversion": "3.8.0.1400"},
        "message": {"event": "FSDJump", "timestamp": "2026-08-18T14:30:00Z", "SystemAddress": 10477373803, "StarSystem": "Sol"},
    }
    recs = router.route(legacy_bypassed)
    assert len(recs) > 0
    assert all(r.table_name != "eddn_unhandled_events" for r in recs)


@pytest.mark.parametrize(
    "live_version",
    ["4.0.0.1451", "4.1.0", "5.0.0", "Live", "CAPI-Live-market"],
    ids=["4.0_base", "4.1_minor", "5.0_major", "live_string", "capi_live"],
)
def test_router_live_game_version_accepted(live_version: str, sample_fsd_jump_payload: dict) -> None:
    """Validates that Live game versions are processed into domain records."""
    metrics = EDDNMetrics()
    router = EDDNRouter(config_data=EDDNUtils.load_config("config.yaml"), metrics=metrics)

    payload = dict(sample_fsd_jump_payload)
    payload["header"] = dict(sample_fsd_jump_payload["header"])
    payload["header"]["gameversion"] = live_version

    records = router.route(payload)
    assert len(records) > 0
    assert all(r.table_name != "eddn_unhandled_events" for r in records)


@pytest.mark.parametrize(
    "legacy_version",
    ["3.8.0.1400", "3.8_Legacy", "Legacy", "CAPI-Legacy-market"],
    ids=["3.8_base", "3.8_legacy_string", "legacy_keyword", "capi_legacy"],
)
def test_router_legacy_game_version_dropped_without_dlq(legacy_version: str, sample_fsd_jump_payload: dict) -> None:
    """Validates that Legacy version events are dropped cleanly without populating the DLQ."""
    metrics = EDDNMetrics()
    router = EDDNRouter(config_data=EDDNUtils.load_config("config.yaml"), metrics=metrics)

    payload = dict(sample_fsd_jump_payload)
    payload["header"] = dict(sample_fsd_jump_payload["header"])
    payload["header"]["gameversion"] = legacy_version

    records = router.route(payload)
    assert len(records) == 0
    assert metrics.filtered_game_versions_count == 1


def test_router_below_min_game_version_routes_to_dlq(sample_fsd_jump_payload: dict) -> None:
    """Validates that versions below min_game_version threshold route to DLQ with detailed reason."""
    metrics = EDDNMetrics()
    default_config = EDDNUtils.load_config("config.yaml")
    router = EDDNRouter(config_data={**default_config, "min_game_version": "4.1"}, metrics=metrics)

    payload = dict(sample_fsd_jump_payload)
    payload["header"] = dict(sample_fsd_jump_payload["header"])
    payload["header"]["gameversion"] = "4.0.0.1451"

    records = router.route(payload)
    assert len(records) == 1
    assert records[0].table_name == "eddn_unhandled_events"
    assert "below_min_game_version" in records[0].data["dlq_reason"]


def test_router_debug_log_rule_matching_and_payload_capture() -> None:
    """Validates granular debug_log rule evaluation and raw payload archiving."""
    test_uid = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    router = EDDNRouter(
        config_data={
            "allowed_senders": [{"name": "EDMarketConnector", "bypass_version_check": False}],
            "debug_log": [
                {"label": "Commander_Filter", "match": {"header.uploaderID": test_uid}},
                {"label": "Commodity_Filter", "match": {"message.commodities.name": "SpecialOre"}},
            ],
        }
    )

    # 1. Matches Commander filter
    payload = {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": test_uid,
            "softwareName": "EDMarketConnector",
            "softwareVersion": "1.0",
            "gameversion": "4.0.0.1451",
        },
        "message": {
            "event": "Docked",
            "timestamp": "2026-08-20T18:45:00Z",
            "StationName": "Test Port",
            "MarketID": 128000100,
            "StationType": "Coriolis",
            "SystemAddress": 10477373803,
        },
    }
    records = router.route(payload)
    debug_recs = [r for r in records if r.table_name == "_raw_debug_log"]
    domain_recs = [r for r in records if r.table_name == "stations"]

    assert len(debug_recs) == 1
    assert debug_recs[0].data["filter_label"] == "Commander_Filter"
    assert debug_recs[0].data["uploader_id"] == test_uid
    assert len(domain_recs) == 1


def test_router_debug_all_flag_captures_unconditionally(sample_fsd_jump_payload: dict) -> None:
    """Validates that debug_all=True routes every event to _raw_debug_log with All_Messages label."""
    router = EDDNRouter(
        config_data={
            "allowed_senders": [{"name": "EDMarketConnector", "bypass_version_check": False}],
            "debug_all": True,
            "debug_log": [],
        }
    )
    records = router.route(sample_fsd_jump_payload)
    debug_recs = [r for r in records if r.table_name == "_raw_debug_log"]
    assert len(debug_recs) == 1
    assert debug_recs[0].data["filter_label"] == "All_Messages"


def test_router_dlq_unhandled_schema_and_validation_error() -> None:
    """Validates unhandled schemas and schema validation exceptions route to DLQ cleanly."""
    metrics = EDDNMetrics()
    router = EDDNRouter(config_data={"enable_dlq": True, "min_game_version": "4.0"}, metrics=metrics)

    # 1. Ignored schema (navroute) -> returns no DLQ
    payload = {
        "$schemaRef": "https://eddn.edcd.io/schemas/navroute/1",
        "header": {"uploaderID": "Cmdr", "softwareName": "EDMarketConnector", "gameversion": "4.0.0.1451"},
        "message": {"event": "NavRoute", "timestamp": "2026-08-20T18:46:00Z", "Route": []},
    }
    assert len(router.route(payload)) == 0

    # 2. Unknown schema that is not ignored -> routes to DLQ
    unknown_schema_payload = {
        "$schemaRef": "https://eddn.edcd.io/schemas/unknown_future_schema/99",
        "header": {"uploaderID": "Cmdr", "softwareName": "EDMarketConnector", "gameversion": "4.0.0.1451"},
        "message": {"event": "FutureEvent", "timestamp": "2026-08-20T18:46:00Z"},
    }
    recs = router.route(unknown_schema_payload)
    assert len(recs) == 1
    assert recs[0].table_name == "eddn_unhandled_events"
    assert "unhandled_schema" in recs[0].data["dlq_reason"]

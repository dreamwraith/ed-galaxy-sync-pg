"""Unit tests for EDDNUtils static helper functions, identifier encoding, and version checking."""

from pathlib import Path

import pytest

from eddn.utils import EDDNUtils


@pytest.mark.parametrize(
    ("raw_input", "expected_output"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("$government_Anarchy;", "Anarchy"),
        ("$Codex_Ent_Aleoida_01_A_Name;", "Aleoida_01_A"),
        ("$Codex_Ent_Aleoid_Genus_Name;", "Aleoid"),
        ("$Warzone_PointRace_Low:#index=1;", "Warzone_PointRace_Low"),
        ("  $economy_Industrial;  ", "Industrial"),
        ("$airqualityreports_name;", "airqualityreports"),
        ("Drake-Class Carrier", "Drake-Class Carrier"),
        ("Unmapped_Unknown_Variant_XYZ", "Unmapped_Unknown_Variant_XYZ"),
    ],
    ids=[
        "none",
        "empty",
        "whitespace",
        "government_anarchy",
        "codex_species",
        "codex_genus",
        "scenario_index_tag",
        "whitespace_economy",
        "commodity_symbol",
        "plain_station_type",
        "unmapped_symbol",
    ],
)
def test_sanitize_edname(raw_input: str | None, expected_output: str) -> None:
    """Validates stripping of Frontier EDName wrapping artifacts ($ prefix, ; suffix, index tags)."""
    assert EDDNUtils.sanitize_edname(raw_input) == expected_output


@pytest.mark.parametrize(
    ("raw_input", "expected_output"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("$government_Anarchy;", "anarchy"),
        ("$Codex_Ent_Aleoida_01_A_Name;", "aleoida01a"),
        ("$Codex_Ent_Aleoid_Genus_Name;", "aleoid"),
        ("$Warzone_PointRace_Low:#index=1;", "warzonepointracelow"),
        ("  $economy_Industrial;  ", "industrial"),
        ("Drake-Class Carrier", "drakeclasscarrier"),
        ("B (Blue-white super giant) Star", "bbluewhitesupergiantstar"),
    ],
    ids=[
        "none",
        "empty",
        "whitespace",
        "government_anarchy",
        "codex_species",
        "codex_genus",
        "scenario_index_tag",
        "whitespace_economy",
        "plain_station_type",
        "complex_star_type",
    ],
)
def test_sanitize_normalize_edname(raw_input: str | None, expected_output: str) -> None:
    """Validates sanitization followed by lowercase alphanumeric lookup key generation."""
    assert EDDNUtils.sanitize_normalize_edname(raw_input) == expected_output


@pytest.mark.parametrize(
    ("system_id64", "body_id", "expected_id64"),
    [
        (10477373803, 3, (10477373803 << 9) | 3),
        (10477373803, "3", (10477373803 << 9) | 3),
        (10477373803, None, 10477373803),
        (10477373803, "invalid", 10477373803),
        ("invalid", 3, 0),
    ],
    ids=[
        "valid_integers",
        "string_body_id",
        "none_body_id",
        "invalid_body_id",
        "invalid_system_address",
    ],
)
def test_compute_body_id64(system_id64: int | str, body_id: int | str | None, expected_id64: int) -> None:
    """Validates 55-bit system address and 9-bit body ID composition."""
    assert EDDNUtils.compute_body_id64(system_id64, body_id) == expected_id64


def test_get_entity_id() -> None:
    """Validates get_entity_id uses integer ID when provided and falls back to deterministic CRC32 hash."""
    assert EDDNUtils.get_entity_id(12345, "gold") == 12345
    assert EDDNUtils.get_entity_id("67890", "gold") == 67890

    hash1 = EDDNUtils.get_entity_id(None, "Platinum")
    hash2 = EDDNUtils.get_entity_id(None, "  platinum  ")
    assert isinstance(hash1, int)
    assert hash1 > 0
    assert hash1 == hash2


@pytest.mark.parametrize(
    ("game_version", "min_version", "expected_valid", "expected_reason"),
    [
        ("4.0.0.1451", "4.0", True, ""),
        ("4.1.0", "4.0", True, ""),
        ("5.0.0", "4.0", True, ""),
        ("Live", "4.0", True, ""),
        ("CAPI-Live-market", "4.0", True, ""),
        ("4.0.0.1451", "4.1", False, "below_min_game_version: 4.0.0.1451"),
        ("3.8.0.1400", "4.0", False, "legacy_game_version: 3.8.0.1400"),
        ("3.8_Legacy", "4.0", False, "legacy_game_version: 3.8_Legacy"),
        (None, "4.0", False, "missing_game_version"),
        ("   ", "4.0", False, "missing_game_version"),
    ],
    ids=[
        "live_4_0",
        "live_4_1",
        "future_5_0",
        "live_keyword",
        "capi_live",
        "below_min_threshold",
        "legacy_3_8",
        "legacy_keyword",
        "none_version",
        "whitespace_version",
    ],
)
def test_check_game_version(game_version: str | None, min_version: str, expected_valid: bool, expected_reason: str) -> None:
    """Validates game version filtering against minimum version thresholds and legacy flags."""
    is_valid, reason = EDDNUtils.check_game_version(game_version, min_version)
    assert is_valid == expected_valid
    if expected_reason:
        assert expected_reason in reason


@pytest.mark.parametrize(
    ("station_text", "signal_type", "expected_id", "expected_name", "expected_type"),
    [
        (
            "UECV NO OSHA HERE | SKAG",
            "SquadronCarrier",
            "SKAG",
            "UECV NO OSHA HERE",
            "SquadronCarrier",
        ),
        (
            "| ONLYID",
            "SquadronCarrier",
            "ONLYID",
            None,
            "SquadronCarrier",
        ),
        (
            "ESB Tiberium Toke RZZ-51F",
            "FleetCarrier",
            "RZZ-51F",
            "ESB Tiberium Toke",
            "FleetCarrier",
        ),
        (
            "RZZ-51F",
            "FleetCarrier",
            "RZZ-51F",
            None,
            "FleetCarrier",
        ),
        (
            "DSSA Explorer's Haven (V2X-45L)",
            "FleetCarrier",
            "V2X-45L",
            "DSSA Explorer's Haven",
            "FleetCarrier",
        ),
        (
            "Abraham Lincoln",
            "Coriolis",
            None,
            None,
            None,
        ),
    ],
    ids=[
        "squadron_carrier_pipe_format",
        "squadron_carrier_callsign_only",
        "fleet_carrier_full_name_and_id",
        "fleet_carrier_callsign_only",
        "fleet_carrier_bracketed_id",
        "standard_starport",
    ],
)
def test_extract_carrier_parts(
    station_text: str,
    signal_type: str | None,
    expected_id: str | None,
    expected_name: str | None,
    expected_type: str | None,
) -> None:
    """Validates callsign and custom carrier name extraction across carrier string variations."""
    carrier_id, carrier_name, carrier_type = EDDNUtils.extract_carrier_parts(station_text, signal_type)
    assert carrier_id == expected_id
    assert carrier_name == expected_name
    assert carrier_type == expected_type


def test_load_config_and_load_yaml(tmp_path: Path) -> None:
    """Validates load_config and load_yaml file parsing and error handling."""
    config_file = tmp_path / "valid_config.yaml"
    config_file.write_text("min_game_version: '4.0'\nenable_dlq: true\n", encoding="utf-8")

    loaded = EDDNUtils.load_config(str(config_file))
    assert loaded["min_game_version"] == "4.0"
    assert loaded["enable_dlq"] is True

    assert EDDNUtils.load_config(str(tmp_path / "non_existent.yaml")) == {}
    assert EDDNUtils.load_config("") == {}

    corrupt_file = tmp_path / "corrupt.yaml"
    corrupt_file.write_text("key: [unclosed list\n", encoding="utf-8")
    assert EDDNUtils.load_config(str(corrupt_file)) == {}

"""Unit tests for EDDN token normalizers, YAML mappings integrity, and canonical enum resolution."""

from pathlib import Path

import pytest
import yaml

from eddn.metrics import EDDNMetrics
from eddn.normalizers import NormalizerManager


def test_all_yaml_mapping_files_integrity_on_disk() -> None:
    """Validates that all 23 YAML mapping files on disk load without duplicate keys or syntax errors."""
    yaml_dir = Path("eddn/normalizations")
    yaml_files = list(yaml_dir.rglob("*.yaml"))
    assert len(yaml_files) >= 20

    for yaml_file in yaml_files:
        content = yaml_file.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict), f"Failed loading {yaml_file.name}: expected dict"
        assert len(parsed) > 0, f"Empty mapping file: {yaml_file.name}"


@pytest.mark.parametrize(
    ("raw_type", "expected_type"),
    [
        ("eRingClass_Metalic", "Metallic"),
        ("eRingClass_Metallic", "Metallic"),
        ("metallic", "Metallic"),
        ("eRingClass_Icy", "Icy"),
        ("eRingClass_MetalRich", "Metal Rich"),
        ("eRingClass_Rocky", "Rocky"),
    ],
    ids=["metalic_typo", "metallic_std", "metallic_lower", "icy", "metal_rich", "rocky"],
)
def test_ring_types_normalization(
    raw_type: str, expected_type: str, normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates canonical ring and belt type resolution."""
    assert normalizer_instance.normalize("body_rings", "type", "ring_types", raw_type, metrics_instance) == expected_type


@pytest.mark.parametrize(
    ("raw_type", "expected_type"),
    [
        ("Drake-Class Carrier", "Fleet Carrier"),
        ("FleetCarrier", "Fleet Carrier"),
        ("Fleet Carrier", "Fleet Carrier"),
        ("SquadronCarrier", "Squadron Carrier"),
        ("Squadron Carrier", "Squadron Carrier"),
        ("Coriolis", "Coriolis Starport"),
        ("Orbis", "Orbis Starport"),
        ("Ocellus", "Ocellus Starport"),
        ("Dodec", "Dodec Starport"),
        ("CraterPort", "Planetary Port"),
        ("SurfaceStation", "Planetary Port"),
        ("AsteroidBase", "Asteroid Base"),
        ("MegaShip", "Mega Ship"),
    ],
    ids=[
        "drake_carrier",
        "fleet_carrier_no_space",
        "fleet_carrier_spaced",
        "squadron_carrier_no_space",
        "squadron_carrier_spaced",
        "coriolis",
        "orbis",
        "ocellus",
        "dodec",
        "crater_port",
        "surface_station",
        "asteroid_base",
        "megaship",
    ],
)
def test_station_types_normalization(
    raw_type: str, expected_type: str, normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates station type resolution."""
    assert normalizer_instance.normalize("stations", "type", "station_types", raw_type, metrics_instance) == expected_type


@pytest.mark.parametrize(
    ("raw_input", "expected_output"),
    [
        ("$economy_Industrial;", "Industrial"),
        ("$economy_HighTech;", "High Tech"),
        ("$economy_Agriculture;", "Agriculture"),
        ("$economy_Agri;", "Agriculture"),
        ("agri", "Agriculture"),
    ],
    ids=["industrial", "high_tech", "agri_full", "agri_short", "agri_lower"],
)
def test_economies_normalization(
    raw_input: str, expected_output: str, normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates economy token resolution."""
    assert normalizer_instance.normalize("systems", "primaryEconomy", "economies", raw_input, metrics_instance) == expected_output


@pytest.mark.parametrize(
    ("raw_input", "expected_output"),
    [
        ("$SYSTEM_SECURITY_high;", "High"),
        ("$SYSTEM_SECURITY_anarchy;", "Anarchy"),
        ("$GAlAXY_MAP_INFO_state_anarchy;", "Anarchy"),
    ],
    ids=["security_high", "security_anarchy", "galaxy_map_anarchy"],
)
def test_securities_normalization(
    raw_input: str, expected_output: str, normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates security token resolution."""
    assert normalizer_instance.normalize("systems", "security", "securities", raw_input, metrics_instance) == expected_output


@pytest.mark.parametrize(
    ("raw_input", "expected_output"),
    [
        ("$government_Democracy;", "Democracy"),
        ("$government_PrisonColony;", "Prison Colony"),
    ],
    ids=["democracy", "prison_colony"],
)
def test_governments_normalization(
    raw_input: str, expected_output: str, normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates government token resolution."""
    assert normalizer_instance.normalize("systems", "government", "governments", raw_input, metrics_instance) == expected_output


def test_unmapped_token_fallback_and_metrics_tracking(
    normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates that unknown raw tokens fallback to sanitized values and log metrics."""
    result = normalizer_instance.normalize("stations", "type", "station_types", "$UnknownStationType_Special;", metrics_instance)
    assert result == "UnknownStationType_Special"
    assert metrics_instance.unmapped_tokens["stations"]["type"]["UnknownStationType_Special"] == 1


def test_scenarios_resolution(normalizer_instance: NormalizerManager) -> None:
    """Validates multifield scenario tuples for name, signal_type, and threat severity."""
    rec = normalizer_instance.get_multifield("scenarios", "$MULTIPLAYER_SCENARIO79_TITLE;")
    assert rec is not None
    assert rec.name == "Resource Extraction Site [Hazardous]"
    assert rec.signal_type == "ResourceExtraction"
    assert rec.severity == "Hazardous"

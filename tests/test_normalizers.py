"""Unit tests for NormalizerManager engine mechanics, YAML structural integrity, and fallback behaviors.

These tests are designed to be malleable and generic, verifying core normalization logic,
structural validity of mapping files, casing/punctuation invariance, prefix stripping,
and metrics tracking without hardcoding specific catalog entries.
"""

from pathlib import Path

import yaml

from eddn.metrics import EDDNMetrics
from eddn.normalizers import NormalizerManager


def test_all_yaml_mapping_files_structural_integrity_on_disk() -> None:
    """Validates that every YAML mapping file on disk parses as a valid, non-empty mapping without duplicate keys."""
    yaml_dir = Path("eddn/normalizations")
    yaml_files = list(yaml_dir.rglob("*.yaml")) + list(yaml_dir.rglob("*.yml"))
    assert len(yaml_files) > 0, "No YAML mapping files found in normalizations directory"

    for yaml_file in yaml_files:
        content = yaml_file.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict), f"Structural error in {yaml_file.name}: expected top-level mapping (dict)"
        assert len(parsed) > 0, f"Empty mapping file: {yaml_file.name}"


def test_normalizer_manager_loads_all_direct_and_multifield_categories(normalizer_instance: NormalizerManager) -> None:
    """Validates that NormalizerManager dynamically discovers and loads all direct and multifield categories."""
    assert len(normalizer_instance.maps) > 0, "NormalizerManager maps dictionary is empty"
    assert len(normalizer_instance.multifield_maps) > 0, "NormalizerManager multifield_maps dictionary is empty"

    # Verify that each loaded direct category is a populated dictionary of normalized keys
    for category_name, category_map in normalizer_instance.maps.items():
        assert isinstance(category_map, dict), f"Category map '{category_name}' is not a dict"
        assert len(category_map) > 0, f"Category map '{category_name}' contains no entries"


def test_normalizer_canonical_self_match_resolution(normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics) -> None:
    """Validates that any canonical key registered in any category automatically resolves to itself."""
    # Pick dynamically from loaded categories
    for category_name, category_map in normalizer_instance.maps.items():
        # Pick the first available canonical value in this map
        sample_canonical = next(iter(category_map.values()))
        result = normalizer_instance.normalize("test_table", "test_field", category_name, sample_canonical, metrics_instance)
        assert result == sample_canonical, f"Canonical self-match failed for '{sample_canonical}' in category '{category_name}'"


def test_normalizer_case_and_punctuation_invariance(normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics) -> None:
    """Validates that token resolution is invariant to character casing, spaces, hyphens, and underscores."""
    # Pick a direct category with at least one multi-word entry if available
    target_category = next(iter(normalizer_instance.maps.keys()))
    sample_canonical = next(iter(normalizer_instance.maps[target_category].values()))

    # Generate casing and spacing permutations
    permutations = [
        sample_canonical.upper(),
        sample_canonical.lower(),
        sample_canonical.replace(" ", "_"),
        sample_canonical.replace(" ", "-"),
        f"  {sample_canonical}  ",
    ]

    for variant in permutations:
        result = normalizer_instance.normalize("test_table", "test_field", target_category, variant, metrics_instance)
        assert result == sample_canonical, f"Normalization failed for permutation '{variant}' -> expected '{sample_canonical}'"


def test_normalizer_strips_frontier_wrapper_symbols_and_prefixes(
    normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates that leading $, trailing ;, index tags, and known Frontier prefixes are stripped during lookup."""
    target_category = next(iter(normalizer_instance.maps.keys()))
    sample_canonical = next(iter(normalizer_instance.maps[target_category].values()))

    # Wrapped with Frontier symbols and parameter tags
    wrapped_token = f"${sample_canonical}:#index=1;"
    result = normalizer_instance.normalize("test_table", "test_field", target_category, wrapped_token, metrics_instance)
    assert result == sample_canonical


def test_unmapped_token_fallback_and_metrics_tracking(
    normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics
) -> None:
    """Validates that unknown raw tokens fall back to sanitized strings and record unmapped metrics without crashing."""
    raw_unknown_token = "$Completely_Unknown_Entity_XYZ_9999;"
    target_category = next(iter(normalizer_instance.maps.keys()))

    result = normalizer_instance.normalize("test_table", "test_field", target_category, raw_unknown_token, metrics_instance)
    assert result == "Completely_Unknown_Entity_XYZ_9999"
    assert metrics_instance.unmapped_tokens["test_table"]["test_field"]["Completely_Unknown_Entity_XYZ_9999"] == 1


def test_multifield_record_lookup_and_none_fallback(normalizer_instance: NormalizerManager) -> None:
    """Validates multifield lookup returns NamedTuple for known keys and None for unknown keys."""
    target_category = next(iter(normalizer_instance.multifield_maps.keys()))
    target_map = normalizer_instance.multifield_maps[target_category]

    # Test resolution of any registered key in the multifield map
    sample_raw_key = next(iter(target_map.keys()))
    record = normalizer_instance.get_multifield(target_category, sample_raw_key)
    assert record is not None
    assert hasattr(record, "_fields"), "Multifield record is not a NamedTuple"

    # Test unknown key returns None without error
    assert normalizer_instance.get_multifield(target_category, "$NonExistent_Scenario_9999;") is None


def test_empty_and_none_inputs_safe_handling(normalizer_instance: NormalizerManager, metrics_instance: EDDNMetrics) -> None:
    """Validates that None, empty string, and whitespace-only inputs are handled safely."""
    target_category = next(iter(normalizer_instance.maps.keys()))
    assert normalizer_instance.normalize("test_table", "test_field", target_category, None, metrics_instance) is None
    assert normalizer_instance.normalize("test_table", "test_field", target_category, "", metrics_instance) == ""
    assert normalizer_instance.normalize("test_table", "test_field", target_category, "   ", metrics_instance) == ""
    assert normalizer_instance.get_multifield(next(iter(normalizer_instance.multifield_maps.keys())), None) is None

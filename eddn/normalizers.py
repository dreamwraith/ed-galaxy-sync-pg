"""YAML-driven canonical token normalization engine for Frontier journal entities.

Loads modular normalization YAML dictionaries from two directory tiers:

- **Direct mappings** (``direct/``): Single-field canonical-to-variants inverted
  lookup tables for economies, governments, allegiances, ship names, etc.
- **Multifield mappings** (``multifield/``): Multi-attribute entity definitions
  (e.g. FSS scenarios, biological species) materialized as dynamically typed
  ``NamedTuple`` objects for structured resolution.

All lookups are O(1) case- and punctuation-insensitive via pre-normalized keys.
"""

import collections
import logging
from pathlib import Path
from typing import Any

import yaml

from .utils import EDDNUtils


logger = logging.getLogger(__name__)


class NormalizerManager:
    """Manages static in-memory lookup tables for token normalization and enum mapping.

    Provides canonical mapping for system allegiances, governments, economies,
    station types, commodity categories, module categories, planet classes,
    star types, body reserve levels, terraform states, and FSS scenarios.

    All lookups are O(1) case- and punctuation-insensitive via pre-normalized keys.
    """

    def __init__(
        self,
        config_dir: str | Path | None = None,
        direct_dir: str | Path | None = None,
        multifield_dir: str | Path | None = None,
    ) -> None:
        """Initializes NormalizerManager and automatically loads all YAML mapping dictionaries.

        Args:
            config_dir: Base directory containing 'direct' and 'multifield' subdirectories.
            direct_dir: Optional explicit override path for direct single-value mapping YAML files.
            multifield_dir: Optional explicit override path for multifield entity YAML files.
        """
        if config_dir is None:
            package_normalizations_dir = Path(__file__).parent / "normalizations"
            if package_normalizations_dir.is_dir():
                self.config_dir = package_normalizations_dir
            elif Path("eddn/normalizations").is_dir():
                self.config_dir = Path("eddn/normalizations")
            elif Path("normalizations").is_dir():
                self.config_dir = Path("normalizations")
            else:
                self.config_dir = package_normalizations_dir
        else:
            self.config_dir = Path(config_dir)

        direct_candidate = self.config_dir / "direct"
        multifield_candidate = self.config_dir / "multifield"

        self.direct_dir = Path(direct_dir) if direct_dir else (direct_candidate if direct_candidate.is_dir() else self.config_dir)
        self.multifield_dir = (
            Path(multifield_dir) if multifield_dir else (multifield_candidate if multifield_candidate.is_dir() else self.config_dir)
        )

        self.maps: dict[str, dict[str, str]] = {}
        self.multifield_maps: dict[str, dict[str, Any]] = {}
        self.load_all()

    def load_direct_maps(self, directory: str | Path | None = None) -> None:
        """Loads canonical-to-variants inverted mapping YAML files into high-speed O(1) lookup tables."""
        target_directory = Path(directory) if directory else self.direct_dir
        if not target_directory.is_dir():
            logger.warning(f"Direct normalizations directory not found: '{target_directory}'.")
            return

        yaml_files = list(target_directory.glob("*.yaml")) + list(target_directory.glob("*.yml"))
        for yaml_file in yaml_files:
            category = yaml_file.stem
            try:
                yaml_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
                category_map: dict[str, str] = {}
                for canonical_name, variants in yaml_data.items():
                    # Register canonical self-match
                    category_map[EDDNUtils.sanitize_normalize_edname(canonical_name)] = canonical_name

                    if isinstance(variants, list):
                        for variant in variants:
                            if variant is not None:
                                category_map[EDDNUtils.sanitize_normalize_edname(variant)] = canonical_name
                    elif isinstance(variants, str):
                        category_map[EDDNUtils.sanitize_normalize_edname(variants)] = canonical_name

                self.maps[category] = category_map
            except Exception as error:
                logger.error(f"Failed to load direct normalization file '{yaml_file}': {error}")

    def load_multifield_maps(self, directory: str | Path | None = None) -> None:
        """Loads multi-attribute entity definition YAML files into dynamically typed NamedTuple objects."""
        target_directory = Path(directory) if directory else self.multifield_dir
        if not target_directory.is_dir():
            logger.warning(f"Multifield normalizations directory not found: '{target_directory}'.")
            return

        yaml_files = list(target_directory.glob("*.yaml")) + list(target_directory.glob("*.yml"))
        for yaml_file in yaml_files:
            category = yaml_file.stem
            try:
                yaml_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
                if not isinstance(yaml_data, dict) or not yaml_data:
                    continue

                # 1. Discover all unique field names across records in this YAML file
                field_names: list[str] = []
                seen_fields: set[str] = set()
                for record_dict in yaml_data.values():
                    for field_key in record_dict:
                        if field_key not in seen_fields:
                            seen_fields.add(field_key)
                            field_names.append(field_key)

                if not field_names:
                    continue

                # 2. Build specialized NamedTuple class dynamically for this category schema
                class_name = "".join(part.capitalize() for part in category.split("_")) + "Record"
                record_class = collections.namedtuple(  # type: ignore[misc] # pyright: ignore[reportGeneralTypeIssues]
                    class_name,
                    field_names,
                    defaults=(None,) * len(field_names),
                )

                # 3. Populate category lookup store with clean normalized lookup keys
                category_store: dict[str, Any] = {}

                for raw_mapping_key, field_definitions in yaml_data.items():
                    normalized_lookup_key = EDDNUtils.sanitize_normalize_edname(raw_mapping_key)
                    record_instance = record_class(**{field_name: field_definitions.get(field_name) for field_name in field_names})
                    category_store[normalized_lookup_key] = record_instance

                self.multifield_maps[category] = category_store

            except Exception as error:
                logger.error(f"Failed to load multifield normalization file '{yaml_file}': {error}")

    def load_all(self) -> None:
        """Loads both direct single-value mapping files and multifield entity definitions."""
        self.maps.clear()
        self.multifield_maps.clear()
        self.load_direct_maps()
        self.load_multifield_maps()

    def get_multifield(self, category: str, raw_entity_name: str | None) -> Any | None:
        """Retrieves a typed multi-attribute NamedTuple record for any multifield category.

        Args:
            category: Multifield category name (e.g. 'scenarios', 'species').
            raw_entity_name: Raw or sanitized entity token/name string.

        Returns:
            NamedTuple | None: The matched NamedTuple record instance, or None if unmapped.
        """
        if not raw_entity_name:
            return None

        category_store = self.multifield_maps.get(category)
        if not category_store:
            return None

        normalized_lookup_key = EDDNUtils.sanitize_normalize_edname(raw_entity_name)
        return category_store.get(normalized_lookup_key)

    def normalize(
        self,
        table: str,
        field: str,
        category: str,
        raw_value: Any | None,
        metrics: Any | None = None,
    ) -> str | None:
        """Normalizes a raw value against the specified category mapping.

        If mapped: returns the canonical Title Case string.
        If unmapped: strips unusable wrappers (preserving original internal character casing and spacing),
        records the unmapped occurrence in metrics, and returns the sanitized value.

        Args:
            table: Target database table name for unmapped metric tracking.
            field: Target database column name for unmapped metric tracking.
            category: Normalization category name matching the YAML filename (e.g. 'economies').
            raw_value: Raw token string from the EDDN payload.
            metrics: Optional EDDNMetrics instance for recording unmapped tokens.

        Returns:
            str | None: Mapped canonical string, sanitized raw value if unmapped, or None if raw_value is None.
        """
        if raw_value is None:
            return None

        sanitized_token = EDDNUtils.sanitize_edname(raw_value)
        if not sanitized_token:
            return ""

        category_map = self.maps.get(category)
        if category_map:
            normalized_lookup_key = EDDNUtils.normalize_lookup_key(sanitized_token)
            canonical_name = category_map.get(normalized_lookup_key)
            if canonical_name is not None:
                return canonical_name

        # Fallback: unmapped value (record sanitized value in metrics preserving original casing and spacing)
        if metrics and hasattr(metrics, "record_unmapped"):
            metrics.record_unmapped(table, field, sanitized_token)

        return sanitized_token

    def resolve_scenario(
        self,
        raw_name: str | None,
        raw_type: str | None,
        localised_name: str | None = None,
        is_station: bool = False,
        metrics: Any | None = None,
    ) -> tuple[str, str, str | None]:
        """Resolves FSS scenario tokens into (display_name, signal_type, severity).

        Args:
            raw_name: Raw SignalName token (e.g. '$Warzone_PointRace_Low:#index=1;').
            raw_type: Raw SignalType string (e.g. 'Station', 'FleetCarrier', 'ResourceExtraction').
            localised_name: Localized name string if provided by Frontier.
            is_station: Boolean flag indicating if Frontier flagged the signal as a station.
            metrics: Optional EDDNMetrics instance for recording unmapped scenarios.

        Returns:
            tuple[str, str, str | None]: Tuple of (display_name, signal_type, severity).
        """
        if not raw_name or not raw_name.strip():
            return ("Unknown Signal", raw_type or "Unknown", None)

        raw_signal_token = raw_name.strip()
        sanitized_signal_name = EDDNUtils.sanitize_edname(raw_signal_token)
        display_name = localised_name.strip() if localised_name else sanitized_signal_name

        # 1. Check scenarios map directly using generic get_multifield
        scenario_record = self.get_multifield("scenarios", raw_signal_token)
        if scenario_record is not None:
            return (scenario_record[0], scenario_record[1], scenario_record[2])

        # 2. Dynamic Player Carrier Signals (Callsign parsing / carrier naming)
        carrier_id, carrier_name, carrier_type = EDDNUtils.extract_carrier_parts(raw_signal_token)
        if carrier_type is not None or raw_type in ("FleetCarrier", "SquadronCarrier"):
            signal_type = carrier_type or raw_type
            return (display_name, signal_type, None)

        # 3. Check declared station types and signal types from YAML mappings
        if raw_type:
            normalized_type = self.maps.get("station_types", {}).get(
                EDDNUtils.sanitize_normalize_edname(raw_type)
            ) or self.maps.get("signal_types", {}).get(EDDNUtils.sanitize_normalize_edname(raw_type))
            if normalized_type:
                return (display_name, normalized_type, None)

        # 4. If is_station flag is True (dockable station with unclassified type)
        if is_station:
            return (display_name, raw_type or "Station", None)

        # 5. Dynamic Planetary Surface POI Scenes (procedural client-side surface POI spawns)
        if sanitized_signal_name.startswith("POIScene_"):
            return (localised_name.strip() if localised_name else "Surface Point of Interest", "GenericPOI", None)

        # 6. Fallback: only record unmapped metric for Frontier game tokens (starting with $)
        if raw_signal_token.startswith("$") and metrics and hasattr(metrics, "record_unmapped"):
            metrics.record_unmapped("system_signals", "raw_name", sanitized_signal_name)

        return (display_name, raw_type or "GenericPOI", None)

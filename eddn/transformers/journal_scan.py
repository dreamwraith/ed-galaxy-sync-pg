"""Transformer for EDDN journal scanning and scientific exploration events."""

import json
import math
from typing import Any

from ..normalizers import NormalizerManager
from ..utils import EDDNUtils
from .base import BaseTransformer, TransformedRecord


class JournalScanTransformer(BaseTransformer):
    """Transforms EDDN journal scanning and scientific exploration events.

    Handles celestial body Scans, SAASignalsFound, FSSBodySignals, ScanOrganic,
    and CodexEntry events for `bodies`, `body_rings`, `body_belts`, `body_signals`,
    and `system_signals` tables.
    """

    def __init__(self, normalizer: NormalizerManager | None = None, metrics: Any | None = None) -> None:
        """Initializes JournalScanTransformer.

        Args:
            normalizer: Optional NormalizerManager instance for celestial and scientific normalization.
            metrics: Optional EDDNMetrics instance for recording unmapped tokens.
        """
        self.normalizer = normalizer or NormalizerManager()
        self.metrics = metrics

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Checks if this transformer can handle the scan or exploration event."""
        schema_lower = schema_ref.lower()
        if any(s in schema_lower for s in ("journal", "scan", "fssbodysignals", "scanorganic", "codexentry", "saasignalsfound")):
            return True
        return message.get("event") in {"Scan", "SAASignalsFound", "FSSBodySignals", "ScanOrganic", "CodexEntry"}

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms exploration and scanning events into celestial and signal records."""
        records: list[TransformedRecord] = []
        event = message.get("event")
        timestamp = message.get("timestamp")
        system_id64_raw = message.get("SystemAddress")

        if not system_id64_raw:
            return records

        try:
            system_id64 = int(system_id64_raw)
        except ValueError, TypeError:
            return records

        body_id_raw = message.get("BodyID") or message.get("Body")
        try:
            body_id = int(body_id_raw) if body_id_raw is not None else None
        except ValueError, TypeError:
            body_id = None

        body_id64 = EDDNUtils.compute_body_id64(system_id64, body_id_raw)

        match event:
            case "Scan":
                # 1. bodies record
                star_type = message.get("StarType")
                planet_class = message.get("PlanetClass")
                body_type = "Star" if star_type else ("Planet" if planet_class else None)
                if star_type:
                    sub_type = self.normalizer.normalize("bodies", "subType", "star_types", star_type, metrics=self.metrics)
                elif planet_class:
                    sub_type = self.normalizer.normalize("bodies", "subType", "planet_classes", planet_class, metrics=self.metrics)
                else:
                    sub_type = None

                normalized_terraform_state = (
                    self.normalizer.normalize(
                        "bodies", "terraformingState", "terraform_states", message.get("TerraformState"), metrics=self.metrics
                    )
                    if message.get("TerraformState")
                    else None
                )

                normalized_reserve_level = (
                    self.normalizer.normalize(
                        "bodies", "reserveLevel", "reserve_levels", message.get("ReserveLevel"), metrics=self.metrics
                    )
                    if message.get("ReserveLevel")
                    else None
                )

                materials = message.get("Materials")
                materials_json = json.dumps(materials) if materials is not None else None

                atmosphere_composition = message.get("AtmosphereComposition")
                atmosphere_composition_json = json.dumps(atmosphere_composition) if atmosphere_composition is not None else None

                solid_composition = message.get("Composition")
                solid_composition_json = json.dumps(solid_composition) if solid_composition is not None else None

                parents = message.get("Parents")
                parents_json = json.dumps(parents) if parents is not None else None

                body_data = {
                    "system_id64": system_id64,
                    "id64": body_id64,
                    "bodyId": body_id,
                    "name": message.get("BodyName"),
                    "type": body_type,
                    "subType": sub_type,
                    "distanceToArrival": message.get("DistanceFromArrivalLS"),
                    "orbitalPeriod": (message.get("OrbitalPeriod") / 86400.0) if message.get("OrbitalPeriod") is not None else None,
                    "semiMajorAxis": (message.get("SemiMajorAxis") / 1000.0) if message.get("SemiMajorAxis") is not None else None,
                    "orbitalEccentricity": message.get("Eccentricity"),
                    "orbitalInclination": message.get("OrbitalInclination"),
                    "argOfPeriapsis": message.get("Periapsis"),
                    "meanAnomaly": message.get("MeanAnomaly"),
                    "ascendingNode": message.get("AscendingNode"),
                    "rotationalPeriod": (message.get("RotationPeriod") / 86400.0)
                    if message.get("RotationPeriod") is not None
                    else None,
                    "rotationalPeriodTidallyLocked": message.get("TidalLock"),
                    "axialTilt": message.get("AxialTilt"),
                    "surfaceTemperature": message.get("SurfaceTemperature"),
                    "radius": (message.get("Radius") / 1000.0) if message.get("Radius") is not None else None,
                    "isLandable": message.get("Landable"),
                    "gravity": (message.get("SurfaceGravity") / 9.80665) if message.get("SurfaceGravity") is not None else None,
                    "earthMasses": message.get("MassEM"),
                    "surfacePressure": (message.get("SurfacePressure") / 101325.0)
                    if message.get("SurfacePressure") is not None
                    else None,
                    "volcanismType": message.get("Volcanism"),
                    "atmosphereType": message.get("AtmosphereType") or message.get("Atmosphere"),
                    "terraformingState": normalized_terraform_state,
                    "reserveLevel": normalized_reserve_level,
                    "mainStar": message.get("MainStar"),
                    "age": message.get("Age_MY"),
                    "spectralClass": message.get("SpectralClass"),
                    "luminosity": message.get("Luminosity"),
                    "absoluteMagnitude": message.get("AbsoluteMagnitude"),
                    "solarMasses": message.get("StellarMass"),
                    "solarRadius": message.get("Radius") / 695700000.0 if (star_type and message.get("Radius")) else None,
                    "atmosphereComposition": atmosphere_composition_json,
                    "solidComposition": solid_composition_json,
                    "materials": materials_json,
                    "parents": parents_json,
                    "update_dtm": timestamp,
                }

                records.append(
                    TransformedRecord(
                        table_name="bodies",
                        data=body_data,
                        key_fields=("id64",),
                        timestamp_field="update_dtm",
                    )
                )

                # 2. body_rings records
                rings = message.get("Rings")
                if isinstance(rings, list):
                    for ring in rings:
                        ring_name = ring.get("Name")
                        if not ring_name:
                            continue

                        # Filter out belt clusters if marked as belt in name
                        if "Belt" in ring_name and "Ring" not in ring_name:
                            # 3. body_belts
                            inner_radius = float(ring.get("InnerRad", 0.0))
                            outer_radius = float(ring.get("OuterRad", 0.0))
                            mass_megatons = float(ring.get("MassMT", 0.0))
                            area = abs(math.pi * (outer_radius**2) - math.pi * (inner_radius**2))
                            density = (mass_megatons / area) if area > 0 else None

                            raw_ring_class = ring.get("RingClass")
                            ring_type = self.normalizer.normalize(
                                "body_belts", "type", "ring_types", raw_ring_class, metrics=self.metrics
                            )

                            belt_data = {
                                "body_id64": body_id64,
                                "name": ring_name,
                                "type": ring_type,
                                "mass": mass_megatons,
                                "innerRadius": inner_radius,
                                "outerRadius": outer_radius,
                                "density": density,
                                "update_dtm": timestamp,
                            }
                            records.append(
                                TransformedRecord(
                                    table_name="body_belts",
                                    data=belt_data,
                                    key_fields=("body_id64", "name"),
                                    timestamp_field="update_dtm",
                                )
                            )
                        else:
                            inner_radius = float(ring.get("InnerRad", 0.0))
                            outer_radius = float(ring.get("OuterRad", 0.0))
                            mass_megatons = float(ring.get("MassMT", 0.0))
                            area = abs(math.pi * (outer_radius**2) - math.pi * (inner_radius**2))
                            density = (mass_megatons / area) if area > 0 else None

                            raw_ring_class = ring.get("RingClass")
                            ring_type = self.normalizer.normalize(
                                "body_rings", "type", "ring_types", raw_ring_class, metrics=self.metrics
                            )

                            ring_data = {
                                "body_id64": body_id64,
                                "id64": None,
                                "name": ring_name,
                                "type": ring_type,
                                "mass": mass_megatons,
                                "innerRadius": inner_radius,
                                "outerRadius": outer_radius,
                                "density": density,
                                "signals": None,
                                "update_dtm": timestamp,
                            }
                            records.append(
                                TransformedRecord(
                                    table_name="body_rings",
                                    data=ring_data,
                                    key_fields=("body_id64", "name"),
                                    timestamp_field="update_dtm",
                                )
                            )

            case "SAASignalsFound" | "FSSBodySignals":
                # Exobiology signals and hotspots from DSS surface scan or FSS body zoom
                body_name = message.get("BodyName") or message.get("Body") or ""
                raw_signals = message.get("Signals") if isinstance(message.get("Signals"), list) else []

                # 1. Ring Hotspots (DSS scan on a ring, e.g. "Sol 3 A Ring")
                if event == "SAASignalsFound" and body_name.endswith(" Ring") and body_id64:
                    signals_dict: dict[str, int] = {}

                    for s in raw_signals:
                        if not isinstance(s, dict):
                            continue
                        raw_type = s.get("Type", "")
                        count = s.get("Count", 1)

                        # Normalize commodity hotspot name
                        name = self.normalizer.normalize("body_rings", "signals", "commodities", raw_type, metrics=self.metrics)
                        if not name or name == EDDNUtils.sanitize_edname(raw_type):
                            scenario = self.normalizer.get_multifield("scenarios", raw_type)
                            if scenario and getattr(scenario, "name", None):
                                name = scenario.name
                        if not name:
                            name = EDDNUtils.sanitize_edname(raw_type)
                            if self.metrics and hasattr(self.metrics, "record_unmapped"):
                                self.metrics.record_unmapped("body_rings", "signals", name)

                        signals_dict[name] = count

                    ring_data = {
                        "body_id64": body_id64,
                        "id64": None,
                        "name": body_name,
                        "type": "Unknown",
                        "mass": 0.0,
                        "innerRadius": 0.0,
                        "outerRadius": 0.0,
                        "density": None,
                        "signals": json.dumps(signals_dict) if signals_dict else None,
                        "update_dtm": timestamp,
                    }

                    records.append(
                        TransformedRecord(
                            table_name="body_rings",
                            data=ring_data,
                            key_fields=("body_id64", "name"),
                            timestamp_field="update_dtm",
                        )
                    )
                    return records

                # 2. Planetary Surface Signals (FSS zoom or DSS surface scan on planets/moons)
                genuses = message.get("Genuses")
                genus_list: list[str] = []
                if isinstance(genuses, list):
                    for g in genuses:
                        raw_g = g.get("Genus", "") if isinstance(g, dict) else g
                        local_g = g.get("Genus_Localised") if isinstance(g, dict) else None
                        norm_g = local_g or self.normalizer.normalize(
                            "body_signals", "genuses", "genuses", raw_g, metrics=self.metrics
                        )
                        if norm_g:
                            genus_list.append(norm_g)

                signals_dict = {}
                for s in raw_signals:
                    if isinstance(s, dict):
                        raw_type = s.get("Type", "")
                        count = s.get("Count", 1)
                        clean_type = EDDNUtils.sanitize_edname(raw_type)
                        signals_dict[clean_type] = count

                signal_record_data = {
                    "system_id64": system_id64,
                    "body_id64": body_id64,
                    "signals": json.dumps(signals_dict) if signals_dict else None,
                    "genuses": genus_list if genus_list else None,
                    "update_dtm": timestamp,
                }
                records.append(
                    TransformedRecord(
                        table_name="body_signals",
                        data=signal_record_data,
                        key_fields=("body_id64",),
                        timestamp_field="update_dtm",
                    )
                )

            case "ScanOrganic":
                # Odyssey on-foot exobiology sampling
                raw_genus = message.get("Genus")
                normalized_genus = (
                    self.normalizer.normalize("body_signals", "genuses", "genuses", raw_genus, metrics=self.metrics)
                    if raw_genus
                    else None
                )
                genus = message.get("Genus_Localised") or normalized_genus or raw_genus
                genus_list = [genus] if genus else None

                if genus_list and body_id64:
                    signal_record_data = {
                        "system_id64": system_id64,
                        "body_id64": body_id64,
                        "signals": None,
                        "genuses": genus_list,
                        "update_dtm": timestamp,
                    }
                    records.append(
                        TransformedRecord(
                            table_name="body_signals",
                            data=signal_record_data,
                            key_fields=("body_id64",),
                            timestamp_field="update_dtm",
                        )
                    )

            case "CodexEntry":
                # Biological flora and space phenomena
                category = message.get("Category", "")
                sub_category = message.get("SubCategory", "")

                # 1. Biological Exobiology Flora (confirms confirmed genus in body_signals.genuses on parent body)
                nearest_dest = str(message.get("NearestDestination") or "")
                has_surface_coords = message.get("Latitude") is not None and message.get("Longitude") is not None
                is_space_cloud = (
                    "Life_Cloud" in nearest_dest or "Lagrange" in nearest_dest or "Lagrange" in str(message.get("Name"))
                )

                is_biology = (
                    ("Biology" in category or "Organics" in sub_category or message.get("Genus") is not None)
                    and "Geology" not in sub_category
                    and (has_surface_coords or "Organic_Structures" not in sub_category)
                    and not is_space_cloud
                )
                if is_biology and body_id64:
                    raw_genus = message.get("Genus") or message.get("Name")
                    normalized_genus = self.normalizer.normalize(
                        "body_signals", "genuses", "genuses", raw_genus, metrics=self.metrics
                    )
                    display_name = normalized_genus or message.get("Genus_Localised") or message.get("Name_Localised") or raw_genus
                    if display_name:
                        signal_record_data = {
                            "system_id64": system_id64,
                            "body_id64": body_id64,
                            "signals": None,
                            "genuses": [display_name],
                            "update_dtm": timestamp,
                        }
                        records.append(
                            TransformedRecord(
                                table_name="body_signals",
                                data=signal_record_data,
                                key_fields=("body_id64",),
                                timestamp_field="update_dtm",
                            )
                        )
                    return records

                # 2. Space-based Notable Stellar Phenomena (Lagrange clouds, space storms, space organisms, space crystals)
                is_space_phenomena = (
                    "Phenomena" in category
                    or "Storms" in sub_category
                    or is_space_cloud
                    or ("Organic_Structures" in sub_category and not has_surface_coords)
                )
                if is_space_phenomena:
                    raw_name = message.get("Name") or "Notable Stellar Phenomena"
                    display_name = (
                        message.get("Name_Localised") or EDDNUtils.sanitize_edname(raw_name) or "Notable Stellar Phenomena"
                    )
                    signal_type = "Notable Stellar Phenomena"

                    system_signal_record_data = {
                        "system_id64": system_id64,
                        "signal_type": signal_type,
                        "name": display_name,
                        "raw_name": raw_name,
                        "severity": None,
                        "threat_level": None,
                        "spawning_faction": None,
                        "spawning_state": None,
                        "is_station": False,
                        "update_dtm": timestamp,
                    }
                    records.append(
                        TransformedRecord(
                            table_name="system_signals",
                            data=system_signal_record_data,
                            key_fields=("system_id64", "raw_name"),
                            timestamp_field="update_dtm",
                        )
                    )
                    return records

                # All other personal discoveries (planetary bodies, sub-object data logs, obelisks, combat interceptors)
                # are personal logbook scans and not persistent galaxy entities/POIs.
                return records

        return records

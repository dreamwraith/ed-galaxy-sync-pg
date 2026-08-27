"""Transformer for EDDN journal station events (Docked, ApproachSettlement)."""

import json
from typing import Any

from ..normalizers import NormalizerManager
from ..utils import EDDNUtils
from .base import BaseTransformer, TransformedRecord


class JournalStationTransformer(BaseTransformer):
    """Transforms EDDN journal events (Docked, ApproachSettlement).

    Routes market-equipped ports, starports, outposts, and fleet carriers to `stations`,
    and non-market surface settlements, ruins, and sites to `body_pois`.
    """

    def __init__(self, normalizer: NormalizerManager | None = None, metrics: Any | None = None) -> None:
        """Initializes JournalStationTransformer.

        Args:
            normalizer: Optional NormalizerManager instance for station and POI normalization.
            metrics: Optional EDDNMetrics instance for recording unmapped tokens.
        """
        self.normalizer = normalizer or NormalizerManager()
        self.metrics = metrics

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Checks if this transformer can handle the Docked or ApproachSettlement event."""
        schema_lower = schema_ref.lower()
        if "journal" in schema_lower or "approachsettlement" in schema_lower or "docked" in schema_lower:
            return True
        return message.get("event") in {"Docked", "ApproachSettlement"}

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms docking and settlement approach events into station or POI records."""
        records: list[TransformedRecord] = []
        system_id64_raw = message.get("SystemAddress")
        raw_station_name = message.get("StationName") or message.get("Name")
        station_name = EDDNUtils.sanitize_station_name(raw_station_name)

        if not system_id64_raw or not station_name:
            return records

        try:
            system_id64 = int(system_id64_raw)
            if system_id64 <= 1:
                return records
        except ValueError, TypeError:
            return records

        market_id_raw = message.get("MarketID") or message.get("marketId")
        body_id_raw = message.get("BodyID") or message.get("Body")
        timestamp = message.get("timestamp")

        # 1. Market-equipped station / port / settlement -> stations table
        if market_id_raw is not None:
            try:
                market_id = int(market_id_raw)
                if market_id <= 0:
                    market_id = None
            except ValueError, TypeError:
                market_id = None

            if market_id is not None:
                try:
                    body_source_id64 = int(body_id_raw) if body_id_raw is not None else None
                except ValueError, TypeError:
                    body_source_id64 = None

                landing_pads = message.get("LandingPads", {}) or {}
                pad_large = landing_pads.get("Large")
                pad_medium = landing_pads.get("Medium")
                pad_small = landing_pads.get("Small")

                controlling_faction_dict = message.get("StationFaction")
                controlling_faction = None
                controlling_faction_state = None
                if isinstance(controlling_faction_dict, dict):
                    controlling_faction = controlling_faction_dict.get("Name")
                    controlling_faction_state = controlling_faction_dict.get("FactionState")
                elif isinstance(controlling_faction_dict, str):
                    controlling_faction = controlling_faction_dict

                economies = message.get("StationEconomies")
                economies_json = json.dumps(economies) if economies is not None else None

                raw_primary_economy = message.get("StationEconomy")
                primary_economy = self.normalizer.normalize(
                    "stations", "primaryEconomy", "economies", raw_primary_economy, metrics=self.metrics
                )

                raw_secondary_economy = None
                if isinstance(economies, list) and len(economies) >= 2:
                    secondary_economy_item = economies[1]
                    if isinstance(secondary_economy_item, dict):
                        raw_secondary_economy = secondary_economy_item.get("Name")

                secondary_economy = (
                    self.normalizer.normalize(
                        "stations", "secondaryEconomy", "economies", raw_secondary_economy, metrics=self.metrics
                    )
                    if raw_secondary_economy
                    else None
                )

                raw_station_type = message.get("StationType")
                normalized_station_type = self.normalizer.normalize(
                    "stations", "type", "station_types", raw_station_type, metrics=self.metrics
                )

                raw_allegiance = message.get("StationAllegiance")
                normalized_allegiance = self.normalizer.normalize(
                    "stations", "allegiance", "allegiances", raw_allegiance, metrics=self.metrics
                )

                raw_government = message.get("StationGovernment")
                normalized_government = self.normalizer.normalize(
                    "stations", "government", "governments", raw_government, metrics=self.metrics
                )

                carrier_name = message.get("CarrierName") or message.get("carrierName")

                services = message.get("StationServices")
                services_arr = services if isinstance(services, list) else None

                raw_station_state = message.get("StationState") or controlling_faction_state
                normalized_station_state = (
                    self.normalizer.normalize("stations", "state", "faction_states", raw_station_state, metrics=self.metrics)
                    if raw_station_state
                    else None
                )

                normalized_faction_state = (
                    self.normalizer.normalize(
                        "stations", "controllingFactionState", "faction_states", controlling_faction_state, metrics=self.metrics
                    )
                    if controlling_faction_state
                    else None
                )

                raw_docking_access = message.get("CarrierDockingAccess") or message.get("DockingAccess")
                normalized_docking_access = (
                    self.normalizer.normalize(
                        "stations", "carrierDockingAccess", "carrier_docking_access", raw_docking_access, metrics=self.metrics
                    )
                    if raw_docking_access
                    else None
                )

                station_data = {
                    "source": "eddn",
                    "system_id64": system_id64,
                    "body_source_id64": body_source_id64,
                    "market_id": market_id,
                    "name": station_name,
                    "realName": station_name,
                    "carrierName": carrier_name,
                    "type": normalized_station_type,
                    "state": normalized_station_state,
                    "distanceToArrival": message.get("DistFromStarLS"),
                    "latitude": message.get("Latitude"),
                    "longitude": message.get("Longitude"),
                    "allegiance": normalized_allegiance,
                    "government": normalized_government,
                    "controllingFaction": controlling_faction,
                    "controllingFactionState": normalized_faction_state,
                    "primaryEconomy": primary_economy,
                    "secondaryEconomy": secondary_economy,
                    "economies": economies_json,
                    "carrierDockingAccess": normalized_docking_access,
                    "pad_large": pad_large,
                    "pad_medium": pad_medium,
                    "pad_small": pad_small,
                    "services_arr": services_arr,
                    "update_dtm": timestamp,
                }

                records.append(
                    TransformedRecord(
                        table_name="stations",
                        data=station_data,
                        key_fields=("market_id",),
                        timestamp_field="update_dtm",
                    )
                )
                return records

        # 2. Non-market surface location / POI (Guardian ruin, Thargoid site, settlement without market) -> body_pois table
        body_id64 = EDDNUtils.compute_body_id64(system_id64, body_id_raw)
        raw_name = (message.get("Name") or message.get("StationName") or raw_station_name or "").strip()
        localised = message.get("Name_Localised") or message.get("StationName_Localised")
        clean_name = EDDNUtils.sanitize_station_name(localised or raw_name)
        display_name = clean_name or "Unknown POI"
        raw_station_type = message.get("StationType")
        if raw_station_type:
            normalized_poi_type = self.normalizer.normalize(
                "body_pois", "poi_type", "poi_types", raw_station_type, metrics=self.metrics
            )
            poi_type = (
                normalized_poi_type
                if normalized_poi_type and normalized_poi_type != EDDNUtils.sanitize_edname(raw_station_type)
                else "Settlement"
            )
        elif raw_name.startswith("$") or "Ancient" in raw_name or "Thargoid" in raw_name:
            normalized_poi_type = self.normalizer.normalize("body_pois", "poi_type", "poi_types", raw_name, metrics=self.metrics)
            poi_type = (
                normalized_poi_type
                if normalized_poi_type and normalized_poi_type != EDDNUtils.sanitize_edname(raw_name)
                else "Settlement"
            )
        else:
            poi_type = "Settlement"

        poi_data = {
            "system_id64": system_id64,
            "body_id64": body_id64,
            "body_name": message.get("BodyName"),
            "poi_type": poi_type,
            "name": display_name,
            "raw_name": raw_name,
            "latitude": message.get("Latitude"),
            "longitude": message.get("Longitude"),
            "update_dtm": timestamp,
        }

        records.append(
            TransformedRecord(
                table_name="body_pois",
                data=poi_data,
                key_fields=("body_id64", "raw_name"),
                timestamp_field="update_dtm",
            )
        )

        return records

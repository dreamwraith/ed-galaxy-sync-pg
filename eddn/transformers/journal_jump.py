"""Transformer for EDDN journal navigation events (FSDJump, Location, CarrierJump)."""

import json
from typing import Any

from ..normalizers import NormalizerManager
from .base import BaseTransformer, TransformedRecord


class JournalJumpTransformer(BaseTransformer):
    """Transforms EDDN journal navigation events into systems and system_factions records.

    Handles FSDJump, Location, CarrierJump, and FSSDiscoveryScan events.
    """

    def __init__(self, normalizer: NormalizerManager | None = None, metrics: Any | None = None) -> None:
        """Initializes JournalJumpTransformer.

        Args:
            normalizer: Optional NormalizerManager instance for allegiances, economies, and securities.
            metrics: Optional EDDNMetrics instance for recording unmapped tokens.
        """
        self.normalizer = normalizer or NormalizerManager()
        self.metrics = metrics

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Checks if this transformer can handle the jump/location event."""
        schema_lower = schema_ref.lower()
        if any(s in schema_lower for s in ("journal", "fsdjump", "location", "carrierjump", "fssdiscoveryscan")):
            return True
        return message.get("event") in {"FSDJump", "Location", "CarrierJump", "FSSDiscoveryScan"}

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms navigation journal payloads into systems and faction records."""
        records: list[TransformedRecord] = []

        system_id64_raw = message.get("SystemAddress")
        if not system_id64_raw:
            return records

        try:
            system_id64 = int(system_id64_raw)
        except ValueError, TypeError:
            return records

        event = message.get("event")
        timestamp = message.get("timestamp")

        if event == "FSSDiscoveryScan":
            body_count = message.get("BodyCount")
            if body_count is not None:
                system_record_data = {
                    "id64": system_id64,
                    "name": message.get("SystemName") or message.get("StarSystem"),
                    "bodyCount": body_count,
                    "update_dtm": timestamp,
                }
                records.append(
                    TransformedRecord(
                        table_name="systems",
                        data=system_record_data,
                        key_fields=("id64",),
                        timestamp_field="update_dtm",
                    )
                )
            return records

        system_name = message.get("StarSystem")
        star_pos = message.get("StarPos")
        coords = None
        if isinstance(star_pos, (list, tuple)) and len(star_pos) == 3:
            coords = f"({star_pos[0]}, {star_pos[1]}, {star_pos[2]})"

        # 1. systems record
        powers = message.get("Powers")
        powers_json = json.dumps(powers) if powers is not None else None

        controlling_faction = message.get("SystemFaction")
        controlling_faction_json = json.dumps(controlling_faction) if controlling_faction is not None else None

        thargoid_war = message.get("ThargoidWar")
        thargoid_war_json = json.dumps(thargoid_war) if thargoid_war is not None else None

        raw_allegiance = message.get("SystemAllegiance")
        normalized_allegiance = self.normalizer.normalize(
            "systems", "allegiance", "allegiances", raw_allegiance, metrics=self.metrics
        )

        raw_government = message.get("SystemGovernment")
        normalized_government = self.normalizer.normalize(
            "systems", "government", "governments", raw_government, metrics=self.metrics
        )

        raw_primary_economy = message.get("SystemEconomy")
        normalized_primary_economy = self.normalizer.normalize(
            "systems", "primaryEconomy", "economies", raw_primary_economy, metrics=self.metrics
        )

        raw_secondary_economy = message.get("SystemSecondEconomy")
        normalized_secondary_economy = self.normalizer.normalize(
            "systems", "secondaryEconomy", "economies", raw_secondary_economy, metrics=self.metrics
        )

        raw_security = message.get("SystemSecurity")
        normalized_security = self.normalizer.normalize("systems", "security", "securities", raw_security, metrics=self.metrics)

        system_record_data = {
            "id64": system_id64,
            "name": system_name,
            "coords": coords,
            "allegiance": normalized_allegiance,
            "government": normalized_government,
            "primaryEconomy": normalized_primary_economy,
            "secondaryEconomy": normalized_secondary_economy,
            "security": normalized_security,
            "population": message.get("Population"),
            "bodyCount": message.get("BodyCount"),
            "controllingPower": message.get("ControllingPower"),
            "powerState": message.get("PowerplayState"),
            "powerStateControlProgress": message.get("PowerplayStateControlProgress"),
            "powerStateReinforcement": message.get("PowerplayStateReinforcement"),
            "powerStateUndermining": message.get("PowerplayStateUndermining"),
            "powers": powers_json,
            "controllingFaction": controlling_faction_json,
            "thargoidWar": thargoid_war_json,
            "update_dtm": timestamp,
        }

        records.append(
            TransformedRecord(
                table_name="systems",
                data=system_record_data,
                key_fields=("id64",),
                timestamp_field="update_dtm",
            )
        )

        # 2. system_factions records
        factions = message.get("Factions")
        if isinstance(factions, list):
            for faction_entry in factions:
                faction_name = faction_entry.get("Name")
                if not faction_name:
                    continue

                active_states = faction_entry.get("ActiveStates")
                pending_states = faction_entry.get("PendingStates")
                recovering_states = faction_entry.get("RecoveringStates")

                raw_faction_allegiance = faction_entry.get("Allegiance")
                normalized_faction_allegiance = self.normalizer.normalize(
                    "system_factions", "allegiance", "allegiances", raw_faction_allegiance, metrics=self.metrics
                )

                raw_faction_government = faction_entry.get("Government")
                normalized_faction_government = self.normalizer.normalize(
                    "system_factions", "government", "governments", raw_faction_government, metrics=self.metrics
                )

                raw_faction_state = faction_entry.get("FactionState")
                normalized_faction_state = (
                    self.normalizer.normalize("system_factions", "state", "faction_states", raw_faction_state, metrics=self.metrics)
                    if raw_faction_state
                    else None
                )

                faction_record_data = {
                    "system_id64": system_id64,
                    "name": faction_name,
                    "state": normalized_faction_state,
                    "allegiance": normalized_faction_allegiance,
                    "government": normalized_faction_government,
                    "influence": faction_entry.get("Influence"),
                    "activeStates": json.dumps(active_states) if active_states is not None else None,
                    "pendingStates": json.dumps(pending_states) if pending_states is not None else None,
                    "recoveringStates": json.dumps(recovering_states) if recovering_states is not None else None,
                    "update_dtm": timestamp,
                }

                records.append(
                    TransformedRecord(
                        table_name="system_factions",
                        data=faction_record_data,
                        key_fields=("system_id64", "name"),
                        timestamp_field="update_dtm",
                    )
                )

        # 3. If CarrierJump, also emit a stations record for the fleet carrier
        if event == "CarrierJump":
            market_id_raw = message.get("MarketID") or message.get("marketId")
            if market_id_raw:
                try:
                    market_id = int(market_id_raw)
                except ValueError, TypeError:
                    market_id = None

                if market_id:
                    station_name = message.get("StationName") or message.get("Name") or "Fleet Carrier"
                    carrier_name = message.get("CarrierName") or message.get("carrierName")
                    body_id_raw = message.get("BodyID") or message.get("Body")
                    try:
                        body_source_id64 = int(body_id_raw) if body_id_raw is not None else None
                    except ValueError, TypeError:
                        body_source_id64 = None

                    landing_pads = message.get("LandingPads", {}) or {}
                    pad_large = landing_pads.get("Large")
                    pad_medium = landing_pads.get("Medium")
                    pad_small = landing_pads.get("Small")

                    economies = message.get("StationEconomies")
                    economies_json = json.dumps(economies) if economies is not None else None

                    raw_primary_economy = message.get("StationEconomy")
                    primary_economy = self.normalizer.normalize(
                        "stations", "primaryEconomy", "economies", raw_primary_economy, metrics=self.metrics
                    )

                    secondary_economy = None
                    if isinstance(economies, list) and len(economies) >= 2:
                        secondary_economy_item = economies[1]
                        if isinstance(secondary_economy_item, dict):
                            raw_secondary_economy = secondary_economy_item.get("Name")
                            secondary_economy = self.normalizer.normalize(
                                "stations", "secondaryEconomy", "economies", raw_secondary_economy, metrics=self.metrics
                            )

                    services = message.get("StationServices")
                    services_arr = services if isinstance(services, list) else None

                    raw_carrier_type = message.get("StationType") or "Fleet Carrier"
                    normalized_carrier_type = self.normalizer.normalize(
                        "stations", "type", "station_types", raw_carrier_type, metrics=self.metrics
                    )

                    raw_docking_access = message.get("CarrierDockingAccess") or message.get("DockingAccess")
                    normalized_docking_access = (
                        self.normalizer.normalize(
                            "stations", "carrierDockingAccess", "carrier_docking_access", raw_docking_access, metrics=self.metrics
                        )
                        if raw_docking_access
                        else None
                    )

                    station_record_data = {
                        "source": "eddn",
                        "system_id64": system_id64,
                        "body_source_id64": body_source_id64,
                        "market_id": market_id,
                        "name": station_name,
                        "realName": station_name,
                        "carrierName": carrier_name,
                        "type": normalized_carrier_type,
                        "distanceToArrival": message.get("DistFromStarLS"),
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
                            data=station_record_data,
                            key_fields=("market_id",),
                            timestamp_field="update_dtm",
                        )
                    )

        return records

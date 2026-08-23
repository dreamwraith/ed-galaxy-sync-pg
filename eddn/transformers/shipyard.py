"""Transformer for EDDN shipyard and outfitting schema messages."""

from typing import Any

from ..normalizers import NormalizerManager
from ..utils import EDDNUtils
from .base import BaseTransformer, TransformedRecord


class ShipyardTransformer(BaseTransformer):
    """Transforms EDDN shipyard and outfitting messages into station_ships and station_modules records.

    Also emits timestamp updates to `stations.shipyard_updated_at` and `stations.outfitting_updated_at`
    to trigger stale stock cleanup.
    """

    def __init__(self, normalizer: NormalizerManager | None = None, metrics: Any | None = None) -> None:
        """Initializes ShipyardTransformer.

        Args:
            normalizer: Optional NormalizerManager instance for ship, module, and category normalization.
            metrics: Optional EDDNMetrics instance for recording unmapped tokens.
        """
        self.normalizer = normalizer or NormalizerManager()
        self.metrics = metrics

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Checks if this transformer can handle shipyard or outfitting schemas."""
        return "shipyard" in schema_ref or "outfitting" in schema_ref

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms shipyard/outfitting payloads into ship/module and station records."""
        records: list[TransformedRecord] = []
        market_id_raw = message.get("marketId") or message.get("MarketID")
        if not market_id_raw:
            return records

        try:
            market_id = int(market_id_raw)
        except ValueError, TypeError:
            return records

        timestamp = message.get("timestamp")
        station_name = message.get("stationName") or message.get("StationName")

        station_display_name = station_name or "Unknown Station"

        if "shipyard" in schema_ref:
            # 1. Emit stations update record to track shipyard_updated_at
            station_record_data = {
                "market_id": market_id,
                "system_id64": 0,
                "name": station_display_name,
                "realName": station_display_name,
                "shipyard_updated_at": timestamp,
                "update_dtm": timestamp,
            }

            records.append(
                TransformedRecord(
                    table_name="stations",
                    data=station_record_data,
                    key_fields=("market_id",),
                    timestamp_field="shipyard_updated_at",
                )
            )

            # 2. Extract ships
            ships = message.get("ships") or message.get("Ships") or message.get("prices")
            if isinstance(ships, list):
                for ship_entry in ships:
                    if isinstance(ship_entry, dict):
                        ship_name = ship_entry.get("name") or ship_entry.get("Name")
                        ship_symbol = ship_entry.get("symbol") or ship_name or ""
                        raw_ship_id = ship_entry.get("shipId") or ship_entry.get("id")
                    elif isinstance(ship_entry, str):
                        ship_name = ship_entry
                        ship_symbol = ship_entry
                        raw_ship_id = None
                    else:
                        continue

                    normalized_ship_name = ship_name
                    if ship_name:
                        normalized_ship_name = self.normalizer.normalize(
                            "station_ships", "name", "ships", ship_name, metrics=self.metrics
                        )

                    ship_id = EDDNUtils.get_entity_id(raw_ship_id, ship_symbol)
                    ship_record_data = {
                        "market_id": market_id,
                        "name": normalized_ship_name,
                        "symbol": ship_symbol,
                        "shipId": ship_id,
                        "update_dtm": timestamp,
                    }
                    records.append(
                        TransformedRecord(
                            table_name="station_ships",
                            data=ship_record_data,
                            key_fields=("market_id", "shipId"),
                            timestamp_field="update_dtm",
                        )
                    )

        elif "outfitting" in schema_ref:
            # 1. Emit stations update record to track outfitting_updated_at
            station_record_data = {
                "market_id": market_id,
                "system_id64": 0,
                "name": station_display_name,
                "realName": station_display_name,
                "outfitting_updated_at": timestamp,
                "update_dtm": timestamp,
            }

            records.append(
                TransformedRecord(
                    table_name="stations",
                    data=station_record_data,
                    key_fields=("market_id",),
                    timestamp_field="outfitting_updated_at",
                )
            )

            # 2. Extract modules
            modules = message.get("modules") or message.get("Modules") or message.get("items")
            if isinstance(modules, list):
                for module_entry in modules:
                    if isinstance(module_entry, dict):
                        module_symbol = module_entry.get("symbol") or module_entry.get("name") or ""
                        module_name = module_entry.get("name") or module_symbol
                        raw_module_id = module_entry.get("moduleId") or module_entry.get("id")
                        module_category = module_entry.get("category")
                        module_class = module_entry.get("class")
                        module_rating = module_entry.get("rating")
                    elif isinstance(module_entry, str):
                        module_symbol = module_entry
                        module_name = module_entry
                        raw_module_id = None
                        module_category = None
                        module_class = None
                        module_rating = None
                    else:
                        continue

                    normalized_module_category = (
                        self.normalizer.normalize(
                            "station_modules", "category", "module_categories", module_category, metrics=self.metrics
                        )
                        if module_category
                        else None
                    )

                    normalized_module_name = self.normalizer.normalize(
                        "station_modules", "name", "modules", module_symbol or module_name, metrics=self.metrics
                    )
                    module_id = EDDNUtils.get_entity_id(raw_module_id, module_symbol)
                    module_record_data = {
                        "market_id": market_id,
                        "name": normalized_module_name,
                        "symbol": module_symbol,
                        "moduleId": module_id,
                        "class": module_class,
                        "rating": module_rating,
                        "category": normalized_module_category,
                        "update_dtm": timestamp,
                    }
                    records.append(
                        TransformedRecord(
                            table_name="station_modules",
                            data=module_record_data,
                            key_fields=("market_id", "moduleId"),
                            timestamp_field="update_dtm",
                        )
                    )

        return records

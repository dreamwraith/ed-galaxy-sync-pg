"""Transformer for EDDN Fleet Carrier bartender material (FCMaterials) messages."""

from typing import Any

from ..normalizers import NormalizerManager
from ..utils import EDDNUtils
from .base import BaseTransformer, TransformedRecord


class FCMaterialsTransformer(BaseTransformer):
    """Transforms EDDN Fleet Carrier bartender material messages (Journal and CAPI).

    Emits `station_materials` records for bartender inventories and updates
    `bartender_updated_at` on the `stations` table.
    """

    def __init__(self, normalizer: NormalizerManager | None = None, metrics: Any | None = None) -> None:
        """Initializes FCMaterialsTransformer.

        Args:
            normalizer: Optional NormalizerManager instance for bartender material normalization.
            metrics: Optional EDDNMetrics instance for recording unmapped tokens.
        """
        self.normalizer = normalizer or NormalizerManager()
        self.metrics = metrics

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Checks if this transformer can handle the FCMaterials schema or event."""
        return "fcmaterials" in schema_ref.lower() or message.get("event") == "FCMaterials"

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms Fleet Carrier material payloads into station_materials and carrier station records."""
        records: list[TransformedRecord] = []
        market_id_raw = message.get("MarketID") or message.get("marketId")
        if not market_id_raw:
            return records

        try:
            market_id = int(market_id_raw)
        except ValueError, TypeError:
            return records

        timestamp = message.get("timestamp")
        carrier_id = message.get("CarrierID") or message.get("carrierId")
        carrier_name = message.get("CarrierName") or message.get("carrierName")
        callsign = carrier_id or carrier_name or "Fleet Carrier"

        station_type = self.normalizer.normalize("stations", "type", "station_types", "Fleet Carrier", metrics=self.metrics)

        # 1. Always emit a stations update record to track bartender_updated_at and trigger stale cleanup
        station_record_data = {
            "market_id": market_id,
            "system_id64": 0,
            "name": callsign,
            "realName": callsign,
            "carrierName": carrier_name,
            "type": station_type,
            "bartender_updated_at": timestamp,
            "update_dtm": timestamp,
        }
        records.append(
            TransformedRecord(
                table_name="stations",
                data=station_record_data,
                key_fields=("market_id",),
                timestamp_field="bartender_updated_at",
            )
        )

        items_container = message.get("Items") or message.get("items")
        if not items_container:
            return records

        # 2. Extract material items
        extracted_materials: dict[int, dict[str, Any]] = {}

        if isinstance(items_container, list):
            # Journal format: list of item dicts
            for item in items_container:
                if not isinstance(item, dict):
                    continue
                raw_name = item.get("Name") or item.get("name")
                if not raw_name:
                    continue

                normalized_material_name = self.normalizer.normalize(
                    "station_materials", "name", "materials", raw_name, metrics=self.metrics
                )

                raw_material_id = item.get("id") or item.get("Id")
                material_id = EDDNUtils.get_entity_id(raw_material_id, raw_name)
                price = int(item.get("Price") or item.get("price") or 0)
                stock = int(item.get("Stock") or item.get("stock") or 0)
                demand = int(item.get("Demand") or item.get("demand") or 0)

                buy_price = price if demand > 0 else 0
                sell_price = price if stock > 0 else 0

                extracted_materials[material_id] = {
                    "market_id": market_id,
                    "carrier_id": carrier_id,
                    "material_id": material_id,
                    "name": normalized_material_name,
                    "symbol": raw_name,
                    "stock": stock,
                    "demand": demand,
                    "buyPrice": buy_price,
                    "sellPrice": sell_price,
                    "update_dtm": timestamp,
                }

        elif isinstance(items_container, dict):
            # CAPI format: {"sales": [...], "purchases": [...]}
            sales = items_container.get("sales") or []
            if isinstance(sales, list):
                for sale_item in sales:
                    if not isinstance(sale_item, dict):
                        continue
                    raw_name = sale_item.get("name") or sale_item.get("Name")
                    if not raw_name:
                        continue
                    normalized_material_name = self.normalizer.normalize(
                        "station_materials", "name", "materials", raw_name, metrics=self.metrics
                    )
                    raw_material_id = sale_item.get("id") or sale_item.get("Id")
                    material_id = EDDNUtils.get_entity_id(raw_material_id, raw_name)
                    price = int(sale_item.get("price") or sale_item.get("Price") or 0)
                    stock = int(sale_item.get("stock") or sale_item.get("Stock") or 0)

                    extracted_materials[material_id] = {
                        "market_id": market_id,
                        "carrier_id": carrier_id,
                        "material_id": material_id,
                        "name": normalized_material_name,
                        "symbol": raw_name,
                        "stock": stock,
                        "demand": 0,
                        "buyPrice": 0,
                        "sellPrice": price,
                        "update_dtm": timestamp,
                    }

            purchases = items_container.get("purchases") or []
            if isinstance(purchases, list):
                for purchase_item in purchases:
                    if not isinstance(purchase_item, dict):
                        continue
                    raw_name = purchase_item.get("name") or purchase_item.get("Name")
                    if not raw_name:
                        continue
                    normalized_material_name = self.normalizer.normalize(
                        "station_materials", "name", "materials", raw_name, metrics=self.metrics
                    )
                    raw_material_id = purchase_item.get("id") or purchase_item.get("Id")
                    material_id = EDDNUtils.get_entity_id(raw_material_id, raw_name)
                    price = int(purchase_item.get("price") or purchase_item.get("Price") or 0)
                    demand = int(purchase_item.get("demand") or purchase_item.get("Demand") or 0)

                    if material_id in extracted_materials:
                        extracted_materials[material_id]["demand"] = demand
                        extracted_materials[material_id]["buyPrice"] = price
                    else:
                        extracted_materials[material_id] = {
                            "market_id": market_id,
                            "carrier_id": carrier_id,
                            "material_id": material_id,
                            "name": normalized_material_name,
                            "symbol": raw_name,
                            "stock": 0,
                            "demand": demand,
                            "buyPrice": price,
                            "sellPrice": 0,
                            "update_dtm": timestamp,
                        }

        records.extend(
            TransformedRecord(
                table_name="station_materials",
                data=material_record_data,
                key_fields=("market_id", "material_id"),
                timestamp_field="update_dtm",
            )
            for material_record_data in extracted_materials.values()
        )

        return records

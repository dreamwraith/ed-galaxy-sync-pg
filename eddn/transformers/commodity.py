"""Transformer for EDDN commodity market schema messages."""

from typing import Any

from ..normalizers import NormalizerManager
from ..utils import EDDNUtils
from .base import BaseTransformer, TransformedRecord


class CommodityTransformer(BaseTransformer):
    """Transforms EDDN commodity market messages into station_commodities records.

    Also emits timestamp updates to `stations.market_updated_at` to trigger stale item cleanup.
    """

    def __init__(self, normalizer: NormalizerManager | None = None, metrics: Any | None = None) -> None:
        """Initializes CommodityTransformer.

        Args:
            normalizer: Optional NormalizerManager instance for commodity and category normalization.
            metrics: Optional EDDNMetrics instance for recording unmapped tokens.
        """
        self.normalizer = normalizer or NormalizerManager()
        self.metrics = metrics

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Checks if this transformer can handle the commodity schema."""
        return "commodity" in schema_ref

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms commodity payloads into station_commodities and station update records."""
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

        # 1. Always emit a stations update record to track market_updated_at and trigger stale cleanup
        station_display_name = station_name or "Unknown Station"
        station_record_data = {
            "market_id": market_id,
            "system_id64": 0,
            "name": station_display_name,
            "realName": station_display_name,
            "market_updated_at": timestamp,
            "update_dtm": timestamp,
        }

        records.append(
            TransformedRecord(
                table_name="stations",
                data=station_record_data,
                key_fields=("market_id",),
                timestamp_field="market_updated_at",
            )
        )

        # 2. Process commodities list if present
        commodities = message.get("commodities") or message.get("Commodities")
        if isinstance(commodities, list):
            for commodity_entry in commodities:
                commodity_name = commodity_entry.get("name") or commodity_entry.get("Name")
                if not commodity_name:
                    continue

                normalized_commodity_name = self.normalizer.normalize(
                    "station_commodities", "name", "commodities", commodity_name, metrics=self.metrics
                )
                raw_category = commodity_entry.get("category") or commodity_entry.get("Category")

                normalized_category = (
                    self.normalizer.normalize(
                        "station_commodities", "category", "commodity_categories", raw_category, metrics=self.metrics
                    )
                    if raw_category
                    else None
                )

                raw_commodity_id = commodity_entry.get("commodityId") or commodity_entry.get("id")
                commodity_id = EDDNUtils.get_entity_id(raw_commodity_id, commodity_name)

                commodity_record_data = {
                    "market_id": market_id,
                    "name": normalized_commodity_name,
                    "symbol": commodity_entry.get("symbol") or commodity_entry.get("Symbol") or commodity_name.lower(),
                    "category": normalized_category,
                    "commodityId": commodity_id,
                    "demand": commodity_entry.get("demand") or commodity_entry.get("Demand", 0),
                    "supply": commodity_entry.get("stock") or commodity_entry.get("supply") or commodity_entry.get("Stock", 0),
                    "buyPrice": commodity_entry.get("buyPrice") or commodity_entry.get("BuyPrice", 0),
                    "sellPrice": commodity_entry.get("sellPrice") or commodity_entry.get("SellPrice", 0),
                    "update_dtm": timestamp,
                }

                records.append(
                    TransformedRecord(
                        table_name="station_commodities",
                        data=commodity_record_data,
                        key_fields=("market_id", "commodityId"),
                        timestamp_field="update_dtm",
                    )
                )

        return records

"""Dead-Letter Queue (DLQ) fallback transformer for unmapped or rejected EDDN events."""

import json
from typing import Any

from .base import BaseTransformer, TransformedRecord


class UnhandledEventTransformer(BaseTransformer):
    """Dead-Letter Queue (DLQ) fallback transformer for unmapped schemas or novel events.

    Captures unhandled, legacy, or filtered events into the `eddn_unhandled_events` table
    with raw payload auditing and rejection reasons for subsequent analysis or schema expansion.
    """

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Always returns True as the final fallback transformer."""
        return True

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
        reason: str = "unhandled_schema",
    ) -> list[TransformedRecord]:
        """Transforms unhandled or rejected payloads into eddn_unhandled_events DLQ records."""
        app_name = header.get("softwareName") or header.get("appName") or header.get("software_name")

        # Combine message with header metadata for complete auditing
        raw_payload = dict(message)
        if header:
            raw_payload["header"] = header
        if schema_ref:
            raw_payload["$schemaRef"] = schema_ref

        unhandled_record_data = {
            "message_timestamp": message.get("timestamp"),
            "schema_ref": schema_ref,
            "event_name": message.get("event") or (schema_ref.split("/")[-2] if "/" in schema_ref else schema_ref),
            "system_name": message.get("StarSystem") or message.get("systemName"),
            "station_name": message.get("StationName") or message.get("stationName"),
            "uploader_id": header.get("uploaderID"),
            "app_name": app_name,
            "dlq_reason": reason,
            "raw_message": json.dumps(raw_payload),
        }

        return [
            TransformedRecord(
                table_name="eddn_unhandled_events",
                data=unhandled_record_data,
                key_fields=("id",),
                timestamp_field=None,
            )
        ]

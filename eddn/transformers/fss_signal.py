"""Transformer for EDDN FSSSignalDiscovered schema messages."""

import logging
from typing import Any

from ..normalizers import NormalizerManager
from .base import BaseTransformer, TransformedRecord


logger = logging.getLogger(__name__)


class FSSSignalTransformer(BaseTransformer):
    """Transforms EDDN FSS signal discovery messages into system_signals records."""

    def __init__(
        self,
        normalizer: NormalizerManager | None = None,
        metrics: Any | None = None,
    ) -> None:
        """Initializes FSSSignalTransformer.

        Args:
            normalizer: Optional NormalizerManager instance for FSS scenario and signal resolution.
            metrics: Optional EDDNMetrics instance for recording unmapped scenarios.
        """
        self.normalizer = normalizer or NormalizerManager()
        self.metrics = metrics

    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Checks if this transformer can handle the FSSSignalDiscovered schema or event."""
        schema_lower = schema_ref.lower()
        return "fsssignaldiscovered" in schema_lower or message.get("event") in {"FSSSignalDiscovered"}

    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms FSSSignalDiscovered signals into system_signals TransformedRecord objects."""
        records: list[TransformedRecord] = []
        system_id64_raw = message.get("SystemAddress")
        if not system_id64_raw:
            return records

        try:
            system_id64 = int(system_id64_raw)
            if system_id64 <= 1:
                return records
        except ValueError, TypeError:
            return records

        timestamp = message.get("timestamp")
        signals = message.get("signals") or message.get("Signals")

        if not isinstance(signals, list):
            # Check single signal format
            single_signal_name = message.get("SignalName")
            if single_signal_name:
                signals = [message]
            else:
                return records

        for signal_entry in signals:
            if not isinstance(signal_entry, dict):
                continue

            raw_name = signal_entry.get("SignalName")
            if not raw_name:
                continue

            uss_signal_type = signal_entry.get("USSType") or ""
            # Filter out ephemeral personal mission USS signals
            if uss_signal_type == "$USS_Type_MissionTarget;" or "missiontarget" in raw_name.lower().replace("_", "").replace(
                " ", ""
            ):
                continue
            raw_type = signal_entry.get("SignalType")
            localised = signal_entry.get("SignalName_Localised")
            threat = signal_entry.get("ThreatLevel")
            is_station = signal_entry.get("IsStation", False)
            faction = signal_entry.get("SpawningFaction")
            state = signal_entry.get("SpawningState")
            signal_timestamp = signal_entry.get("timestamp") or timestamp

            display_name, signal_type, severity = self.normalizer.resolve_scenario(
                raw_name, raw_type, localised, is_station=is_station, metrics=self.metrics
            )

            signal_record_data = {
                "system_id64": system_id64,
                "signal_type": signal_type,
                "name": display_name,
                "raw_name": raw_name,
                "severity": severity,
                "threat_level": threat,
                "spawning_faction": faction,
                "spawning_state": state,
                "is_station": is_station,
                "update_dtm": signal_timestamp,
            }

            records.append(
                TransformedRecord(
                    table_name="system_signals",
                    data=signal_record_data,
                    key_fields=("system_id64", "raw_name"),
                    timestamp_field="update_dtm",
                )
            )

        return records

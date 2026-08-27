"""EDDN message router with sender whitelisting, version gating, and DLQ dispatching.

Evaluates incoming EDDN payloads against sender application whitelists, minimum
game version thresholds, ignore filters for ephemeral events, and dot-notation
debug log match rules. Matched messages are dispatched to registered core
transformers; unhandled or rejected events are routed to the Dead-Letter Queue
transformer for auditing and future reprocessing.
"""

import json
import logging
from typing import Any

from .metrics import EDDNMetrics
from .normalizers import NormalizerManager
from .transformers import (
    BaseTransformer,
    CommodityTransformer,
    FCMaterialsTransformer,
    FSSSignalTransformer,
    JournalJumpTransformer,
    JournalScanTransformer,
    JournalStationTransformer,
    ShipyardTransformer,
    TransformedRecord,
    UnhandledEventTransformer,
)
from .utils import EDDNUtils


logger = logging.getLogger(__name__)


class EDDNRouter:
    """Routes incoming EDDN JSON payloads to appropriate transformers.

    Evaluates sender whitelist policies, legacy game version gating, ignore filters,
    and dot-notation debug log match rules. Unmatched or invalid events are routed
    to the Dead-Letter Queue transformer.
    """

    def __init__(
        self,
        config_data: dict[str, Any],
        metrics: EDDNMetrics | None = None,
        normalizer: NormalizerManager | None = None,
    ) -> None:
        """Initializes the EDDNRouter instance.

        Args:
            config_data: Application configuration dictionary loaded from config.yaml.
            metrics: Optional EDDNMetrics instance for recording filtered events and statistics.
            normalizer: Optional NormalizerManager instance for token and scenario normalizations.
        """
        self.config_data = config_data
        self.metrics = metrics
        self.normalizer = normalizer or NormalizerManager()

        # 1. Initialize Internal Variables
        self._IGNORE_SCHEMAS: set[str] = {
            "navroute",
            "dockinggranted",
            "dockingdenied",
            "fssallbodiesfound",
            "navbeaconscan",
            "scanbarycentre",
        }
        self._debug_rules = self.config_data.get("debug_log") or []
        self._debug_all = self.config_data.get("debug_all") or []
        self._enable_dlq = self.config_data.get("enable_dlq", True)
        self._min_game_version = self.config_data.get("min_game_version", "4.0")
        self._allowed_senders: dict[str, bool] = {
            sender["name"].lower(): bool(sender.get("bypass_version_check", False))
            for sender in (self.config_data.get("allowed_senders") or [])
            if isinstance(sender, dict) and "name" in sender
        }

        # Registered core transformers
        self.transformers: list[BaseTransformer] = [
            JournalJumpTransformer(normalizer=self.normalizer, metrics=self.metrics),
            JournalScanTransformer(normalizer=self.normalizer, metrics=self.metrics),
            JournalStationTransformer(normalizer=self.normalizer, metrics=self.metrics),
            CommodityTransformer(normalizer=self.normalizer, metrics=self.metrics),
            ShipyardTransformer(normalizer=self.normalizer, metrics=self.metrics),
            FSSSignalTransformer(normalizer=self.normalizer, metrics=self.metrics),
            FCMaterialsTransformer(normalizer=self.normalizer, metrics=self.metrics),
        ]

        self.dlq_transformer = UnhandledEventTransformer()

    def route(self, raw_payload: dict[str, Any]) -> list[TransformedRecord]:
        """Parses and transforms an EDDN message dictionary into database records.

        Args:
            raw_payload: Deserialized EDDN JSON message payload containing $schemaRef,
                header, and message dictionaries.

        Returns:
            list[TransformedRecord]: List of TransformedRecord objects ready for database batching.
        """
        schema_ref = raw_payload.get("$schemaRef", "")
        header = raw_payload.get("header", {}) or {}
        message = raw_payload.get("message", {}) or {}
        should_bypass_version = False

        # Evaluate debug log filter rules
        debug_records: list[TransformedRecord] = []
        if self._debug_all or self._debug_rules:
            matched_labels: list[str] = ["All_Messages"] if self._debug_all else []
            matched_labels.extend(
                rule.get("label", "debug")
                for rule in self._debug_rules
                if isinstance(rule, dict) and EDDNUtils.matches_debug_rule(raw_payload, rule.get("match", {}))
            )

            if matched_labels:
                uploader_id = (header.get("uploaderID") or header.get("uploaderId") or header.get("uploader_id") or "").strip()
                software_name = (header.get("softwareName") or header.get("appName") or header.get("software_name") or "").strip()
                software_version = (header.get("gameversion") or header.get("softwareVersion") or "").strip()
                event_name = message.get("event") or (schema_ref.split("/")[-2] if "/" in schema_ref else "unknown")
                msg_timestamp = message.get("timestamp") or header.get("gatewayTimestamp")
                raw_payload_json = json.dumps(raw_payload) if isinstance(raw_payload, dict) else str(raw_payload)

                for label in matched_labels:
                    logger.info(
                        f"🎯 [DEBUG LOG] Captured message matching '{label}' "
                        f"(software: {software_name} v{software_version}, uploaderID: {uploader_id}, schema: {schema_ref}, event: {event_name})"
                    )
                    debug_records.append(
                        TransformedRecord(
                            table_name="_raw_debug_log",
                            data={
                                "filter_label": label,
                                "software_name": software_name,
                                "software_version": software_version,
                                "uploader_id": uploader_id,
                                "schema_ref": schema_ref,
                                "event_name": event_name,
                                "message_timestamp": msg_timestamp,
                                "raw_payload": raw_payload_json,
                            },
                            key_fields=(),
                            timestamp_field=None,
                        )
                    )

        # 1. Filter out test messages
        if "/test" in schema_ref:
            return debug_records

        # 2. Check ignore list (never save or process ephemeral events like NavRoute, DockingGranted, ScanBaryCentre)
        schema_lower = schema_ref.lower()
        event_lower = (message.get("event") or "").lower()
        for ignored in self._IGNORE_SCHEMAS:
            ignored_schema = ignored.lower()
            if (ignored_schema and ignored_schema in schema_lower) or (ignored_schema and ignored_schema == event_lower):
                return debug_records

        # 2b. Ignore personal/geological/celestial codex discoveries (terminals, data logs, planets, volcanism)
        if "codexentry" in schema_lower or event_lower == "codexentry":
            category = message.get("Category", "")
            sub_category = message.get("SubCategory", "")
            is_bio = "Biology" in category or "Organic" in category or "Flora" in category or message.get("Genus") is not None
            nearest_dest = str(message.get("NearestDestination") or "")
            is_space_phenomena = (
                "Phenomena" in category
                or "Storms" in sub_category
                or "Organic_Structures" in sub_category
                or "Lagrange" in str(message.get("Name"))
                or "Life_Cloud" in nearest_dest
                or "Lagrange" in nearest_dest
            )
            if not is_bio and not is_space_phenomena:
                return debug_records
            if (
                "StellarBodies" in category
                or "Stars" in category
                or "Planets" in category
                or "Geology" in sub_category
                or "Terrestrial" in sub_category
            ):
                return debug_records

        software_name = (header.get("softwareName") or header.get("appName") or header.get("software_name") or "").strip()

        # 3. Sender application whitelist check (exact string match, case-insensitive)
        should_bypass_version = False
        if self._allowed_senders:
            name_key = software_name.lower()
            matched = software_name != "" and name_key in self._allowed_senders
            should_bypass_version = self._allowed_senders.get(name_key, False) if matched else False

            if not matched:
                if self.metrics:
                    self.metrics.record_filtered_sender(1)
                if self._enable_dlq:
                    dlq_records = self.dlq_transformer.transform(schema_ref, header, message, reason="unapproved_sender")
                    return debug_records + dlq_records
                return debug_records

        if not should_bypass_version:
            keys = ("gameversion", "gameVersion", "game_version")
            game_version = next((data_dict[key] for data_dict in (header, message) for key in keys if key in data_dict), None)
            is_valid_ver, ver_reason = EDDNUtils.check_game_version(game_version, self._min_game_version)

            if not is_valid_ver:
                if self.metrics:
                    self.metrics.record_filtered_game_version(1)

                # Truly legacy versions (3.x or explicit Legacy galaxy) are cleanly no-oped (do not DLQ)
                if ver_reason.startswith("legacy_game_version"):
                    return debug_records

                # Outdated non-legacy (Live) versions below min_game_version or missing versions -> route to DLQ
                if self._enable_dlq:
                    return debug_records + self.dlq_transformer.transform(schema_ref, header, message, reason=ver_reason)

                return debug_records

        # 4. Message timestamp sanity check (filter out uninitialized epoch or future drift dates)
        message_timestamp = message.get("timestamp") or header.get("gatewayTimestamp")
        if message_timestamp and not EDDNUtils.is_valid_timestamp(message_timestamp):
            if self._enable_dlq:
                return debug_records + self.dlq_transformer.transform(schema_ref, header, message, reason="invalid_timestamp")
            return debug_records

        # 4b. Guard against corrupted SystemAddress <= 1
        system_address = message.get("SystemAddress") or message.get("systemAddress")
        if system_address is not None and isinstance(system_address, int) and system_address <= 1:
            if self._enable_dlq:
                return debug_records + self.dlq_transformer.transform(schema_ref, header, message, reason="invalid_system_address")
            return debug_records

        # 5. Match against core transformers
        # [TEMPORARY HACK] Audit snapshot before transformation
        unmapped_count_before = (
            sum(sum(len(tokens) for tokens in fields.values()) for fields in self.metrics.unmapped_tokens.values())
            if self.metrics
            else 0
        )
        matched_records: list[TransformedRecord] = []
        matched_transformers: list[str] = []

        for transformer in self.transformers:
            if transformer.can_handle(schema_ref, header, message):
                matched_transformers.append(transformer.__class__.__name__)
                records = transformer.transform(schema_ref, header, message)
                if records:
                    matched_records.extend(records)

        # 6. Fallback to Dead-Letter Queue if unhandled or rejected
        if not matched_records and self._enable_dlq:
            event_name = message.get("event") or (schema_ref.split("/")[-2] if "/" in schema_ref else "unknown")
            if matched_transformers:
                # Schema/event was recognized by registered transformers, but 0 records were produced
                transformer_names = ", ".join(matched_transformers)
                missing = []
                if "SystemAddress" not in message and "systemName" not in message and "StarSystem" not in message:
                    missing.append("SystemAddress/StarSystem")
                if (
                    (
                        "commodity" in schema_lower
                        or "shipyard" in schema_lower
                        or "outfitting" in schema_lower
                        or "fcmaterials" in schema_lower
                    )
                    and "MarketID" not in message
                    and "marketId" not in message
                ):
                    missing.append("MarketID")
                if (
                    "journal" in schema_lower
                    and ("docked" in event_lower or "approachsettlement" in event_lower)
                    and "StationName" not in message
                    and "Name" not in message
                ):
                    missing.append("StationName/Name")

                if missing:
                    missing_desc = ", ".join(missing)
                    reason = f"validation_error: {transformer_names} matched event '{event_name}' in schema '{schema_ref}', but required fields were missing or invalid: {missing_desc}"
                else:
                    reason = f"validation_error: {transformer_names} matched event '{event_name}' in schema '{schema_ref}', but produced 0 records (empty payload or filtered entities)"
            else:
                reason = f"unhandled_schema: no transformer registered for schema '{schema_ref}' (event: '{event_name}')"

            dlq_records = self.dlq_transformer.transform(schema_ref, header, message, reason=reason)
            matched_records.extend(dlq_records)

        # --------------------------------------------------------------------------
        # [TEMPORARY HACK] Audit Hook: Capture unmapped token payloads to _raw_debug_log
        # >>> DELETE THIS ENTIRE BLOCK WHEN DONE WITH MANUAL REVIEW <<<
        # --------------------------------------------------------------------------
        if (
            self.metrics
            and sum(sum(len(tokens) for tokens in fields.values()) for fields in self.metrics.unmapped_tokens.values())
            > unmapped_count_before
        ):
            uploader_id = (header.get("uploaderID") or header.get("uploaderId") or header.get("uploader_id") or "").strip()
            software_name = (header.get("softwareName") or header.get("appName") or header.get("software_name") or "").strip()
            software_version = (header.get("gameversion") or header.get("softwareVersion") or "").strip()
            event_name = message.get("event") or (schema_ref.split("/")[-2] if "/" in schema_ref else "unknown")
            msg_timestamp = message.get("timestamp") or header.get("gatewayTimestamp")
            raw_payload_json = json.dumps(raw_payload) if isinstance(raw_payload, dict) else str(raw_payload)

            logger.info(
                f"🎯 [UNMAPPED DEBUG] Captured message with unmapped token to _raw_debug_log "
                f"(software: {software_name} v{software_version}, uploaderID: {uploader_id}, schema: {schema_ref}, event: {event_name})"
            )
            debug_records.append(
                TransformedRecord(
                    table_name="_raw_debug_log",
                    data={
                        "filter_label": f"Unmapped_Token:{event_name}",
                        "software_name": software_name,
                        "software_version": software_version,
                        "uploader_id": uploader_id,
                        "schema_ref": schema_ref,
                        "event_name": event_name,
                        "message_timestamp": msg_timestamp,
                        "raw_payload": raw_payload_json,
                    },
                    key_fields=(),
                    timestamp_field=None,
                )
            )
        # --------------------------------------------------------------------------

        if debug_records:
            matched_records = debug_records + matched_records

        return matched_records

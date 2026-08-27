"""Shared utility helpers for EDDN message transformation and entity resolution.

Provides static methods for Frontier EDName sanitization, case/punctuation-insensitive
normalization, YAML/JSON configuration loading, Fleet Carrier callsign parsing,
deterministic body ID64 computation, CRC32-based entity ID fallback generation,
game version validation, dot-notation path extraction, debug rule matching, and
live EDDN stream commander probing.
"""

import contextlib
import json
import logging
import re
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
import zmq


logger = logging.getLogger(__name__)


class EDDNUtils:
    """Utility helpers for EDDN message transformation, entity parsing, and database batching."""

    @staticmethod
    def sanitize_edname(raw_name: str | None) -> str:
        """Strips Frontier EDName wrapper artifacts (leading '$', trailing ';', index tags,
        whitespace, and known Frontier prefixes/suffixes) while strictly preserving
        original internal character casing.

        Examples:
            "$government_Anarchy;" -> "Anarchy"
            "$Codex_Ent_Aleoida_01_A_Name;" -> "Aleoida_01_A"
            "$Codex_Ent_Aleoid_Genus_Name;" -> "Aleoid"
            "$economy_Industrial;" -> "Industrial"
            "$Warzone_PointRace_Low:#index=1;" -> "Warzone_PointRace_Low"
            "  $airqualityreports_name;  " -> "airqualityreports"
            "Drake-Class Carrier" -> "Drake-Class Carrier"
            "Unmapped_Unknown_Variant_XYZ" -> "Unmapped_Unknown_Variant_XYZ"
            None -> ""

        Args:
            raw_name: Raw token string or None.

        Returns:
            str: Sanitized string stripped of unusable wrapper symbols and known prefixes/suffixes,
                 with original casing preserved. Returns empty string on None or empty input.
        """
        if raw_name is None:
            return ""
        sanitized_name = str(raw_name).strip()
        if not sanitized_name:
            return ""

        # Strip parameter suffixes like :#index=1;
        sanitized_name = re.sub(r":#index=\d+;?$", "", sanitized_name)

        # Strip leading $ and trailing ;
        sanitized_name = sanitized_name.lstrip("$").rstrip(";").strip()
        if not sanitized_name:
            return ""

        lowercase_name = sanitized_name.lower()

        known_prefixes = (
            "codex_ent_",
            "codex_category_",
            "codex_subcategory_",
            "government_",
            "economy_",
            "allegiance_",
            "factionstate_",
            "stationstate_",
            "faction_",
            "system_security_",
            "galaxy_map_info_state_",
            "carrierdockingaccess_",
            "market_category_",
            "eringclass_",
            "saa_signaltype_",
            "reservelevel_",
        )
        known_suffixes = ("_genus_name", "_species_name", "_name", "_desc")

        # Strip known prefixes (case-insensitively, preserving original casing of remainder)
        for known_prefix in known_prefixes:
            if lowercase_name.startswith(known_prefix):
                sanitized_name = sanitized_name[len(known_prefix) :].strip()
                lowercase_name = sanitized_name.lower()
                break

        # Strip known suffixes (case-insensitively, preserving original casing of remainder)
        for known_suffix in known_suffixes:
            if lowercase_name.endswith(known_suffix):
                sanitized_name = sanitized_name[: -len(known_suffix)].strip()
                lowercase_name = sanitized_name.lower()
                break

        return sanitized_name

    @staticmethod
    def sanitize_station_name(raw_name: str | None) -> str:
        """Sanitizes station, port, and settlement display names by stripping
        Frontier dollar/semicolon symbol wrappers, trailing settlement security markers
        ('+', '++', '+++'), and extraneous whitespace.

        Examples:
            "Muller Extraction +++" -> "Muller Extraction"
            "Stevenson Research Base ++" -> "Stevenson Research Base"
            "  $Station_Name;  " -> "Station_Name"
            "Jameson Memorial" -> "Jameson Memorial"
            None -> ""

        Args:
            raw_name: Raw station or POI name string or None.

        Returns:
            str: Cleaned station display name, or empty string on None/empty input.
        """
        if not raw_name:
            return ""
        return raw_name.strip().lstrip("$").rstrip(";+ ").strip()

    @staticmethod
    def is_valid_timestamp(
        timestamp_str: str | None,
        max_future_seconds: int = 86400,
    ) -> bool:
        """Validates that an ISO 8601 timestamp string is well-formed, not prehistoric
        (before Elite Dangerous release on 2014-12-16), and not unreasonably in the future.

        Args:
            timestamp_str: ISO 8601 timestamp string (e.g. '2026-08-26T19:00:00Z').
            max_future_seconds: Allowable clock drift into future in seconds (default: 86400 / 24h).

        Returns:
            bool: True if timestamp is valid and within acceptable date bounds, False otherwise.
        """
        if not timestamp_str:
            return False
        try:
            normalized_timestamp = timestamp_str[:-1] + "+00:00" if timestamp_str.endswith(("Z", "z")) else timestamp_str
            parsed_datetime = datetime.fromisoformat(normalized_timestamp)
            if parsed_datetime.tzinfo is None:
                parsed_datetime = parsed_datetime.replace(tzinfo=UTC)
            current_utc_datetime = datetime.now(UTC)
            return not (
                parsed_datetime < datetime(2014, 12, 16, tzinfo=UTC)
                or (parsed_datetime - current_utc_datetime).total_seconds() > max_future_seconds
            )
        except ValueError, TypeError:
            return False

    @staticmethod
    def normalize_lookup_key(raw_token: Any) -> str:
        """Normalizes a token for in-memory O(1) comparison by stripping whitespace,
        underscores, hyphens, parentheses, periods, and quotes, and lowercasing the result.

        Examples:
            "B (Blue-white super giant) Star" -> "bbluewhitesupergiantstar"
            "B_Blue_White_Super_Giant" -> "bbluewhitesupergiant"
            "Type-8 Transporter" -> "type8transporter"
            "Python Mk. II" -> "pythonmkii"
            "O'Neil Cylinder" -> "oneilcylinder"
            "Consumer_Items" -> "consumeritems"

        Args:
            raw_token: Raw token or string.

        Returns:
            str: Normalized string for case/punctuation-insensitive lookup.
        """
        if raw_token is None:
            return ""
        strip_punctuation_table = str.maketrans("", "", " _-().'\"")
        return str(raw_token).translate(strip_punctuation_table).lower()

    @staticmethod
    def sanitize_normalize_edname(raw_name: Any) -> str:
        """Sanitizes Frontier EDName wrappers (stripping '$', ';', index tags, known prefixes/suffixes)
        and normalizes the result for case- and punctuation-insensitive O(1) comparison.

        Combines `sanitize_edname()` and `normalize_lookup_key()` into a single step.

        Examples:
            "$Warzone_PointRace_Low:#index=1;" -> "warzonepointracelow"
            "$economy_Industrial;" -> "industrial"
            "$Codex_Ent_Aleoida_01_A_Name;" -> "aleoida01a"
            "Drake-Class Carrier" -> "drakeclasscarrier"
            None -> ""

        Args:
            raw_name: Raw token or string.

        Returns:
            str: Sanitized and normalized lowercase string without punctuation or spaces.
        """
        if raw_name is None:
            return ""
        return EDDNUtils.normalize_lookup_key(EDDNUtils.sanitize_edname(raw_name))

    @staticmethod
    def load_config(file_path: str | Path) -> dict[str, Any]:
        """Loads configuration dictionary from a YAML or JSON file.

        Args:
            file_path: Filepath to the YAML or JSON configuration file.

        Returns:
            dict[str, Any]: Parsed configuration dictionary, or empty dict on failure.
        """
        if not file_path:
            return {}
        config_path = Path(file_path)
        if not config_path.is_file():
            return {}
        try:
            config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            return config_data if isinstance(config_data, dict) else {}
        except Exception as err:
            logger.warning(f"Failed to load config file '{file_path}': {err}")
            return {}

    @staticmethod
    def extract_carrier_parts(station_text: str, signal_type: str | None = None) -> tuple[str | None, str | None, str | None]:
        """Extracts callsign, custom name, and classified carrier type from a Fleet Carrier or Squadron Carrier string.

        Supports:
            - Squadron Carrier pipe format: 'UECV NO OSHA HERE | SKAG' -> ('SKAG', 'UECV NO OSHA HERE', 'SquadronCarrier')
            - Squadron Carrier callsign only: '| SKAG' -> ('SKAG', None, 'SquadronCarrier')
            - Fleet Carrier standard format: 'ESB Tiberium Toke RZZ-51F' -> ('RZZ-51F', 'ESB Tiberium Toke', 'FleetCarrier')
            - Fleet Carrier callsign only: 'RZZ-51F' -> ('RZZ-51F', None, 'FleetCarrier')
            - Bracketed callsign format: 'DSSA Explorer\\'s Haven (V2X-45L)' -> ('V2X-45L', 'DSSA Explorer\\'s Haven', 'FleetCarrier')

        Args:
            station_text: Raw station or signal string containing carrier name/callsign.
            signal_type: Optional signal type indicator.

        Returns:
            tuple[str | None, str | None, str | None]: Tuple of (carrier_id, carrier_name, carrier_type).
        """
        if not station_text:
            return None, None, None

        cleaned_text = station_text.strip()

        # 1. Squadron Carrier format with pipe delimiter (e.g. "NAME | ID" or "| ID")
        if "|" in cleaned_text:
            pipe_segments = cleaned_text.rsplit("|", 1)
            name_part = pipe_segments[0].strip()
            id_part = pipe_segments[1].strip()
            carrier_id = id_part if id_part else None
            carrier_name = name_part if name_part else None
            return carrier_id, carrier_name, "SquadronCarrier"

        # 2. Fleet Carrier format XXX-XXX (e.g. "NAME XXX-XXX" or "XXX-XXX")
        callsign_match = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", cleaned_text)
        if callsign_match:
            carrier_id = callsign_match.group(1)
            name_part = re.sub(r"[\(\[\{]?\b" + re.escape(carrier_id) + r"\b[\)\]\}]?", "", cleaned_text).strip()
            carrier_name = name_part if name_part else None
            return carrier_id, carrier_name, "FleetCarrier"

        return None, None, None

    @staticmethod
    def compute_body_id64(system_id64: Any, body_id: Any) -> int:
        """Computes a deterministic 64-bit body ID if raw id64 is absent.

        Elite Dangerous systems use a 55-bit address; the top 9 bits encode the body ID.

        Args:
            system_id64: The 64-bit integer star system address.
            body_id: Local integer body ID within the star system.

        Returns:
            int: Deterministic composite 64-bit body ID.
        """
        try:
            system_address = int(system_id64)
        except ValueError, TypeError:
            return 0

        if body_id is None:
            return system_address

        try:
            body_number = int(body_id)
            return (system_address << 9) | (body_number & 0x1FF)
        except ValueError, TypeError:
            return system_address

    @staticmethod
    def get_entity_id(raw_id: Any | None, fallback_symbol: str) -> int:
        """Returns an entity integer ID, falling back to a deterministic 31-bit CRC32 hash.

        Args:
            raw_id: Integer ID provided in payload (if present).
            fallback_symbol: String symbol or name used to derive a deterministic hash ID.

        Returns:
            int: 31-bit integer entity ID.
        """
        if raw_id is not None:
            try:
                return int(raw_id)
            except ValueError, TypeError:
                pass
        cleaned_symbol = fallback_symbol.strip().lower()
        return zlib.crc32(cleaned_symbol.encode("utf-8")) & 0x7FFFFFFF

    @staticmethod
    def check_game_version(game_version: str | None, min_game_version: str | None = "4.0") -> tuple[bool, str]:
        """Validates the client game version string against a minimum version requirement.

        Args:
            game_version: Raw gameversion string from the message header.
            min_game_version: Minimum allowable version threshold (default: "4.0").

        Returns:
            tuple[bool, str]: Tuple of (is_valid, rejection_reason).
        """
        if not game_version or not game_version.strip():
            return False, "missing_game_version"

        version_string = game_version.strip()
        lowercase_version = version_string.lower()

        if "legacy" in lowercase_version:
            return False, f"legacy_game_version: {version_string}"
        if "live" in lowercase_version or not min_game_version:
            return True, ""

        def parse_version_tuple(version_text: str) -> tuple[int, ...] | None:
            """Parses numeric version components into a comparable integer tuple."""
            stripped_version = version_text.strip().lstrip("vV")
            version_parts: list[int] = []
            for chunk in re.split(r"[.\-_/ ]", stripped_version):
                if not chunk:
                    continue
                if chunk.isdigit():
                    version_parts.append(int(chunk))
                else:
                    digit_match = re.match(r"^(\d+)", chunk)
                    if digit_match:
                        version_parts.append(int(digit_match.group(1)))
                    break
            return tuple(version_parts) if version_parts else None

        version_tuple = parse_version_tuple(version_string)
        minimum_version_tuple = parse_version_tuple(min_game_version)
        if version_tuple is None or minimum_version_tuple is None:
            return False, f"unsupported_game_version: {version_string}"

        max_length = max(len(version_tuple), len(minimum_version_tuple))
        padded_version = version_tuple + (0,) * (max_length - len(version_tuple))
        padded_minimum = minimum_version_tuple + (0,) * (max_length - len(minimum_version_tuple))

        if padded_version < padded_minimum:
            if version_tuple[0] < 4:
                return False, f"legacy_game_version: {version_string}"
            return False, f"below_min_game_version: {version_string}"

        return True, ""

    @staticmethod
    def get_path_values(payload_node: Any, path_segments: list[str]) -> list[Any]:
        """Extracts all values matching a dot-separated path, traversing nested lists.

        Args:
            payload_node: Target dictionary or list payload node.
            path_segments: List of path string segments (e.g. ['header', 'softwareName']).

        Returns:
            list[Any]: All extracted matching values.
        """
        if not path_segments:
            return [payload_node] if payload_node is not None else []
        current_key, remaining_segments = path_segments[0], path_segments[1:]
        if isinstance(payload_node, dict):
            nested_value = payload_node.get(current_key)
            if nested_value is not None:
                return EDDNUtils.get_path_values(nested_value, remaining_segments)
        elif isinstance(payload_node, list):
            collected_values = []
            for item in payload_node:
                collected_values.extend(EDDNUtils.get_path_values(item, path_segments))
            return collected_values
        return []

    @staticmethod
    def matches_debug_rule(payload: dict[str, Any], match_criteria: dict[str, Any]) -> bool:
        """Checks if a payload matches all key/value criteria (case-insensitive).

        Args:
            payload: Incoming EDDN message payload dictionary.
            match_criteria: Dictionary mapping dot-notation paths to expected string values.

        Returns:
            bool: True if all criteria match, False otherwise.
        """
        if not isinstance(match_criteria, dict):
            return False
        for path, target in match_criteria.items():
            path_segments = path.strip().split(".")
            extracted_values = EDDNUtils.get_path_values(payload, path_segments)
            if not extracted_values:
                return False
            expected_target_value = str(target).strip().lower()
            if not any(str(extracted_val).strip().lower() == expected_target_value for extracted_val in extracted_values):
                return False
        return True

    @staticmethod
    def probe_commander(
        relay_url: str = "tcp://eddn.edcd.io:9500",
        system: str | None = None,
        station: str | None = None,
        software: str | None = None,
        limit: int = 3,
        timeout_ms: int = 30000,
    ) -> None:
        """Subscribes to live EDDN ZeroMQ messages to probe and display a client's uploaderID.

        Args:
            relay_url: EDDN ZeroMQ relay URL (default: 'tcp://eddn.edcd.io:9500').
            system: Optional star system name filter.
            station: Optional station name filter.
            software: Optional software name filter.
            limit: Maximum number of matched messages to display before exiting (default: 3).
            timeout_ms: Socket receive timeout in milliseconds (default: 30000).
        """
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.setsockopt_string(zmq.SUBSCRIBE, "")
        socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 30)
        socket.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 10)
        socket.connect(relay_url)

        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)

        logger.info("==================================================")
        logger.info("EDDN Commander / UploaderID Probe Active")
        logger.info(f"Connected to: {relay_url}")
        if system:
            logger.info(f"Filtering by StarSystem: '{system}'")
        if station:
            logger.info(f"Filtering by Station: '{station}'")
        if software:
            logger.info(f"Filtering by Software: '{software}'")
        logger.info("Perform an in-game action (jump, dock, scan, browse market) or trigger your EDDN publisher...")
        logger.info("Press Ctrl+C to stop.")
        logger.info("==================================================")

        matched_count = 0
        try:
            while matched_count < limit:
                try:
                    active_sockets = dict(poller.poll(500))
                except zmq.ZMQError:
                    break

                if socket not in active_sockets:
                    continue

                try:
                    raw_message = socket.recv(zmq.NOBLOCK)
                    if not raw_message or len(raw_message) > 5 * 1024 * 1024:
                        continue
                    decompressor = zlib.decompressobj()
                    decompressed_bytes = decompressor.decompress(raw_message, 10 * 1024 * 1024)
                    if decompressor.unconsumed_tail:
                        continue
                    payload = json.loads(decompressed_bytes.decode("utf-8", errors="replace"))

                    header = payload.get("header", {}) or {}
                    message = payload.get("message", {}) or {}
                    schema_ref = payload.get("$schemaRef", "")

                    uploader_id = header.get("uploaderID", "")
                    software_name = header.get("softwareName", "")
                    game_version = header.get("gameversion", "")
                    event_name = message.get("event") or (schema_ref.split("/")[-2] if "/" in schema_ref else "Unknown")
                    star_system = message.get("StarSystem") or message.get("systemName") or message.get("SystemName") or ""
                    station_name = message.get("StationName") or message.get("stationName") or message.get("Name") or ""
                    msg_timestamp = message.get("timestamp") or header.get("gatewayTimestamp") or ""

                    if system and system.lower() not in star_system.lower():
                        continue
                    if station and station.lower() not in station_name.lower():
                        continue
                    if software and software.lower() not in software_name.lower():
                        continue

                    matched_count += 1
                    logger.info("--------------------------------------------------")
                    logger.info(f"🎯 [MATCH #{matched_count}/{limit}] EDDN Event Detected:")
                    logger.info(f"  • Timestamp:   {msg_timestamp}")
                    logger.info(f"  • Software:    {software_name} (version: {game_version})")
                    logger.info(f"  • Event:       {event_name} ({schema_ref})")
                    if star_system:
                        logger.info(f"  • StarSystem:  {star_system}")
                    if station_name:
                        logger.info(f"  • Station:     {station_name}")
                    logger.info(f"  • Uploader ID: {uploader_id}")
                    logger.info("")
                    logger.info("  To capture in debug log, add to config.yaml:")
                    logger.info("  debug_log:")
                    logger.info('    - label: "MyCommanderName"')
                    logger.info("      match:")
                    logger.info(f'        "header.uploaderID": "{uploader_id}"')
                    logger.info("--------------------------------------------------")

                except zmq.Again:
                    continue
                except KeyboardInterrupt:
                    break
                except Exception as error:
                    logger.debug(f"Error parsing probe message: {error}")
                    continue
        except KeyboardInterrupt:
            logger.info("Probe terminated by user.")
        finally:
            with contextlib.suppress(Exception):
                socket.close(linger=0)
            with contextlib.suppress(Exception):
                context.term()
            logger.info("Probe completed.")

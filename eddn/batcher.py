"""In-memory write buffer and atomic PostgreSQL transaction manager for EDDN events.

Accumulates incoming ``TransformedRecord`` objects into per-table micro-batches
and flushes them as parameterized multi-row upserts within single atomic
transactions. Handles timestamp-gated conflict resolution, cascading stale
item deletions for commodity/shipyard/outfitting/bartender service updates,
and Fleet Carrier name enrichment via ``system_signals`` cross-referencing.
"""

import logging
import time
from collections import defaultdict

import psycopg

from .metrics import EDDNMetrics
from .transformers.base import TransformedRecord
from .utils import EDDNUtils


logger = logging.getLogger(__name__)


class EDDNBatcher:
    """Asynchronous in-memory write buffer for micro-batching records and executing upserts.

    Handles timestamp-gated multi-row PostgreSQL upserts, conflict resolution,
    cascading stale item deletions, and carrier name enrichments.
    """

    def __init__(
        self,
        db_conn: psycopg.Connection | None,
        metrics: EDDNMetrics,
        batch_size: int = 200,
        flush_interval_seconds: float = 1.5,
        dry_run: bool = False,
    ) -> None:
        """Initializes the EDDNBatcher instance.

        Args:
            db_conn: Active psycopg connection, or None if dry-run.
            metrics: EDDNMetrics instance for tracking commit rates and table row counts.
            batch_size: Maximum buffered records before an automatic flush is triggered (default: 200).
            flush_interval_seconds: Maximum time in seconds before flushing pending records (default: 1.5).
            dry_run: If True, simulates batching and records metrics without writing to the database.
        """
        self.conn = db_conn
        self.metrics = metrics
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self.dry_run = dry_run

        self._buffer: dict[str, list[TransformedRecord]] = defaultdict(list)
        self._total_buffered = 0
        self._last_flush_time = time.time()

    def add(self, records: list[TransformedRecord]) -> None:
        """Adds records to the in-memory buffer and triggers a flush if thresholds are met.

        Args:
            records: List of TransformedRecord objects to queue for batch upsert.
        """
        for record in records:
            self._buffer[record.table_name].append(record)
            self._total_buffered += 1
            self.metrics.record_records(record.table_name, 1)

        now = time.time()
        if self._total_buffered >= self.batch_size or (now - self._last_flush_time) >= self.flush_interval_seconds:
            self.flush()

    def flush(self, force: bool = False) -> int:
        """Flushes all buffered records to PostgreSQL within a single atomic transaction.

        Args:
            force: Unused parameter kept for API compatibility.

        Returns:
            int: Total number of records committed to the database.

        Raises:
            Exception: Re-raises database exceptions after recording error metrics.
        """
        if self._total_buffered == 0:
            self._last_flush_time = time.time()
            return 0

        flushed_count = 0
        now = time.time()

        if self.dry_run or self.conn is None:
            # Dry-run: update metrics and clear buffer
            flushed_count = self._total_buffered
            self.metrics.record_commit(flushed_count)
            self._buffer.clear()
            self._total_buffered = 0
            self._last_flush_time = now
            return flushed_count

        try:
            with self.conn.transaction(), self.conn.cursor() as cursor:
                for table_name, table_records in self._buffer.items():
                    if not table_records:
                        continue
                    self._flush_table(cursor, table_name, table_records)
                    flushed_count += len(table_records)

            self.metrics.record_commit(flushed_count)
        except Exception as error:
            logger.error(f"Error committing batch to database: {error}", exc_info=True)
            self.metrics.record_error(1)
            # Reconnect or rollback handled by psycopg context manager
            raise
        finally:
            self._buffer.clear()
            self._total_buffered = 0
            self._last_flush_time = time.time()

        return flushed_count

    def _flush_table(
        self,
        cursor: psycopg.Cursor,
        table_name: str,
        records: list[TransformedRecord],
    ) -> None:
        """Generates and executes parameterized bulk upsert queries for a single table."""
        if not records:
            return

        # 1. Simple insert for DLQ table and debug log
        if table_name == "_raw_debug_log":
            columns = [
                "filter_label",
                "software_name",
                "software_version",
                "uploader_id",
                "schema_ref",
                "event_name",
                "message_timestamp",
                "raw_payload",
            ]
            placeholders = ", ".join(["%s"] * len(columns))
            column_names_sql = ", ".join(columns)
            sql = f"INSERT INTO _raw_debug_log ({column_names_sql}) VALUES ({placeholders});"
            params = [[record.data.get(column_name) for column_name in columns] for record in records]
            cursor.executemany(sql, params)
            return

        if table_name == "eddn_unhandled_events":
            columns = [
                "message_timestamp",
                "schema_ref",
                "event_name",
                "system_name",
                "station_name",
                "uploader_id",
                "app_name",
                "dlq_reason",
                "raw_message",
            ]
            placeholders = ", ".join(["%s"] * len(columns))
            column_names_sql = ", ".join(columns)
            sql = f"INSERT INTO eddn_unhandled_events ({column_names_sql}) VALUES ({placeholders});"
            params = [[record.data.get(column_name) for column_name in columns] for record in records]
            cursor.executemany(sql, params)
            return

        # 2. Extract standard columns from first record
        first_record = records[0]
        if first_record.custom_upsert_sql:
            columns = list(first_record.data.keys())
            params = [[record.data.get(column_name) for column_name in columns] for record in records]
            cursor.executemany(first_record.custom_upsert_sql, params)
            return

        key_fields = first_record.key_fields
        timestamp_field = first_record.timestamp_field

        columns = list(first_record.data.keys())
        column_names_sql = ", ".join(columns)

        # Placeholders with special casting for cube coordinates
        value_placeholders = []
        for column_name in columns:
            if column_name == "coords":
                value_placeholders.append("%s::cube")
            else:
                value_placeholders.append("%s")
        values_placeholder_sql = ", ".join(value_placeholders)

        conflict_keys = ", ".join(key_fields)
        key_lower = {key_field.lower() for key_field in key_fields}
        update_columns = [col for col in columns if col.lower() not in key_lower]

        if not update_columns:
            # Table has only key columns
            sql = f"INSERT INTO {table_name} ({column_names_sql}) VALUES ({values_placeholder_sql}) ON CONFLICT ({conflict_keys}) DO NOTHING;"
        elif table_name == "body_signals":
            set_clauses = [
                "system_id64 = COALESCE(EXCLUDED.system_id64, body_signals.system_id64)",
                "signals = COALESCE(EXCLUDED.signals, body_signals.signals)",
                "genuses = CASE WHEN EXCLUDED.genuses IS NOT NULL AND body_signals.genuses IS NOT NULL THEN (SELECT array_agg(DISTINCT x) FROM unnest(body_signals.genuses || EXCLUDED.genuses) t(x)) ELSE COALESCE(EXCLUDED.genuses, body_signals.genuses) END",
                "update_dtm = GREATEST(EXCLUDED.update_dtm, body_signals.update_dtm)",
            ]
            set_sql = ", ".join(set_clauses)
            sql = f"""
                INSERT INTO body_signals ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql};
            """
        elif table_name == "stations":
            set_clauses = []
            for column_name in update_columns:
                if column_name == "system_id64":
                    set_clauses.append(
                        "system_id64 = CASE WHEN EXCLUDED.system_id64 = 0 OR EXCLUDED.system_id64 IS NULL THEN stations.system_id64 ELSE EXCLUDED.system_id64 END"
                    )
                elif column_name in (
                    "market_updated_at",
                    "shipyard_updated_at",
                    "outfitting_updated_at",
                    "bartender_updated_at",
                    "update_dtm",
                ):
                    set_clauses.append(f"{column_name} = GREATEST(EXCLUDED.{column_name}, stations.{column_name})")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, stations.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        elif table_name == "systems":
            set_clauses = []
            for column_name in update_columns:
                if column_name == "name":
                    set_clauses.append("name = EXCLUDED.name")
                elif column_name == "update_dtm":
                    set_clauses.append("update_dtm = GREATEST(EXCLUDED.update_dtm, systems.update_dtm)")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, systems.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        elif table_name == "bodies":
            set_clauses = []
            for column_name in update_columns:
                if column_name == "name":
                    set_clauses.append("name = EXCLUDED.name")
                elif column_name == "update_dtm":
                    set_clauses.append("update_dtm = GREATEST(EXCLUDED.update_dtm, bodies.update_dtm)")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, bodies.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        elif table_name == "body_rings":
            set_clauses = []
            for column_name in update_columns:
                if column_name == "type":
                    set_clauses.append(
                        "type = CASE WHEN EXCLUDED.type IS NOT NULL AND EXCLUDED.type != 'Unknown' THEN EXCLUDED.type ELSE body_rings.type END"
                    )
                elif column_name in ("mass", "innerRadius", "outerRadius"):
                    set_clauses.append(
                        f"{column_name} = CASE WHEN EXCLUDED.{column_name} > 0 THEN EXCLUDED.{column_name} ELSE body_rings.{column_name} END"
                    )
                elif column_name == "density":
                    set_clauses.append("density = CASE WHEN EXCLUDED.density > 0 THEN EXCLUDED.density ELSE body_rings.density END")
                elif column_name == "signals":
                    set_clauses.append("signals = COALESCE(EXCLUDED.signals, body_rings.signals)")
                elif column_name == "id64":
                    set_clauses.append("id64 = COALESCE(EXCLUDED.id64, body_rings.id64)")
                elif column_name == "update_dtm":
                    set_clauses.append("update_dtm = GREATEST(EXCLUDED.update_dtm, body_rings.update_dtm)")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, body_rings.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        elif table_name == "body_belts":
            set_clauses = []
            for column_name in update_columns:
                if column_name == "type":
                    set_clauses.append(
                        "type = CASE WHEN EXCLUDED.type IS NOT NULL AND EXCLUDED.type != 'Unknown' THEN EXCLUDED.type ELSE body_belts.type END"
                    )
                elif column_name in ("mass", "innerRadius", "outerRadius"):
                    set_clauses.append(
                        f"{column_name} = CASE WHEN EXCLUDED.{column_name} > 0 THEN EXCLUDED.{column_name} ELSE body_belts.{column_name} END"
                    )
                elif column_name == "density":
                    set_clauses.append("density = CASE WHEN EXCLUDED.density > 0 THEN EXCLUDED.density ELSE body_belts.density END")
                elif column_name == "update_dtm":
                    set_clauses.append("update_dtm = GREATEST(EXCLUDED.update_dtm, body_belts.update_dtm)")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, body_belts.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        elif table_name == "system_factions":
            set_clauses = []
            for column_name in update_columns:
                if column_name == "state":
                    set_clauses.append("state = EXCLUDED.state")
                elif column_name == "update_dtm":
                    set_clauses.append("update_dtm = GREATEST(EXCLUDED.update_dtm, system_factions.update_dtm)")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, system_factions.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        elif table_name == "system_signals":
            set_clauses = []
            for column_name in update_columns:
                if column_name in ("signal_type", "name", "is_station"):
                    set_clauses.append(f"{column_name} = EXCLUDED.{column_name}")
                elif column_name == "update_dtm":
                    set_clauses.append("update_dtm = GREATEST(EXCLUDED.update_dtm, system_signals.update_dtm)")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, system_signals.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        elif table_name == "body_pois":
            set_clauses = []
            for column_name in update_columns:
                if column_name in ("poi_type", "name"):
                    set_clauses.append(f"{column_name} = EXCLUDED.{column_name}")
                elif column_name == "update_dtm":
                    set_clauses.append("update_dtm = GREATEST(EXCLUDED.update_dtm, body_pois.update_dtm)")
                else:
                    set_clauses.append(f"{column_name} = COALESCE(EXCLUDED.{column_name}, body_pois.{column_name})")
            set_sql = ", ".join(set_clauses)
            where_clause = (
                f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                if timestamp_field
                else ""
            )
            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """
        else:
            # Child tables (station_commodities, station_ships, station_modules, station_materials)
            set_clauses = [f"{column_name}=EXCLUDED.{column_name}" for column_name in update_columns]
            set_sql = ", ".join(set_clauses)

            if timestamp_field and timestamp_field in columns:
                where_clause = (
                    f"WHERE EXCLUDED.{timestamp_field} >= {table_name}.{timestamp_field} OR {table_name}.{timestamp_field} IS NULL"
                )
            else:
                where_clause = ""

            sql = f"""
                INSERT INTO {table_name} ({column_names_sql})
                VALUES ({values_placeholder_sql})
                ON CONFLICT ({conflict_keys}) DO UPDATE SET
                    {set_sql}
                {where_clause};
            """

        params = [[record.data.get(column_name) for column_name in columns] for record in records]
        cursor.executemany(sql, params)

        # 3. Clean up stale delisted items on stations service updates
        if table_name == "stations":
            market_updates = [
                (record.data["market_id"], record.data["market_updated_at"])
                for record in records
                if record.data.get("market_id") and record.data.get("market_updated_at")
            ]
            if market_updates:
                cursor.executemany(
                    "DELETE FROM station_commodities WHERE market_id = %s AND update_dtm < %s::timestamp;",
                    market_updates,
                )

            shipyard_updates = [
                (record.data["market_id"], record.data["shipyard_updated_at"])
                for record in records
                if record.data.get("market_id") and record.data.get("shipyard_updated_at")
            ]
            if shipyard_updates:
                cursor.executemany(
                    "DELETE FROM station_ships WHERE market_id = %s AND update_dtm < %s::timestamp;",
                    shipyard_updates,
                )

            outfitting_updates = [
                (record.data["market_id"], record.data["outfitting_updated_at"])
                for record in records
                if record.data.get("market_id") and record.data.get("outfitting_updated_at")
            ]
            if outfitting_updates:
                cursor.executemany(
                    "DELETE FROM station_modules WHERE market_id = %s AND update_dtm < %s::timestamp;",
                    outfitting_updates,
                )

            bartender_updates = [
                (record.data["market_id"], record.data["bartender_updated_at"])
                for record in records
                if record.data.get("market_id") and record.data.get("bartender_updated_at")
            ]
            if bartender_updates:
                cursor.executemany(
                    "DELETE FROM station_materials WHERE market_id = %s AND update_dtm < %s::timestamp;",
                    bartender_updates,
                )

        elif table_name == "system_signals":
            carrier_updates = []
            for record in records:
                signal_type = record.data.get("signal_type")
                if signal_type in ("FleetCarrier", "SquadronCarrier"):
                    carrier_id, carrier_name, carrier_type = EDDNUtils.extract_carrier_parts(
                        record.data.get("raw_name"), signal_type
                    )
                    if carrier_id and carrier_name:
                        signal_timestamp = record.data.get("update_dtm")
                        carrier_updates.append((carrier_name, signal_timestamp, carrier_id, signal_timestamp))

            if carrier_updates:
                cursor.executemany(
                    """
                    UPDATE stations
                    SET carrierName = %s,
                        update_dtm = GREATEST(stations.update_dtm, %s)
                    WHERE stations.name = %s
                      AND (
                          stations.update_dtm <= %s
                          OR stations.carrierName IS NULL
                          OR stations.carrierName = ''
                      );
                    """,
                    carrier_updates,
                )

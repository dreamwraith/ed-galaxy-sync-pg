"""Live telemetry, unmapped token tracking, and dashboard JSON writer for EDDN sessions.

Maintains real-time counters for message throughput, database commit velocity,
error rates, sender/version filtering, and Dead-Letter Queue routing. Tracks
unmapped normalization tokens per table and field, and exports an atomically
overwriting JSON status dashboard file for external monitoring.
"""

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class EDDNMetrics:
    """Tracks and reports real-time metrics, throughput velocity, and system health for EDDN.

    Maintains an in-memory inventory of unmapped tokens across tables and fields, and exports
    an atomically overwriting dashboard status file.
    """

    def __init__(self) -> None:
        """Initializes metrics counters, timers, and unmapped token tracker."""
        self.start_time = time.time()
        self.last_status_time = self.start_time
        self.messages_received = 0
        self.messages_parsed = 0
        self.records_generated = 0
        self.records_committed = 0
        self.batches_committed = 0
        self.errors_count = 0
        self.dlq_count = 0
        self.filtered_senders_count = 0
        self.filtered_game_versions_count = 0

        self.table_counts: dict[str, int] = defaultdict(int)
        # table -> field -> {raw_val: count}
        self.unmapped_tokens: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        # Rate tracking
        self._last_message_count = 0
        self._last_commit_count = 0

    def record_message(self, count: int = 1) -> None:
        """Increments the count of received ZeroMQ messages.

        Args:
            count: Number of messages received (default: 1).
        """
        self.messages_received += count

    def record_parsed(self, count: int = 1) -> None:
        """Increments the count of successfully parsed JSON messages.

        Args:
            count: Number of messages parsed (default: 1).
        """
        self.messages_parsed += count

    def record_filtered_sender(self, count: int = 1) -> None:
        """Increments the count of messages rejected due to sender whitelist filtering.

        Args:
            count: Number of rejected messages (default: 1).
        """
        self.filtered_senders_count += count

    def record_filtered_game_version(self, count: int = 1) -> None:
        """Increments the count of messages rejected due to legacy game version gating.

        Args:
            count: Number of rejected messages (default: 1).
        """
        self.filtered_game_versions_count += count

    def record_records(self, table_name: str, count: int = 1) -> None:
        """Records generated TransformedRecord instances for a destination table.

        Args:
            table_name: Destination database table name.
            count: Number of records generated (default: 1).
        """
        self.records_generated += count
        self.table_counts[table_name] += count
        if table_name == "eddn_unhandled_events":
            self.dlq_count += count

    def record_commit(self, record_count: int) -> None:
        """Records a successful micro-batch database transaction commit.

        Args:
            record_count: Number of records committed in the batch.
        """
        self.batches_committed += 1
        self.records_committed += record_count

    def record_error(self, count: int = 1) -> None:
        """Increments the processing or database error counter.

        Args:
            count: Number of errors encountered (default: 1).
        """
        self.errors_count += count

    def record_unmapped(self, table: str, field: str, raw_value: str | None) -> None:
        """Records an occurrence of an unmapped token for a specific table and field.

        Args:
            table: Target database table name.
            field: Target column name.
            raw_value: Raw token string that could not be mapped.
        """
        if raw_value and raw_value.strip():
            self.unmapped_tokens[table][field][raw_value.strip()] += 1

    def get_unmapped_summary(self) -> dict[str, dict[str, dict[str, int]]]:
        """Returns a serializable nested dictionary of all recorded unmapped tokens.

        Returns:
            dict[str, dict[str, dict[str, int]]]: Mapping of table -> field -> {token: count}.
        """
        result: dict[str, dict[str, dict[str, int]]] = {}
        for table, fields in self.unmapped_tokens.items():
            result[table] = {}
            for field, token_counts in fields.items():
                result[table][field] = dict(sorted(token_counts.items(), key=lambda item: item[1], reverse=True))
        return result

    def get_status_dict(self) -> dict[str, Any]:
        """Builds a complete dictionary snapshot of current metrics, rates, and unmapped tokens.

        Returns:
            dict[str, Any]: Structured status dictionary.
        """
        now = time.time()
        elapsed = max(now - self.start_time, 0.001)
        interval = max(now - self.last_status_time, 0.001)

        messages_per_second = (self.messages_received - self._last_message_count) / interval
        commits_per_second = (self.records_committed - self._last_commit_count) / interval

        active_tables = {table_name: count for table_name, count in self.table_counts.items() if count > 0}
        unmapped_data = self.get_unmapped_summary()
        total_unmapped_unique = sum(len(token_counts) for fields in unmapped_data.values() for token_counts in fields.values())

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "uptime_seconds": round(elapsed, 1),
            "velocity": {
                "messages_per_sec": round(messages_per_second, 2),
                "db_commits_per_sec": round(commits_per_second, 2),
            },
            "totals": {
                "messages_received": self.messages_received,
                "messages_parsed": self.messages_parsed,
                "records_generated": self.records_generated,
                "records_committed": self.records_committed,
                "batches_committed": self.batches_committed,
                "errors_count": self.errors_count,
                "dlq_count": self.dlq_count,
                "filtered_senders_count": self.filtered_senders_count,
                "filtered_game_versions_count": self.filtered_game_versions_count,
                "total_unmapped_token_variants": total_unmapped_unique,
            },
            "table_breakdown": active_tables,
            "unmapped_tokens": unmapped_data,
        }

    def get_summary_line(self) -> str:
        """Builds a concise one-line formatted status string for console reporting.

        Returns:
            str: Single-line status banner.
        """
        now = time.time()
        interval = max(now - self.last_status_time, 0.001)

        messages_per_second = (self.messages_received - self._last_message_count) / interval
        commits_per_second = (self.records_committed - self._last_commit_count) / interval

        self._last_message_count = self.messages_received
        self._last_commit_count = self.records_committed
        self.last_status_time = now

        active_tables = sorted(
            [
                (table_name, count)
                for table_name, count in self.table_counts.items()
                if count > 0 and table_name != "eddn_unhandled_events"
            ],
            key=lambda item: item[1],
            reverse=True,
        )
        table_str = ", ".join([f"{table_name}:{count:,}" for table_name, count in active_tables]) if active_tables else "none"

        filter_details = []
        if self.filtered_senders_count > 0:
            filter_details.append(f"Unapproved Senders: {self.filtered_senders_count:,}")
        if self.filtered_game_versions_count > 0:
            filter_details.append(f"Filtered Versions: {self.filtered_game_versions_count:,}")
        filters_str = f" | {', '.join(filter_details)}" if filter_details else ""

        total_unmapped = sum(len(token_counts) for fields in self.unmapped_tokens.values() for token_counts in fields.values())
        unmapped_str = f" | Unmapped Variants: {total_unmapped}" if total_unmapped > 0 else ""

        return (
            f"[EDDN Live] Msg Rate: {messages_per_second:5.1f}/s | "
            f"DB Upsert Rate: {commits_per_second:5.1f} rows/s | "
            f"Total Msgs: {self.messages_received:,} | "
            f"Committed: {self.records_committed:,} | "
            f"DLQ: {self.dlq_count:,}{filters_str}{unmapped_str} | "
            f"Errors: {self.errors_count} | "
            f"Tables ({table_str})"
        )

    def write_status_dashboard(self, file_path: str | Path) -> None:
        """Atomically writes or overwrites the status dashboard JSON file.

        Args:
            file_path: Target JSON file path.
        """
        if not file_path:
            return
        try:
            target_path = Path(file_path).resolve()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            status_data = self.get_status_dict()
            temp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
            temp_path.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
            temp_path.replace(target_path)
        except Exception as error:
            logger.warning(f"Failed to write status dashboard to '{file_path}': {error}")

    def log_status(
        self,
        logger: logging.Logger | None = None,
        status_file_path: str | None = None,
        print_console: bool = True,
    ) -> None:
        """Logs current summary line to console and writes status dashboard JSON if configured.

        Args:
            logger: Optional logging.Logger instance.
            status_file_path: Optional JSON file path to write dashboard status.
            print_console: Whether to print summary line to stdout (default: True).
        """
        if print_console:
            print(self.get_summary_line(), flush=True)
        if status_file_path:
            self.write_status_dashboard(status_file_path)

    def get_human_readable_summary(self) -> str:
        """Formats a multi-line human-readable summary of session metrics.

        Returns:
            str: Multi-line formatted session summary string.
        """
        status = self.get_status_dict()
        totals = status["totals"]
        tables = status["table_breakdown"]
        unmapped = status["unmapped_tokens"]

        lines = [
            "==================================================================",
            "                 EDDN LISTENER SESSION SUMMARY                    ",
            "==================================================================",
            f"Uptime:                  {status['uptime_seconds']:.1f} seconds",
            f"Messages Received:       {totals['messages_received']:,}",
            f"Messages Parsed:         {totals['messages_parsed']:,}",
            f"Records Generated:       {totals['records_generated']:,}",
            f"Records Committed:       {totals['records_committed']:,}",
            f"Batches Committed:       {totals['batches_committed']:,}",
            f"Errors Count:            {totals['errors_count']:,}",
            f"DLQ Unhandled Events:    {totals['dlq_count']:,}",
            f"Filtered Senders:        {totals['filtered_senders_count']:,}",
            f"Filtered Game Versions:  {totals['filtered_game_versions_count']:,}",
            f"Total Unmapped Variants: {totals['total_unmapped_token_variants']:,}",
            "------------------------------------------------------------------",
            "Table Breakdown:",
        ]
        if tables:
            for table_name, count in sorted(tables.items(), key=lambda item: item[1], reverse=True):
                lines.append(f"  - {table_name:<25}: {count:,} rows")
        else:
            lines.append("  (none)")

        lines.append("------------------------------------------------------------------")
        lines.append("Top Unmapped Tokens by Field:")
        has_unmapped = False
        for table_name, fields in unmapped.items():
            for field, tokens in fields.items():
                if tokens:
                    has_unmapped = True
                    top_5 = list(tokens.items())[:5]
                    tokens_str = ", ".join([f"'{token_key}' ({token_count:,})" for token_key, token_count in top_5])
                    lines.append(f"  - {table_name}.{field}: {tokens_str}")
        if not has_unmapped:
            lines.append("  (none)")

        lines.append("==================================================================")
        return "\n".join(lines)

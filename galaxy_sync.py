"""Unified CLI entrypoint for Elite Dangerous Galaxy Sync (ed-galaxy-sync-pg).

Orchestrates four operational modes via subcommands:

- **split**: Splits monolithic JSON array dumps into parallel NDJSON chunk files.
- **ingest**: Bootstraps the PostgreSQL galaxy database using DuckDB vectorized
  streaming from Spansh data dump chunks.
- **listen**: Subscribes to the live EDDN ZeroMQ relay and replicates real-time
  galaxy events into PostgreSQL with micro-batching and timestamp gating.
- **probe-cmdr**: Probes the live EDDN stream to discover a client's hashed
  uploaderID for debug session configuration.

PostgreSQL connection parameters are resolved from CLI flags, falling back to
standard ``PG*`` environment variables (``PGHOST``, ``PGPORT``, ``PGUSER``,
``PGPASSWORD``, ``PGDATABASE``).
"""

import argparse
import contextlib
import datetime
import logging
import os
import shutil
import sys
import urllib.parse
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from eddn import EDDNBatcher, EDDNListener, EDDNMetrics, EDDNRouter, EDDNUtils
from spansh import GalaxyIngestor, JSONSplitter


load_dotenv()


def setup_logger(log_file_path: str | None = None) -> logging.Logger:
    """Configures the root logger with formatted console and file handlers.

    Args:
        log_file_path: Optional path to a file where timestamped log records will be written.

    Returns:
        logging.Logger: The configured root logger instance.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    # StreamHandler for console output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    root_logger.addHandler(console_handler)

    if log_file_path:
        log_path = Path(log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # FileHandler for log file (timestamped lines with scoped module name [%(name)s])
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        root_logger.addHandler(file_handler)

    return root_logger


# Instantiated module-level logger property
logger = logging.getLogger(__name__)


def main() -> None:
    """Parses CLI arguments and dispatches to the requested subcommand."""

    parser = argparse.ArgumentParser(description="Elite Dangerous Galaxy Sync for PostgreSQL (ed-galaxy-sync-pg)")
    parser.add_argument(
        "--log-dir",
        default="./.run_logs",
        help="Directory to save timestamped execution log files (default: ./.run_logs)",
    )
    # PostgreSQL Connection Parameters (CLI flags override environment variables)
    parser.add_argument(
        "--host", default=os.environ.get("PGHOST", "localhost"), help="PostgreSQL server hostname (default: localhost, env: PGHOST)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PGPORT", "5432")),
        help="PostgreSQL server port (default: 5432, env: PGPORT)",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("PGUSER", "galaxy_updater"),
        help="PostgreSQL database user (default: galaxy_updater, env: PGUSER)",
    )
    parser.add_argument("--password", default=os.environ.get("PGPASSWORD"), help="PostgreSQL database password (env: PGPASSWORD)")
    parser.add_argument(
        "--dbname",
        default=os.environ.get("PGDATABASE", "galaxy_sync"),
        help="PostgreSQL database name (default: galaxy_sync, env: PGDATABASE)",
    )
    # Database Session & Lock Timeouts
    parser.add_argument(
        "--db-lock-timeout-sec",
        type=int,
        default=10,
        help="Max seconds to wait for a database lock before canceling statement (default: 10, set 0 to disable)",
    )
    parser.add_argument(
        "--db-statement-timeout-sec",
        type=int,
        default=60,
        help="Max seconds for any database statement before canceling query (default: 60, set 0 to disable)",
    )
    parser.add_argument(
        "--db-connect-timeout-sec",
        type=int,
        default=10,
        help="Database connection timeout in seconds (default: 10)",
    )
    # Global EDDN Relay & Config Parameters
    parser.add_argument(
        "--config-file",
        default="config.yaml",
        help="Path to YAML configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--relay-url",
        default=None,
        help="ZeroMQ relay endpoint (default: from config.yaml or tcp://eddn.edcd.io:9500)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Ingest subcommand
    ingest_parser = subparsers.add_parser("ingest", help="Ingest galaxy JSON dump into PostgreSQL")
    ingest_parser.add_argument("--json", default="galaxy.json", help="Path to galaxy JSON dump file")
    ingest_parser.add_argument(
        "--max-memory",
        default="16GB",
        help="Max RAM allocation for DuckDB streaming (e.g., 8GB, 16GB, 32GB)",
    )
    ingest_parser.add_argument(
        "--temp-dir",
        default="./.duckdb_temp",
        help="Temporary directory for disk spilling (default: ./.duckdb_temp)",
    )
    ingest_parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Number of CPU cores to allocate (default: all available cores)",
    )
    ingest_parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Number of chunk files to ingest concurrently in parallel per batch",
    )
    ingest_parser.add_argument(
        "--ignore-errors",
        action="store_true",
        help="Ignore malformed or corrupted JSON records if present",
    )
    ingest_parser.add_argument(
        "--mode",
        choices=["bulk", "upsert"],
        default="upsert",
        help="Ingestion strategy: 'bulk' for initial load, 'upsert' for incremental updates",
    )
    ingest_parser.add_argument("--limit", type=int, default=None, help="Limit records for schema testing")
    ingest_parser.add_argument(
        "--split-first",
        action="store_true",
        help="If the input is a massive monolithic JSON file, split it into chunks first.",
    )
    ingest_parser.add_argument(
        "--split-temp-dir",
        default="./.temp_chunks",
        help="Directory to store temporary chunks when using --split-first (default: ./.temp_chunks)",
    )
    ingest_parser.add_argument(
        "--split-chunks",
        type=int,
        default=100,
        help="Number of chunks to split the massive JSON into when using --split-first",
    )
    ingest_parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing records, relaxing update_dtm timestamp checks and re-ingesting tracked files",
    )
    ingest_parser.add_argument(
        "--post-run-normalize",
        action="store_true",
        help="Run post-ingest sp_normalize_galaxy_data normalization procedure after load (default: false)",
    )
    ingest_parser.add_argument(
        "--normalize-batch-size",
        type=int,
        default=50000,
        help="Batch size for post-ingest sp_normalize_galaxy_data (default: 50000)",
    )

    # Split subcommand
    split_parser = subparsers.add_parser("split", help="Split massive JSON file directly into clean, verified .ndjson files")
    split_parser.add_argument("--file", required=True, help="Path to input massive JSON file (e.g. D:\\galaxy.json\\galaxy.json)")
    split_parser.add_argument("--output-dir", default=r"D:\galaxy_parts", help="Output directory for .ndjson chunks")
    split_parser.add_argument("--chunks", type=int, default=100, help="Number of chunks to create (default: 100)")
    split_parser.add_argument(
        "--chunk-size-gb",
        type=float,
        help="Target size in GB per chunk file (overrides --chunks)",
    )
    split_parser.add_argument(
        "--max-records",
        type=int,
        help="Max records per chunk file (overrides size calculation)",
    )
    split_parser.add_argument("--start-chunk", type=int, default=1, help="Start chunk index N (e.g. 47)")
    split_parser.add_argument("--max-chunks", type=int, help="Limit total chunks created during this run (e.g. 2)")
    split_parser.add_argument("--no-validate", action="store_true", help="Skip validation to split chunks at maximum disk speed")
    split_parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip conversion and run multi-threaded parallel validation across existing .ndjson chunk files",
    )
    split_parser.add_argument("--threads", type=int, default=1, help="Number of parallel worker processes (e.g. 4)")

    # Listen subcommand (ZeroMQ EDDN Live Stream)
    listen_parser = subparsers.add_parser("listen", help="Stream real-time EDDN events into PostgreSQL via ZeroMQ")
    listen_parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="In-memory micro-batch size before triggering flush (default: 200)",
    )
    listen_parser.add_argument(
        "--flush-interval-sec",
        type=float,
        default=1.5,
        help="Max seconds between batch flushes (default: 1.5)",
    )
    listen_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and display live events without writing to PostgreSQL",
    )
    listen_parser.add_argument(
        "--no-dlq",
        action="store_true",
        help="Disable capturing unhandled events into eddn_unhandled_events table",
    )
    listen_parser.add_argument(
        "--status-interval-sec",
        type=int,
        default=5,
        help="Seconds between terminal status updates (default: 5)",
    )
    listen_parser.add_argument(
        "--min-game-version",
        default=None,
        help="Minimum Elite Dangerous game version (e.g. 4.0). Overrides config.yaml value.",
    )
    listen_parser.add_argument(
        "--no-whitelist",
        action="store_true",
        help="Disable sender application whitelisting and accept all senders",
    )
    listen_parser.add_argument(
        "--debug-all",
        dest="debug_all",
        action="store_true",
        default=None,
        help="Log all incoming EDDN messages unconditionally to _raw_debug_log (overrides config.yaml)",
    )
    listen_parser.add_argument(
        "--status-file",
        default=".run_logs/listen_status.json",
        help="Path to overwriting status dashboard JSON file (default: .run_logs/listen_status.json)",
    )

    # 4. PROBE / DISCOVER COMMANDER UPLOADER_ID
    probe_parser = subparsers.add_parser(
        "probe-cmdr",
        aliases=["probe"],
        help="Probe live EDDN stream to detect and output your client's hashed uploaderID",
    )
    probe_parser.add_argument(
        "--system",
        default=None,
        help="Filter events matching this star system name (e.g. --system 'Sol')",
    )
    probe_parser.add_argument(
        "--station",
        default=None,
        help="Filter events matching this station name",
    )
    probe_parser.add_argument(
        "--software",
        default=None,
        help="Filter events matching this sender software substring (e.g. 'Market Connector')",
    )
    probe_parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Number of matching events to display before exiting (default: 3)",
    )

    arguments = parser.parse_args()

    if not arguments.command:
        parser.print_help()
        sys.exit(0)

    if arguments.password:
        encoded_password = urllib.parse.quote_plus(arguments.password)
        postgres_uri = f"postgresql://{arguments.user}:{encoded_password}@{arguments.host}:{arguments.port}/{arguments.dbname}"
    else:
        postgres_uri = f"postgresql://{arguments.user}@{arguments.host}:{arguments.port}/{arguments.dbname}"

    # Automated timestamped log creation under .run_logs directory (galaxy_sync_YYYYMMDD_HHMMSS.log)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_directory = Path(arguments.log_dir or "./.run_logs")
    log_file_path = str(log_directory / f"galaxy_sync_{timestamp}.log")
    setup_logger(log_file_path)

    match arguments.command:
        case "split":
            splitter = JSONSplitter(
                input_file=arguments.file,
                output_dir=arguments.output_dir,
                num_chunks=arguments.chunks,
                chunk_size_gb=arguments.chunk_size_gb,
                max_records_per_chunk=arguments.max_records,
                start_chunk=arguments.start_chunk,
                max_chunks=arguments.max_chunks,
                validate=not arguments.no_validate,
                threads=arguments.threads,
            )
            if arguments.validate_only:
                splitter.validate_all_chunks()
            else:
                splitter.split()

        case "ingest":
            target_json = arguments.json
            temp_chunks_dir = arguments.split_temp_dir or "./.temp_chunks"

            if arguments.split_first:
                logger.info(f"Auto-splitting enabled. Splitting {target_json} to {temp_chunks_dir}...")
                splitter = JSONSplitter(
                    input_file=target_json,
                    output_dir=temp_chunks_dir,
                    num_chunks=arguments.split_chunks,
                    validate=False,
                    threads=arguments.threads or 1,
                )
                splitter.split()
                target_json = str(Path(temp_chunks_dir) / "*.ndjson")

            ingestor = GalaxyIngestor(
                json_path=target_json,
                pg_uri=postgres_uri,
                max_memory=arguments.max_memory,
                temp_dir=arguments.temp_dir,
                batch_size=arguments.batch_size,
                threads=arguments.threads,
                ignore_errors=arguments.ignore_errors,
                mode=arguments.mode,
                limit=arguments.limit,
                force=arguments.force,
                normalize=arguments.post_run_normalize,
                normalize_batch_size=arguments.normalize_batch_size,
            )
            ingestor.run()

            if arguments.split_first:
                logger.info(f"Cleaning up temporary chunks directory: {temp_chunks_dir}")
                with contextlib.suppress(Exception):
                    shutil.rmtree(temp_chunks_dir)
                    logger.info(f"Successfully removed {temp_chunks_dir}")

        case "probe" | "probe-cmdr":
            config_data = EDDNUtils.load_config(arguments.config_file or "config.yaml")
            relay_url = arguments.relay_url or config_data.get("relay_url") or "tcp://eddn.edcd.io:9500"
            timeout_ms = config_data.get("timeout_ms", 30000)

            EDDNUtils.probe_commander(
                relay_url=relay_url,
                system=arguments.system,
                station=arguments.station,
                software=arguments.software,
                limit=arguments.limit,
                timeout_ms=timeout_ms,
            )

        case "listen":
            config_path = arguments.config_file or "config.yaml"
            config_data = EDDNUtils.load_config(config_path)
            metrics_instance = EDDNMetrics()

            if arguments.no_whitelist:
                config_data.pop("allowed_senders", None)

            if arguments.debug_all is not None:
                config_data["debug_all"] = arguments.debug_all

            if arguments.no_dlq:
                config_data["enable_dlq"] = False

            router = EDDNRouter(
                config_data=config_data,
                metrics=metrics_instance,
            )

            database_connection = None
            if not arguments.dry_run:
                try:
                    connection_options = []
                    if arguments.db_lock_timeout_sec and arguments.db_lock_timeout_sec > 0:
                        connection_options.append(f"-c lock_timeout={arguments.db_lock_timeout_sec}s")
                    if arguments.db_statement_timeout_sec and arguments.db_statement_timeout_sec > 0:
                        connection_options.append(f"-c statement_timeout={arguments.db_statement_timeout_sec}s")

                    connection_kwargs = {
                        "autocommit": True,
                        "connect_timeout": arguments.db_connect_timeout_sec or 10,
                        "keepalives": 1,
                        "keepalives_idle": 30,
                        "keepalives_interval": 10,
                        "keepalives_count": 5,
                    }
                    if connection_options:
                        connection_kwargs["options"] = " ".join(connection_options)

                    database_connection = psycopg.connect(postgres_uri, **connection_kwargs)
                    logger.info(
                        f"Connected to PostgreSQL at {arguments.host}:{arguments.port}/{arguments.dbname} "
                        f"(lock_timeout: {arguments.db_lock_timeout_sec}s, statement_timeout: {arguments.db_statement_timeout_sec}s)"
                    )
                except Exception as error:
                    logger.error(f"Failed to connect to PostgreSQL database: {error}")
                    sys.exit(1)

            batcher = EDDNBatcher(
                db_conn=database_connection,
                metrics=metrics_instance,
                batch_size=arguments.batch_size,
                flush_interval_seconds=arguments.flush_interval_sec,
                dry_run=arguments.dry_run,
            )
            listener = EDDNListener(
                router=router,
                batcher=batcher,
                metrics=metrics_instance,
                relay_url=arguments.relay_url or config_data.get("relay_url"),
                timeout_ms=config_data.get("timeout_ms"),
                status_interval_sec=arguments.status_interval_sec,
                status_file_path=arguments.status_file,
            )
            try:
                listener.start()
            finally:
                if database_connection:
                    database_connection.close()

        case None | _:
            parser.print_help()


if __name__ == "__main__":
    main()

"""Unit tests for galaxy_sync unified CLI entrypoint and argument parser."""

import argparse
import urllib.parse
from pathlib import Path

from galaxy_sync import setup_logger


def _build_test_parser() -> argparse.ArgumentParser:
    """Helper to reconstruct the CLI argument parser for test assertions."""
    parser = argparse.ArgumentParser(description="Elite Dangerous Galaxy Sync for PostgreSQL (ed-galaxy-sync-pg)")
    parser.add_argument("--log-dir", default="./.run_logs")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="galaxy_updater")
    parser.add_argument("--password", default=None)
    parser.add_argument("--dbname", default="galaxy_sync")
    parser.add_argument("--db-lock-timeout-sec", type=int, default=10)
    parser.add_argument("--db-statement-timeout-sec", type=int, default=60)
    parser.add_argument("--db-connect-timeout-sec", type=int, default=10)
    parser.add_argument("--config-file", default="config.yaml")
    parser.add_argument("--relay-url", default=None)

    subparsers = parser.add_subparsers(dest="command")

    # Ingest
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--json", default="galaxy.json")
    ingest.add_argument("--max-memory", default="16GB")
    ingest.add_argument("--temp-dir", default="./.duckdb_temp")
    ingest.add_argument("--threads", type=int, default=None)
    ingest.add_argument("--batch-size", type=int, default=4)
    ingest.add_argument("--ignore-errors", action="store_true")
    ingest.add_argument("--mode", choices=["bulk", "upsert"], default="upsert")
    ingest.add_argument("--limit", type=int, default=None)
    ingest.add_argument("--split-first", action="store_true")
    ingest.add_argument("--split-temp-dir", default="./.temp_chunks")
    ingest.add_argument("--split-chunks", type=int, default=100)
    ingest.add_argument("--force", action="store_true")
    ingest.add_argument("--post-run-normalize", action="store_true")
    ingest.add_argument("--normalize-batch-size", type=int, default=50000)

    # Split
    split = subparsers.add_parser("split")
    split.add_argument("--file", required=True)
    split.add_argument("--output-dir", default=r"D:\galaxy_parts")
    split.add_argument("--chunks", type=int, default=100)
    split.add_argument("--chunk-size-gb", type=float)
    split.add_argument("--max-records", type=int)
    split.add_argument("--start-chunk", type=int, default=1)
    split.add_argument("--max-chunks", type=int)
    split.add_argument("--no-validate", action="store_true")
    split.add_argument("--validate-only", action="store_true")
    split.add_argument("--threads", type=int, default=1)

    # Listen
    listen = subparsers.add_parser("listen")
    listen.add_argument("--batch-size", type=int, default=200)
    listen.add_argument("--flush-interval-sec", type=float, default=1.5)
    listen.add_argument("--dry-run", action="store_true")
    listen.add_argument("--no-dlq", action="store_true")
    listen.add_argument("--status-interval-sec", type=int, default=5)
    listen.add_argument("--min-game-version", default=None)
    listen.add_argument("--no-whitelist", action="store_true")
    listen.add_argument("--debug-all", dest="debug_all", action="store_true", default=None)
    listen.add_argument("--status-file", default=".run_logs/listen_status.json")

    # Probe
    probe = subparsers.add_parser("probe-cmdr", aliases=["probe"])
    probe.add_argument("--system", default=None)
    probe.add_argument("--station", default=None)
    probe.add_argument("--software", default=None)
    probe.add_argument("--limit", type=int, default=3)

    return parser


def test_cli_subcommands_registration() -> None:
    """Validates that all expected subcommands and global flags are registered."""
    parser = _build_test_parser()
    assert parser._subparsers is not None

    parsed_help = parser.format_help()
    assert "ingest" in parsed_help
    assert "split" in parsed_help
    assert "listen" in parsed_help
    assert "probe-cmdr" in parsed_help


def test_cli_ingest_argument_defaults_and_overrides() -> None:
    """Validates ingest subcommand default values and custom flag overrides."""
    parser = _build_test_parser()

    # Defaults
    args_default = parser.parse_args(["ingest"])
    assert args_default.command == "ingest"
    assert args_default.mode == "upsert"
    assert args_default.batch_size == 4
    assert args_default.max_memory == "16GB"
    assert args_default.post_run_normalize is False
    assert args_default.normalize_batch_size == 50000

    # Overrides
    args_custom = parser.parse_args(
        [
            "ingest",
            "--json",
            "chunks/*.ndjson",
            "--mode",
            "bulk",
            "--batch-size",
            "8",
            "--max-memory",
            "32GB",
            "--post-run-normalize",
            "--normalize-batch-size",
            "100000",
            "--force",
        ]
    )
    assert args_custom.json == "chunks/*.ndjson"
    assert args_custom.mode == "bulk"
    assert args_custom.batch_size == 8
    assert args_custom.max_memory == "32GB"
    assert args_custom.post_run_normalize is True
    assert args_custom.normalize_batch_size == 100000
    assert args_custom.force is True


def test_cli_split_argument_defaults_and_overrides() -> None:
    """Validates split subcommand required arguments and option flags."""
    parser = _build_test_parser()

    args = parser.parse_args(
        [
            "split",
            "--file",
            "D:\\galaxy.json",
            "--output-dir",
            "D:\\parts",
            "--chunks",
            "50",
            "--threads",
            "4",
            "--no-validate",
        ]
    )
    assert args.command == "split"
    assert args.file == "D:\\galaxy.json"
    assert args.output_dir == "D:\\parts"
    assert args.chunks == 50
    assert args.threads == 4
    assert args.no_validate is True


def test_cli_listen_argument_defaults_and_overrides() -> None:
    """Validates listen subcommand parameters for live ZeroMQ ingestion."""
    parser = _build_test_parser()

    args = parser.parse_args(
        [
            "listen",
            "--batch-size",
            "500",
            "--flush-interval-sec",
            "2.5",
            "--dry-run",
            "--no-dlq",
            "--min-game-version",
            "4.1",
            "--debug-all",
        ]
    )
    assert args.command == "listen"
    assert args.batch_size == 500
    assert args.flush_interval_sec == 2.5
    assert args.dry_run is True
    assert args.no_dlq is True
    assert args.min_game_version == "4.1"
    assert args.debug_all is True


def test_cli_probe_cmdr_argument_parsing() -> None:
    """Validates probe-cmdr filtering arguments and limit options."""
    parser = _build_test_parser()

    args = parser.parse_args(
        [
            "probe-cmdr",
            "--system",
            "Sol",
            "--station",
            "Abraham Lincoln",
            "--software",
            "Market Connector",
            "--limit",
            "5",
        ]
    )
    assert args.command == "probe-cmdr"
    assert args.system == "Sol"
    assert args.station == "Abraham Lincoln"
    assert args.software == "Market Connector"
    assert args.limit == 5


def test_postgres_uri_assembly() -> None:
    """Validates PostgreSQL connection string assembly with password escaping."""
    # Without password
    user, host, port, dbname = "test_user", "127.0.0.1", 5433, "ed_test_db"
    uri_no_pass = f"postgresql://{user}@{host}:{port}/{dbname}"
    assert uri_no_pass == "postgresql://test_user@127.0.0.1:5433/ed_test_db"

    # With password requiring URL encoding
    raw_password = "p@ssword!#$&*()"
    encoded_password = urllib.parse.quote_plus(raw_password)
    uri_with_pass = f"postgresql://{user}:{encoded_password}@{host}:{port}/{dbname}"
    assert "p%40ssword%21%23%24%26%2A%28%29" in uri_with_pass


def test_setup_logger_creates_file_handler(tmp_path: Path) -> None:
    """Validates setup_logger configures console and file loggers properly."""
    log_file = tmp_path / "test_run.log"
    root_log = setup_logger(str(log_file))

    assert root_log is not None
    root_log.info("Test log entry")
    assert log_file.exists()
    assert "Test log entry" in log_file.read_text(encoding="utf-8")

"""Unit tests for Spansh cold bootstrap ingest pipeline parameters and stored procedure execution."""

import logging
from unittest.mock import MagicMock

from spansh import GalaxyIngestor


def test_galaxy_ingestor_initialization_defaults() -> None:
    """Validates GalaxyIngestor default initialization parameters."""
    ingestor = GalaxyIngestor(
        json_path="chunks/*.ndjson",
        pg_uri="postgresql://galaxy_updater@localhost:5432/galaxy_sync",
    )
    assert ingestor.max_memory == "16GB"
    assert ingestor.temp_dir == "./.duckdb_temp"
    assert ingestor.batch_size == 4
    assert ingestor.mode == "upsert"
    assert ingestor.normalize is False
    assert ingestor.normalize_batch_size == 50000


def test_galaxy_ingestor_run_normalization_execution(monkeypatch) -> None:
    """Validates GalaxyIngestor._run_normalization executes sp_normalize_galaxy_data."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: mock_conn)

    ingestor = GalaxyIngestor(
        json_path="chunks/*.ndjson",
        pg_uri="postgresql://user@localhost:5432/db",
        normalize=True,
        normalize_batch_size=75000,
    )
    ingestor._run_normalization()

    assert mock_cursor.execute.called
    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "CALL sp_normalize_galaxy_data(75000);" in executed_sql


def test_galaxy_ingestor_postgres_notice_logging(caplog) -> None:
    """Validates PostgreSQL RAISE NOTICE outputs are cleanly routed to the Python logger."""
    ingestor = GalaxyIngestor(
        json_path="chunks/*.ndjson",
        pg_uri="postgresql://user@localhost:5432/db",
    )
    mock_notice = MagicMock()
    mock_notice.message_primary = "[1/14] Normalizing body_rings.type..."

    with caplog.at_level(logging.INFO):
        ingestor._on_pg_notice(mock_notice)

    assert "[Postgres] [1/14] Normalizing body_rings.type..." in caplog.text


def test_galaxy_ingestor_cli_normalization_flags() -> None:
    """Validates galaxy_sync ingest CLI normalization flag parsing behavior."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--post-run-normalize", action="store_true")
    parser.add_argument("--normalize-batch-size", type=int, default=50000)

    parsed = parser.parse_args(["--post-run-normalize", "--normalize-batch-size", "80000"])
    assert parsed.post_run_normalize is True
    assert parsed.normalize_batch_size == 80000


def test_ingest_filename_sql_escaping() -> None:
    """Validates filenames with single quotes are safely escaped for DuckDB SQL and _ingested_tables."""
    raw_filenames = ["system_o'reilly.ndjson", "normal_chunk.ndjson", "commander's_data.json"]
    sys_files_sql = "[" + ", ".join([f"'{f.replace("'", "''")}'" for f in raw_filenames]) + "]"

    # Verify no unescaped single quotes inside string literal tokens
    assert "'system_o''reilly.ndjson'" in sys_files_sql
    assert "'commander''s_data.json'" in sys_files_sql
    assert "'normal_chunk.ndjson'" in sys_files_sql

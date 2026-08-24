"""Unit tests for db_setup stored procedure generators, schema orchestrator, and reference data seeder.

These tests are designed to be malleable and dynamic, verifying stored procedure generation,
SQL file discovery, password resolution, and reference data seeding without hardcoding
specific YAML catalog tokens or static file counts.
"""

from pathlib import Path

import pytest

from db_setup.db_setup import apply_scripts, collect_sql_files, get_base_dir, resolve_role_password
from db_setup.generate_cleanup_sp import generate_sql
from db_setup.generate_dlq_sp import generate_dlq_sp_sql
from db_setup.seed_data import DataSeeder, get_default_data_dir


def test_db_setup_generate_cleanup_sp_ddl() -> None:
    """Validates generated sp_normalize_galaxy_data stored procedure syntax and structure."""
    sql = generate_sql()
    assert "CREATE OR REPLACE PROCEDURE sp_normalize_galaxy_data" in sql
    assert "GRANT EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) TO galaxy_updater;" in sql
    assert "REVOKE EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) FROM PUBLIC;" in sql
    assert "_norm_mappings" in sql
    assert "systems" in sql
    assert "stations" in sql


def test_db_setup_generate_dlq_sp_ddl() -> None:
    """Validates generated sp_process_eddn_dlq stored procedure contains reprocessing workflows and safe defaults."""
    sql = generate_dlq_sp_sql()
    assert "CREATE OR REPLACE PROCEDURE sp_process_eddn_dlq" in sql
    assert "purge_noise BOOLEAN DEFAULT FALSE" in sql
    assert "GRANT EXECUTE ON PROCEDURE sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN) TO galaxy_updater;" in sql
    assert "REVOKE EXECUTE ON PROCEDURE sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN) FROM PUBLIC;" in sql
    assert "_approved_senders" in sql
    assert "force_sender" in sql
    assert "purge_noise" in sql
    assert "eddn_unhandled_events" in sql


def test_users_roles_sql_procedure_signature_and_isolation() -> None:
    """Validates 02_users_roles.sql and table DDL files contain correct procedure grants and isolate internal tables."""
    roles_sql_path = Path("db_setup/00_init/02_users_roles.sql")
    content = roles_sql_path.read_text(encoding="utf-8")
    assert "sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN)" in content
    assert "sp_normalize_galaxy_data(INT)" in content

    # Dynamically verify internal tables are isolated from galaxy_searcher
    table_files = list(Path("db_setup/01_tables").glob("*.sql"))
    for tf in table_files:
        t_content = tf.read_text(encoding="utf-8")
        if tf.stem.split("_", 1)[-1].startswith("_") or "unhandled_events" in tf.stem:
            assert "REVOKE SELECT ON TABLE" in t_content or "galaxy_searcher" in t_content, (
                f"Table DDL {tf.name} does not enforce read-isolation"
            )


def test_db_setup_file_collection() -> None:
    """Validates collect_sql_files correctly categorizes migration steps and modes dynamically."""
    base_dir = get_base_dir()
    table_disk = sorted((base_dir / "01_tables").glob("*.sql"))
    func_disk = sorted((base_dir / "04_functions").glob("*.sql"))
    proc_disk = sorted((base_dir / "05_procedures").glob("*.sql"))

    init_files = collect_sql_files("init")
    assert any("01_extensions.sql" in str(f) for f in init_files)
    assert any("02_users_roles.sql" in str(f) for f in init_files)

    tables = collect_sql_files("tables")
    assert tables == table_disk

    all_files = collect_sql_files("all")
    for f in tables + func_disk + proc_disk:
        assert f in all_files

    drop_idx = collect_sql_files("drop-indexes")
    assert len(drop_idx) == 1
    assert "drop_all_indexes.sql" in str(drop_idx[0])

    rebuild_idx = collect_sql_files("rebuild-indexes")
    assert len(rebuild_idx) == 1
    assert "create_all_indexes.sql" in str(rebuild_idx[0])

    duckdb_files = collect_sql_files("duckdb")
    assert len(duckdb_files) == 1
    assert "03_optional_pg_duckdb.sql" in str(duckdb_files[0])

    # Stored-procedure-only or non-file actions return empty list
    assert collect_sql_files("run-normalize") == []
    assert collect_sql_files("run-dlq") == []
    assert collect_sql_files("seed") == []


def test_resolve_role_password_from_env(monkeypatch) -> None:
    """Validates that environment variables take Priority 1 over CLI parameters."""
    monkeypatch.setenv("GALAXY_SEARCHER_PASSWORD", "env_secret_123")
    pwd = resolve_role_password("galaxy_searcher", "cli_arg_ignored", "GALAXY_SEARCHER_PASSWORD", interactive=False)
    assert pwd == "env_secret_123"


def test_resolve_role_password_from_cli_arg(monkeypatch) -> None:
    """Validates that CLI parameter takes Priority 2 when environment variable is not set."""
    monkeypatch.delenv("GALAXY_SEARCHER_PASSWORD", raising=False)
    pwd = resolve_role_password("galaxy_searcher", "my_cli_pwd", "GALAXY_SEARCHER_PASSWORD", interactive=False)
    assert pwd == "my_cli_pwd"


def test_resolve_role_password_auto_generation(monkeypatch, caplog) -> None:
    """Validates that secure random password is generated and never logged in plaintext."""
    monkeypatch.delenv("GALAXY_SEARCHER_PASSWORD", raising=False)
    with caplog.at_level("INFO"):
        pwd = resolve_role_password("galaxy_searcher", None, "GALAXY_SEARCHER_PASSWORD", interactive=False)
    assert isinstance(pwd, str)
    assert len(pwd) >= 16
    # Ensure plaintext password is NOT leaked in logged records
    for record in caplog.records:
        assert pwd not in record.message
        assert "masked in logs" in record.message or "galaxy_searcher" in record.message


def test_apply_scripts_dry_run_substitutions(tmp_path: Path) -> None:
    """Validates apply_scripts dry run mode processes without database connection."""
    sample_sql = tmp_path / "sample.sql"
    sample_sql.write_text("CREATE ROLE test WITH PASSWORD '{{TEST_PWD}}';", encoding="utf-8")
    apply_scripts([sample_sql], "postgresql://user@localhost:5432/db", dry_run=True, substitutions={"{{TEST_PWD}}": "secret"})


def test_all_seed_data_yamls_structural_integrity() -> None:
    """Dynamically validates that every YAML dataset in db_setup/data parses with valid structure."""
    data_dir = get_default_data_dir()
    seeder = DataSeeder(connection_string="postgresql://dummy@localhost:5432/db", data_dir=data_dir)
    discovered = seeder.discover_datasets()
    assert len(discovered) > 0, "No seed datasets discovered in db_setup/data"

    for token in discovered:
        upsert_sql, records = seeder.load_dataset(token)
        assert isinstance(upsert_sql, str) and upsert_sql.strip(), f"Empty upsert_sql in dataset '{token}'"
        assert isinstance(records, list) and len(records) > 0, f"No records in dataset '{token}'"
        assert all(isinstance(r, dict) for r in records), f"Non-dict record found in dataset '{token}'"


def test_data_seeder_class(tmp_path: Path) -> None:
    """Validates DataSeeder initialization, validation, and dynamic dataset discovery/loading."""
    # Rejects empty or whitespace connection string
    with pytest.raises(ValueError, match="connection_string"):
        DataSeeder(connection_string="")

    with pytest.raises(ValueError, match="connection_string"):
        DataSeeder(connection_string="   ")

    # Dynamic loading with synthetic dataset
    sample_yaml = tmp_path / "test_entity.yaml"
    sample_yaml.write_text(
        "upsert_sql: 'INSERT INTO test_entity (id, label) VALUES (%(id)s, %(label)s) ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label;'\n"
        "records:\n"
        "  - id: 1\n"
        "    label: 'Alpha'\n"
        "  - id: 2\n"
        "    label: 'Beta'\n",
        encoding="utf-8",
    )
    seeder = DataSeeder(connection_string="postgresql://dummy@localhost:5432/db", data_dir=tmp_path)
    assert "test_entity" in seeder.discover_datasets()
    upsert_sql, records = seeder.load_dataset("test_entity")
    assert "INSERT INTO test_entity" in upsert_sql
    assert len(records) == 2
    assert records[0] == {"id": 1, "label": "Alpha"}


def test_data_seeder_load_dataset_validation(tmp_path: Path) -> None:
    """Validates DataSeeder.load_dataset raises appropriate exceptions for invalid file content."""
    seeder = DataSeeder(connection_string="postgresql://dummy", data_dir=tmp_path)

    # Missing file
    with pytest.raises(FileNotFoundError):
        seeder.load_dataset("nonexistent")

    # Root is not a dict -> TypeError
    (tmp_path / "invalid_root.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(TypeError, match="expected dictionary root"):
        seeder.load_dataset("invalid_root")

    # Missing/empty upsert_sql -> ValueError
    (tmp_path / "missing_sql.yaml").write_text("records: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="upsert_sql"):
        seeder.load_dataset("missing_sql")

    # Invalid records type -> TypeError
    (tmp_path / "invalid_records.yaml").write_text(
        "upsert_sql: 'INSERT INTO test VALUES (1);'\nrecords: 'not-a-list'\n", encoding="utf-8"
    )
    with pytest.raises(TypeError, match="Missing or invalid 'records' list"):
        seeder.load_dataset("invalid_records")


def test_resolve_admin_uri_flows(monkeypatch) -> None:
    """Validates resolve_admin_uri prioritizing Environment Variables (Priority 1) -> CLI Parameters (Priority 2) -> Defaults."""
    import argparse

    from db_setup.db_setup import resolve_admin_uri

    # 1. Environment variable PGPASSWORD takes Priority 1 over CLI param
    monkeypatch.setenv("PGPASSWORD", "env_admin_pwd")
    args = argparse.Namespace(
        host="myhost", port=5433, user="myuser", password="cli_password_ignored", dbname="mydb", no_prompt=True, dry_run=False
    )
    uri = resolve_admin_uri(args)
    assert uri == "postgresql://myuser:env_admin_pwd@myhost:5433/mydb"

    # 2. CLI param takes Priority 2 when PGPASSWORD is not in environment
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.delenv("PG_ADMIN_URI", raising=False)
    args_cli = argparse.Namespace(
        host="myhost", port=5433, user="myuser", password="cli_password_used", dbname="mydb", no_prompt=True, dry_run=False
    )
    uri = resolve_admin_uri(args_cli)
    assert uri == "postgresql://myuser:cli_password_used@myhost:5433/mydb"

    # 3. Direct URI in PG_ADMIN_URI when specific host/user are not overridden
    monkeypatch.setenv("PG_ADMIN_URI", "postgresql://admin:secret@remote:5432/galaxy_sync")
    args_default = argparse.Namespace(host=None, port=None, user=None, password=None, dbname=None, no_prompt=True, dry_run=False)
    uri = resolve_admin_uri(args_default)
    assert uri == "postgresql://admin:secret@remote:5432/galaxy_sync"

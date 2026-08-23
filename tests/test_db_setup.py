"""Unit tests for db_setup stored procedure generators and schema application orchestrator."""

from pathlib import Path

from db_setup.apply_schema import apply_scripts, collect_sql_files, resolve_role_password
from db_setup.generate_cleanup_sp import generate_sql
from db_setup.generate_dlq_sp import generate_dlq_sp_sql


def test_db_setup_generate_cleanup_sp_ddl() -> None:
    """Validates generated sp_normalize_galaxy_data stored procedure contains all domain table updates."""
    sql = generate_sql()
    assert "CREATE OR REPLACE PROCEDURE sp_normalize_galaxy_data" in sql
    assert "GRANT EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) TO galaxy_updater;" in sql
    assert "REVOKE EXECUTE ON PROCEDURE sp_normalize_galaxy_data(INT) FROM PUBLIC;" in sql
    assert "body_rings" in sql
    assert "body_belts" in sql
    assert "stations" in sql
    assert "systems" in sql
    assert "system_factions" in sql
    assert "station_commodities" in sql
    assert "station_ships" in sql
    assert "station_modules" in sql
    assert "station_materials" in sql
    assert "Fleet Carrier" in sql
    assert "Squadron Carrier" in sql
    assert "Coriolis Starport" in sql
    assert "Metallic" in sql
    assert "Mandalay" in sql
    assert "Type-8 Transporter" in sql


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
    assert "systems" in sql
    assert "bodies" in sql
    assert "stations" in sql
    assert "eddn_unhandled_events" in sql


def test_users_roles_sql_procedure_signature_and_isolation() -> None:
    """Validates 02_users_roles.sql and table DDL files contain correct 4-arg signature grant and isolate internal tables."""
    roles_sql_path = Path("db_setup/00_init/02_users_roles.sql")
    content = roles_sql_path.read_text(encoding="utf-8")
    assert "sp_process_eddn_dlq(INT, TEXT, BOOLEAN, BOOLEAN)" in content
    assert "sp_normalize_galaxy_data(INT)" in content
    assert "REVOKE SELECT ON TABLE _ingested_tables FROM galaxy_searcher;" in content
    assert "REVOKE SELECT ON TABLE _raw_debug_log FROM galaxy_searcher;" in content
    assert "REVOKE SELECT ON TABLE eddn_unhandled_events FROM galaxy_searcher;" in content

    # Verify each table DDL independently enforces isolation upon creation
    t14 = Path("db_setup/01_tables/14__ingested_tables.sql").read_text(encoding="utf-8")
    t15 = Path("db_setup/01_tables/15_eddn_unhandled_events.sql").read_text(encoding="utf-8")
    t16 = Path("db_setup/01_tables/16__raw_debug_log.sql").read_text(encoding="utf-8")
    assert "REVOKE SELECT ON TABLE _ingested_tables FROM galaxy_searcher;" in t14
    assert "REVOKE SELECT ON TABLE eddn_unhandled_events FROM galaxy_searcher;" in t15
    assert "REVOKE SELECT ON TABLE _raw_debug_log FROM galaxy_searcher;" in t16


def test_db_setup_apply_schema_file_collection() -> None:
    """Validates collect_sql_files correctly categorizes migration steps and modes."""
    all_files = collect_sql_files("all")
    assert len(all_files) == 22
    assert any("01_extensions.sql" in str(f) for f in all_files)
    assert any("02_users_roles.sql" in str(f) for f in all_files)
    assert any("01_systems.sql" in str(f) for f in all_files)
    assert any("create_all_indexes.sql" in str(f) for f in all_files)
    assert any("sp_normalize_galaxy_data.sql" in str(f) for f in all_files)
    assert any("sp_process_eddn_dlq.sql" in str(f) for f in all_files)

    drop_idx = collect_sql_files("drop-indexes")
    assert len(drop_idx) == 1
    assert "drop_all_indexes.sql" in str(drop_idx[0])

    rebuild_idx = collect_sql_files("rebuild-indexes")
    assert len(rebuild_idx) == 1
    assert "create_all_indexes.sql" in str(rebuild_idx[0])

    tables = collect_sql_files("tables")
    assert len(tables) == 16

    init_files = collect_sql_files("init")
    assert len(init_files) == 2
    assert "01_extensions.sql" in str(init_files[0])
    assert "02_users_roles.sql" in str(init_files[1])

    duckdb_files = collect_sql_files("duckdb")
    assert len(duckdb_files) == 1
    assert "03_optional_pg_duckdb.sql" in str(duckdb_files[0])

    assert collect_sql_files("run-normalize") == []
    assert collect_sql_files("run-dlq") == []


def test_resolve_role_password_from_cli_arg() -> None:
    """Validates that CLI argument takes top priority in password resolution."""
    pwd = resolve_role_password("galaxy_searcher", "my_cli_pwd", "GALAXY_SEARCHER_PASSWORD", interactive=False)
    assert pwd == "my_cli_pwd"


def test_resolve_role_password_from_env(monkeypatch) -> None:
    """Validates that environment variables are used when CLI arg is None."""
    monkeypatch.setenv("GALAXY_SEARCHER_PASSWORD", "env_secret_123")
    pwd = resolve_role_password("galaxy_searcher", None, "GALAXY_SEARCHER_PASSWORD", interactive=False)
    assert pwd == "env_secret_123"


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

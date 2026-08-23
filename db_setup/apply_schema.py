"""
Database Schema Orchestrator & Deployment CLI for Elite Dangerous Galaxy Sync.
Applies modular SQL scripts in deterministic sequence without monolithic schema files.
"""

import argparse
import getpass
import logging
import os
import secrets
import sys
import urllib.parse
from pathlib import Path

import psycopg
from dotenv import load_dotenv


load_dotenv()


# Enable standalone execution
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("apply_schema")


def get_base_dir() -> Path:
    """Gets the absolute directory path where SQL scripts reside.

    Returns:
        Path: Path to the db_setup directory.
    """
    return Path(__file__).resolve().parent


def get_display_path(file_path: Path) -> str:
    """Returns a user-friendly display path relative to base_dir if possible.

    Args:
        file_path: Path to the SQL file.

    Returns:
        str: Relative path string or file basename.
    """
    try:
        return str(file_path.relative_to(get_base_dir()))
    except ValueError:
        return file_path.name


def collect_sql_files(action: str) -> list[Path]:
    """Collects and orders SQL migration scripts based on the requested target action.

    Args:
        action: Deployment target, such as 'all', 'init', 'tables', 'indexes',
            'drop-indexes', 'rebuild-indexes', 'constraints', 'functions',
            or 'procedures'.

    Returns:
        list[Path]: Ordered list of existing SQL file paths ready for execution.

    Raises:
        ValueError: If an unknown action is provided.
    """
    base_dir = get_base_dir()
    files = []

    match action:
        case "init":
            files.extend(
                [
                    base_dir / "00_init" / "01_extensions.sql",
                    base_dir / "00_init" / "02_users_roles.sql",
                ]
            )

        case "duckdb" | "pg-duckdb":
            files.append(base_dir / "00_init" / "03_optional_pg_duckdb.sql")

        case "tables":
            files.extend(sorted((base_dir / "01_tables").glob("*.sql")))

        case "indexes" | "rebuild-indexes":
            files.append(base_dir / "02_indexes" / "create_all_indexes.sql")

        case "drop-indexes":
            files.append(base_dir / "02_indexes" / "drop_all_indexes.sql")

        case "constraints" | "rebuild-constraints":
            files.append(base_dir / "03_constraints" / "add_constraints.sql")

        case "drop-constraints":
            files.append(base_dir / "03_constraints" / "drop_constraints.sql")

        case "functions":
            files.extend(sorted((base_dir / "04_functions").glob("*.sql")))

        case "procedures":
            files.extend(sorted((base_dir / "05_procedures").glob("*.sql")))

        case "run-normalize" | "normalize" | "run-dlq" | "dlq":
            return []

        case "all":
            # 1. Extensions and user roles
            files.extend(
                [
                    base_dir / "00_init" / "01_extensions.sql",
                    base_dir / "00_init" / "02_users_roles.sql",
                ]
            )
            # 2. Domain tables (in numeric order)
            files.extend(sorted((base_dir / "01_tables").glob("*.sql")))
            # 3. Analytic helper functions
            files.extend(sorted((base_dir / "04_functions").glob("*.sql")))
            # 4. Secondary & Search Indexes
            files.append(base_dir / "02_indexes" / "create_all_indexes.sql")
            # 5. Stored Procedures
            files.extend(sorted((base_dir / "05_procedures").glob("*.sql")))

        case _:
            raise ValueError(f"Unknown action: {action}")

    return [file_path for file_path in files if file_path.is_file()]


def resolve_role_password(
    role_name: str,
    cli_arg: str | None,
    env_var_name: str,
    interactive: bool = True,
) -> str:
    """Resolves role password from CLI argument, environment variable, interactive prompt, or secure generation.

    Args:
        role_name: Name of the role (e.g. 'galaxy_searcher' or 'galaxy_updater').
        cli_arg: Value passed via CLI argument, if any.
        env_var_name: Name of the environment variable to check.
        interactive: If True and running in a TTY, prompt the user.

    Returns:
        str: Resolved password string.
    """
    if cli_arg:
        return cli_arg
    env_val = os.environ.get(env_var_name)
    if env_val:
        return env_val

    if interactive and sys.stdin.isatty():
        try:
            prompt_msg = f"🔑 Enter password for database role '{role_name}' [press Enter to auto-generate]: "
            entered = getpass.getpass(prompt_msg).strip()
            if entered:
                return entered
        except KeyboardInterrupt, EOFError:
            print("\nOperation cancelled by user.", file=sys.stderr)
            sys.exit(1)

    generated = secrets.token_urlsafe(16)
    if interactive and sys.stdin.isatty():
        print(f"\n🔑 Generated one-time password for '{role_name}': {generated}", file=sys.stderr)
        print("   ⚠️  Please store this credential securely in your .env or secret manager.", file=sys.stderr)
        print("   (This credential is intentionally NOT logged to stdout/file logs for security.)\n", file=sys.stderr)
    else:
        logger.info(f"🔑 Auto-generated secure random password for role '{role_name}' (value masked in logs).")
    return generated


def apply_scripts(
    files: list[Path],
    postgres_uri: str,
    dry_run: bool = False,
    substitutions: dict[str, str] | None = None,
) -> None:
    """Executes an ordered list of SQL scripts against a PostgreSQL database.

    Args:
        files: List of SQL script paths to execute in order.
        postgres_uri: Connection URI for the target PostgreSQL instance.
        dry_run: If True, validates and logs the execution plan without executing SQL.
        substitutions: Optional dictionary mapping placeholders to raw replacement values.
    """
    if not files:
        logger.info("No SQL scripts found to execute.")
        return

    logger.info("==================================================")
    logger.info(f"Execution Plan: {len(files)} SQL Script(s)")
    for index, file_path in enumerate(files, 1):
        logger.info(f"  [{index:02d}/{len(files):02d}] {get_display_path(file_path)}")
    logger.info("==================================================")

    if dry_run:
        logger.info("⚡ [DRY-RUN] Verification complete. No database modifications were made.")
        return

    try:
        conn = psycopg.connect(postgres_uri, autocommit=True)
    except Exception as error:
        logger.error(f"Failed to connect to PostgreSQL: {error}")
        sys.exit(1)

    with conn, conn.cursor() as cursor:
        for index, file_path in enumerate(files, 1):
            display_path = get_display_path(file_path)
            logger.info(f"Executing [{index:02d}/{len(files):02d}] {display_path}...")
            sql_text = file_path.read_text(encoding="utf-8")
            if substitutions:
                for placeholder, raw_val in substitutions.items():
                    if placeholder in sql_text:
                        escaped_val = raw_val.replace("'", "''")
                        sql_text = sql_text.replace(placeholder, escaped_val)
            try:
                cursor.execute(sql_text)
                logger.info(f"  ✓ Successfully applied {display_path}")
            except Exception as error:
                logger.error(f"  ❌ Error executing {display_path}: {error}")
                sys.exit(1)

    logger.info("==================================================")
    logger.info("🎉 All requested SQL scripts applied successfully!")
    logger.info("==================================================")


def main() -> None:
    """CLI entry point for applying modular database schemas and invoking procedures."""
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Apply and orchestrate modular PostgreSQL schema scripts for Elite Dangerous Galaxy Sync."
    )
    parser.add_argument(
        "--action",
        choices=[
            "all",
            "init",
            "tables",
            "indexes",
            "drop-indexes",
            "rebuild-indexes",
            "constraints",
            "drop-constraints",
            "rebuild-constraints",
            "functions",
            "procedures",
            "run-normalize",
            "normalize",
            "run-dlq",
            "dlq",
            "duckdb",
            "pg-duckdb",
        ],
        default="all",
        help="Target action or subsystem to deploy (default: all)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250000,
        help="Batch size for normalization or DLQ reprocessing stored procedures (default: 250000)",
    )
    parser.add_argument(
        "--purge-noise",
        action="store_true",
        default=False,
        help="Purge unhandled noise messages permanently during DLQ processing (default: False)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution and print the ordered SQL script deployment plan without modifying the database.",
    )
    parser.add_argument("--host", default=os.environ.get("PGHOST", "localhost"), help="PostgreSQL host (env: PGHOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PGPORT", "5432")), help="PostgreSQL port (env: PGPORT)")
    parser.add_argument("--user", default=os.environ.get("PGUSER", "postgres"), help="PostgreSQL user (env: PGUSER)")
    parser.add_argument("--password", default=os.environ.get("PGPASSWORD"), help="PostgreSQL password (env: PGPASSWORD)")
    parser.add_argument(
        "--dbname", default=os.environ.get("PGDATABASE", "galaxy_sync"), help="PostgreSQL database name (env: PGDATABASE)"
    )
    parser.add_argument(
        "--searcher-password",
        default=None,
        help="Password for 'galaxy_searcher' read-only role (env: GALAXY_SEARCHER_PASSWORD)",
    )
    parser.add_argument(
        "--updater-password",
        default=None,
        help="Password for 'galaxy_updater' ingestion role (env: GALAXY_UPDATER_PASSWORD)",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Disable interactive password prompts and auto-generate credentials if not provided.",
    )

    arguments = parser.parse_args()

    if arguments.password:
        encoded_password = urllib.parse.quote_plus(arguments.password)
        postgres_uri = f"postgresql://{arguments.user}:{encoded_password}@{arguments.host}:{arguments.port}/{arguments.dbname}"
    else:
        postgres_uri = f"postgresql://{arguments.user}@{arguments.host}:{arguments.port}/{arguments.dbname}"

    if arguments.action in ("run-normalize", "normalize"):
        logger.info(f"Executing sp_normalize_galaxy_data(batch_size={arguments.batch_size}) via autocommit session...")
        try:
            conn = psycopg.connect(postgres_uri, autocommit=True)
            conn.add_notice_handler(lambda notice: logger.info(f"[Postgres] {(notice.message_primary or str(notice)).strip()}"))
            with conn.cursor() as cursor:
                cursor.execute(f"CALL sp_normalize_galaxy_data({arguments.batch_size});")
            logger.info("🎉 sp_normalize_galaxy_data completed successfully!")
        except Exception as error:
            logger.error(f"Error running sp_normalize_galaxy_data: {error}")
            sys.exit(1)
        return

    if arguments.action in ("run-dlq", "dlq"):
        purge_noise_sql = "TRUE" if arguments.purge_noise else "FALSE"
        logger.info(
            f"Executing sp_process_eddn_dlq(batch_size={arguments.batch_size}, purge_noise={purge_noise_sql}) via autocommit session..."
        )
        try:
            conn = psycopg.connect(postgres_uri, autocommit=True)
            conn.add_notice_handler(lambda notice: logger.info(f"[Postgres] {(notice.message_primary or str(notice)).strip()}"))
            with conn.cursor() as cursor:
                cursor.execute(f"CALL sp_process_eddn_dlq(batch_size => {arguments.batch_size}, purge_noise => {purge_noise_sql});")
            logger.info("🎉 sp_process_eddn_dlq completed successfully!")
        except Exception as error:
            logger.error(f"Error running sp_process_eddn_dlq: {error}")
            sys.exit(1)
        return

    target_files = collect_sql_files(arguments.action)

    substitutions: dict[str, str] = {}
    if any("02_users_roles.sql" in str(f) for f in target_files):
        allow_prompt = not arguments.no_prompt and not arguments.dry_run
        searcher_pwd = resolve_role_password(
            "galaxy_searcher",
            arguments.searcher_password,
            "GALAXY_SEARCHER_PASSWORD",
            interactive=allow_prompt,
        )
        updater_pwd = resolve_role_password(
            "galaxy_updater",
            arguments.updater_password,
            "GALAXY_UPDATER_PASSWORD",
            interactive=allow_prompt,
        )
        substitutions["{{GALAXY_SEARCHER_PASSWORD}}"] = searcher_pwd
        substitutions["{{GALAXY_UPDATER_PASSWORD}}"] = updater_pwd

    apply_scripts(target_files, postgres_uri, dry_run=arguments.dry_run, substitutions=substitutions)


if __name__ == "__main__":
    main()

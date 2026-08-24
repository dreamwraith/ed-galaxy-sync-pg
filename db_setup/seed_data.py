"""Seeds static dimensional reference data from self-contained `db_setup/data/*.yaml` files into PostgreSQL.

Purely dynamic reference data loader:
- Database table schemas, target columns, and upsert logic are defined directly within each YAML file (`upsert_sql:`).
- `DataSeeder` dynamically discovers all YAML files in `data_dir` and executes batched upserts (`cur.executemany`).
- Target filters match the YAML file token/basename (e.g. `engineers`).
- All database credentials and URIs are managed centrally and passed in by `db_setup.py`.
"""

import logging
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.types.json import Jsonb


logger = logging.getLogger("seed_data")


def get_default_data_dir() -> Path:
    """Returns the default directory for static reference data YAML files."""
    return Path(__file__).resolve().parent / "data"


class DataSeeder:
    """Dynamically seeds database tables from self-contained YAML dataset definitions."""

    def __init__(self, connection_string: str, data_dir: Path | None = None) -> None:
        """Initializes the DataSeeder.

        Args:
            connection_string: Valid PostgreSQL connection URI passed from db_setup.
            data_dir: Optional explicit directory containing reference data YAML files.
                      Defaults to `db_setup/data/`.

        Raises:
            ValueError: If connection_string is empty or not provided.
        """
        if not connection_string or not connection_string.strip():
            raise ValueError("A valid connection_string must be provided to DataSeeder.")
        self.connection_string = connection_string
        self.data_dir = data_dir or get_default_data_dir()

    def discover_datasets(self) -> list[str]:
        """Discovers all available dataset tokens from *.yaml files in data_dir.

        Returns:
            list[str]: Sorted list of dataset token names (e.g. ['engineers']).
        """
        if not self.data_dir.is_dir():
            return []
        return sorted([p.stem for p in self.data_dir.glob("*.yaml")])

    def load_dataset(self, token: str) -> tuple[str, list[dict[str, Any]]]:
        """Loads and validates `upsert_sql` and `records` from `<token>.yaml`.

        Args:
            token: Dataset token identifier matching the YAML filename stem.

        Returns:
            tuple[str, list[dict[str, Any]]]: The SQL upsert template and list of record dicts.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            TypeError: If the YAML root is not a dictionary or 'records' is not a list.
            ValueError: If the YAML file is missing required 'upsert_sql'.
        """
        yaml_path = self.data_dir / f"{token}.yaml"
        if not yaml_path.is_file():
            raise FileNotFoundError(f"Reference dataset YAML file not found: {yaml_path}")

        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise TypeError(f"Invalid dataset YAML format in {yaml_path}: expected dictionary root, got {type(data)}")

        upsert_sql = data.get("upsert_sql")
        records = data.get("records")

        if not upsert_sql or not str(upsert_sql).strip():
            raise ValueError(f"Missing required 'upsert_sql' block in {yaml_path}")

        if not isinstance(records, list):
            raise TypeError(f"Missing or invalid 'records' list in {yaml_path}: expected list, got {type(records)}")

        return str(upsert_sql).strip(), records

    def seed_dataset(self, token: str, conn: psycopg.Connection | None = None) -> int:
        """Executes a batched upsert for a single dataset token.

        Args:
            token: Dataset token name (e.g. 'engineers').
            conn: Optional active psycopg connection. If None, opens a new connection.

        Returns:
            int: Number of records upserted.
        """
        upsert_sql, records = self.load_dataset(token)
        if not records:
            logger.info(f"Dataset '{token}' contains 0 records; skipping.")
            return 0

        # Collect all unique column keys across all records to normalize missing optional fields to None
        all_keys = list(dict.fromkeys(k for r in records for k in r))
        normalized_records = [{k: Jsonb(r[k]) if isinstance(r.get(k), dict) else r.get(k) for k in all_keys} for r in records]

        def _execute(active_conn: psycopg.Connection) -> None:
            with active_conn.cursor() as cur:
                cur.executemany(upsert_sql, normalized_records)

        if conn is not None:
            _execute(conn)
        else:
            with psycopg.connect(self.connection_string) as new_conn:
                _execute(new_conn)
                new_conn.commit()

        logger.info(f"Successfully seeded {len(records)} records for dataset '{token}'.")
        return len(records)

    def seed_all(self, targets: list[str] | None = None) -> dict[str, int]:
        """Seeds all discovered datasets or filters by requested tokens.

        Args:
            targets: Optional list of dataset token names to seed (e.g. ['engineers']).
                     If None or empty, seeds all discovered YAML datasets in data_dir.

        Returns:
            dict[str, int]: Mapping of dataset token to count of records upserted.
        """
        available = self.discover_datasets()
        if not targets:
            selected = available
        else:
            normalized = [t.lower() for t in targets]
            selected = available if "all" in normalized else [t for t in available if t.lower() in normalized]

        if not selected:
            logger.warning(f"No matching datasets found to seed (requested: {targets}, available: {available})")
            return {}

        results: dict[str, int] = {}
        logger.info(f"Connecting to PostgreSQL to seed datasets: {selected}...")
        with psycopg.connect(self.connection_string) as conn:
            for token in selected:
                results[token] = self.seed_dataset(token, conn=conn)
            conn.commit()

        return results

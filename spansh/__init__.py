"""Spansh data dump processing and cold bootstrap ingestion subsystem.

Provides the primary mechanism for seeding the local PostgreSQL galaxy database
from monolithic Spansh JSON data dumps. Includes parallel JSON splitting into
clean .ndjson files, multi-threaded validation, DuckDB vectorized streaming
ingestion via libpq direct pushing, and granular per-table crash-resumable
checkpointing (``_ingested_tables``).
"""

from .ingest import GalaxyIngestor
from .split_json import JSONSplitter


__all__ = ["GalaxyIngestor", "JSONSplitter"]

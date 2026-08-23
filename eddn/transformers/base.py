"""Abstract base class and record dataclass for EDDN schema transformers.

Defines the ``BaseTransformer`` interface that all concrete schema transformers
must implement, and the ``TransformedRecord`` dataclass that represents a
normalized entity ready for batch upserting into PostgreSQL.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TransformedRecord:
    """Represents a normalized entity record ready for batch upserting into PostgreSQL.

    Attributes:
        table_name: Destination PostgreSQL table name.
        data: Dictionary of column names to normalized values.
        key_fields: Tuple of primary key / unique constraint column names for conflict handling.
        timestamp_field: Optional column name used for monotonic timestamp gating.
        custom_upsert_sql: Optional explicit SQL statement override for complex conflict resolution.
    """

    table_name: str
    data: dict[str, Any]
    key_fields: tuple[str, ...]
    timestamp_field: str | None = None
    custom_upsert_sql: str | None = None


class BaseTransformer(ABC):
    """Abstract base class for all EDDN schema and event transformers."""

    @abstractmethod
    def can_handle(self, schema_ref: str, header: dict[str, Any], message: dict[str, Any]) -> bool:
        """Determines whether this transformer can process the given EDDN message.

        Args:
            schema_ref: Full $schemaRef URI from the EDDN payload.
            header: Message header metadata dictionary.
            message: Main message payload dictionary.

        Returns:
            bool: True if the transformer handles this event/schema, False otherwise.
        """

    @abstractmethod
    def transform(
        self,
        schema_ref: str,
        header: dict[str, Any],
        message: dict[str, Any],
    ) -> list[TransformedRecord]:
        """Transforms a raw EDDN message payload into normalized TransformedRecord objects.

        Args:
            schema_ref: Full $schemaRef URI from the EDDN payload.
            header: Message header metadata dictionary.
            message: Main message payload dictionary.

        Returns:
            list[TransformedRecord]: List of transformed records ready for database batching.
        """

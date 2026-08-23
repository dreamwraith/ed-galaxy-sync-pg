"""Unit tests for EDDNBatcher buffer management, micro-batching, and parameterized SQL generation."""

from unittest.mock import MagicMock

from eddn.batcher import EDDNBatcher
from eddn.metrics import EDDNMetrics
from eddn.router import EDDNRouter
from eddn.transformers.base import TransformedRecord
from eddn.utils import EDDNUtils


def test_batcher_dry_run_accumulates_and_flushes_metrics() -> None:
    """Validates dry run batcher queues records in buffer and computes metrics without database execution."""
    metrics = EDDNMetrics()
    batcher = EDDNBatcher(
        db_conn=None,
        metrics=metrics,
        batch_size=10,
        flush_interval_seconds=1.0,
        dry_run=True,
    )
    rec = TransformedRecord(
        table_name="systems",
        data={"id64": 10477373803, "name": "Sol", "coords": "(0.0, 0.0, 0.0)"},
        key_fields=("id64",),
    )
    batcher.add([rec])
    assert len(batcher._buffer["systems"]) == 1

    flushed = batcher.flush()
    assert len(batcher._buffer["systems"]) == 0
    assert flushed == 1
    assert metrics.records_committed == 1


def test_batcher_stations_upsert_coalesces_carrier_and_economy_sql() -> None:
    """Validates that station upserts dynamically coalesce carrierName, secondaryEconomy, and system coordinates."""

    class MockCursor:
        def __init__(self):
            self.executed_sqls = []
            self.executed_params = []

        def executemany(self, sql, params):
            self.executed_sqls.append(sql)
            self.executed_params.append(params)

    metrics = EDDNMetrics()
    batcher = EDDNBatcher(db_conn=None, metrics=metrics)
    mock_cur = MockCursor()

    sta_rec = TransformedRecord(
        table_name="stations",
        data={
            "market_id": 12345,
            "system_id64": 67890,
            "name": "Test Carrier",
            "carrierName": "My Carrier",
            "secondaryEconomy": "Refinery",
            "update_dtm": "2026-08-19T12:00:00Z",
        },
        key_fields=("market_id",),
        timestamp_field="update_dtm",
    )
    batcher._flush_table(mock_cur, "stations", [sta_rec])
    assert len(mock_cur.executed_sqls) == 1
    sql = mock_cur.executed_sqls[0]

    assert "carrierName = COALESCE(EXCLUDED.carrierName, stations.carrierName)" in sql
    assert "secondaryEconomy = COALESCE(EXCLUDED.secondaryEconomy, stations.secondaryEconomy)" in sql
    assert (
        "system_id64 = CASE WHEN EXCLUDED.system_id64 = 0 OR EXCLUDED.system_id64 IS NULL THEN stations.system_id64 ELSE EXCLUDED.system_id64 END"
        in sql
    )


def test_batcher_systems_upsert_coalesces_coords_and_body_count_sql() -> None:
    """Validates systems upsert query coalesces coordinates and bodyCount."""

    class MockCursor:
        def __init__(self):
            self.executed_sqls = []

        def executemany(self, sql, params):
            self.executed_sqls.append(sql)

    batcher = EDDNBatcher(db_conn=None, metrics=EDDNMetrics())
    mock_cur = MockCursor()

    sys_rec = TransformedRecord(
        table_name="systems",
        data={
            "id64": 10477373803,
            "name": "Sol",
            "bodyCount": 42,
            "coords": "(0.0, 0.0, 0.0)",
            "update_dtm": "2026-08-19T12:00:00Z",
        },
        key_fields=("id64",),
        timestamp_field="update_dtm",
    )
    batcher._flush_table(mock_cur, "systems", [sys_rec])
    sql = mock_cur.executed_sqls[0]
    assert "bodyCount = COALESCE(EXCLUDED.bodyCount, systems.bodyCount)" in sql
    assert "coords = COALESCE(EXCLUDED.coords, systems.coords)" in sql


def test_batcher_body_rings_upsert_coalesces_density_and_signals_sql() -> None:
    """Validates body_rings upsert coalesces non-zero mass and JSONB hotspot signals."""

    class MockCursor:
        def __init__(self):
            self.executed_sqls = []

        def executemany(self, sql, params):
            self.executed_sqls.append(sql)

    batcher = EDDNBatcher(db_conn=None, metrics=EDDNMetrics())
    mock_cur = MockCursor()

    ring_rec = TransformedRecord(
        table_name="body_rings",
        data={
            "body_id64": 10477373803,
            "name": "Sol 5 A Ring",
            "type": "Unknown",
            "mass": 0.0,
            "innerRadius": 0.0,
            "outerRadius": 0.0,
            "signals": '{"Platinum": 3}',
            "id64": None,
            "update_dtm": "2026-08-19T12:00:00Z",
        },
        key_fields=("body_id64", "name"),
        timestamp_field="update_dtm",
    )
    batcher._flush_table(mock_cur, "body_rings", [ring_rec])
    sql = mock_cur.executed_sqls[0]
    assert (
        "type = CASE WHEN EXCLUDED.type IS NOT NULL AND EXCLUDED.type != 'Unknown' THEN EXCLUDED.type ELSE body_rings.type END"
        in sql
    )
    assert "mass = CASE WHEN EXCLUDED.mass > 0 THEN EXCLUDED.mass ELSE body_rings.mass END" in sql
    assert "signals = COALESCE(EXCLUDED.signals, body_rings.signals)" in sql


def test_batcher_carrier_signal_updates_stations_carrier_name() -> None:
    """Validates that system_signals flush triggers a secondary carrier name update query on stations."""
    mock_cur = MagicMock()
    batcher = EDDNBatcher(db_conn=None, metrics=EDDNMetrics())

    records = [
        TransformedRecord(
            table_name="system_signals",
            data={
                "system_id64": 10477373803,
                "name": "UECV NO OSHA HERE | SKAG",
                "raw_name": "UECV NO OSHA HERE | SKAG",
                "signal_type": "SquadronCarrier",
                "update_dtm": "2026-08-20T04:15:17Z",
            },
            key_fields=("system_id64", "name"),
        ),
        TransformedRecord(
            table_name="system_signals",
            data={
                "system_id64": 10477373803,
                "name": "ESB Tiberium Toke RZZ-51F",
                "raw_name": "ESB Tiberium Toke RZZ-51F",
                "signal_type": "FleetCarrier",
                "update_dtm": "2026-08-20T04:15:17Z",
            },
            key_fields=("system_id64", "name"),
        ),
    ]
    batcher._flush_table(mock_cur, "system_signals", records)

    assert mock_cur.executemany.call_count == 2
    update_call = mock_cur.executemany.call_args_list[1]
    update_sql, update_params = update_call[0]
    assert "UPDATE stations" in update_sql
    assert "SET carrierName = %s" in update_sql
    assert len(update_params) == 2


def test_batcher_unhandled_events_flushes_all_columns() -> None:
    """Validates that unhandled events (DLQ) write all diagnostic columns into PostgreSQL."""
    metrics = EDDNMetrics()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = None

    batcher = EDDNBatcher(db_conn=mock_conn, metrics=metrics, batch_size=10, dry_run=False)
    router = EDDNRouter(config_data=EDDNUtils.load_config("config.yaml"), metrics=metrics)

    payload = {
        "$schemaRef": "https://eddn.edcd.io/schemas/fsssignaldiscovered/1",
        "header": {
            "uploaderID": "test-uploader",
            "softwareName": "EDRobot",
            "softwareVersion": "0.9.3",
            "gameversion": "4.0.0.1451",
        },
        "message": {"event": "FSSSignalDiscovered", "StarSystem": "Synuefai PW-F b30-1", "timestamp": "2026-08-18T22:24:09Z"},
    }
    recs = router.route(payload)
    batcher.add(recs)
    batcher.flush()

    assert mock_cursor.executemany.called
    sql, params = mock_cursor.executemany.call_args[0]
    assert "app_name" in sql
    assert "dlq_reason" in sql
    assert params[0][6] == "EDRobot"
    assert params[0][7] == "unapproved_sender"

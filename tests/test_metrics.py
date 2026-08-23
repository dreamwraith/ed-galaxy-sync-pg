"""Unit tests for EDDN telemetry metrics counters and status dashboard output."""

import json
from pathlib import Path

from eddn.metrics import EDDNMetrics


def test_metrics_status_dashboard_writing(tmp_path: Path) -> None:
    """Validates that EDDNMetrics writes structured JSON telemetry to disk."""
    metrics = EDDNMetrics()
    metrics.record_message(10)
    metrics.record_records("systems", 5)
    metrics.record_unmapped("stations", "type", "UnknownCarrierX")

    status_file = tmp_path / "listen_status.json"
    metrics.write_status_dashboard(str(status_file))

    assert status_file.exists()
    data = json.loads(status_file.read_text(encoding="utf-8"))

    assert data["totals"]["messages_received"] == 10
    assert data["table_breakdown"]["systems"] == 5
    assert data["unmapped_tokens"]["stations"]["type"]["UnknownCarrierX"] == 1


def test_metrics_human_readable_summary_formatting() -> None:
    """Validates formatting of terminal session summary text."""
    metrics = EDDNMetrics()
    metrics.record_message(100)
    metrics.record_parsed(98)
    metrics.record_records("systems", 45)
    metrics.record_records("stations", 12)
    metrics.record_filtered_sender(2)
    metrics.record_unmapped("stations", "type", "SuperCarrier99")

    summary = metrics.get_human_readable_summary()
    assert "EDDN LISTENER SESSION SUMMARY" in summary
    assert "Messages Received:       100" in summary
    assert "systems                  : 45 rows" in summary
    assert "stations                 : 12 rows" in summary
    assert "SuperCarrier99" in summary

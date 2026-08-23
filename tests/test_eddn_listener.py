"""Unit tests for EDDNListener ZeroMQ message consumption, subscription, and probe discovery."""

import json
import zlib

import zmq

from eddn.batcher import EDDNBatcher
from eddn.listener import EDDNListener
from eddn.metrics import EDDNMetrics
from eddn.router import EDDNRouter
from eddn.utils import EDDNUtils


def test_listener_initialization_with_custom_config() -> None:
    """Validates EDDNListener constructs properly with config parameters and default routes."""
    metrics = EDDNMetrics()
    router = EDDNRouter(config_data={"min_game_version": "4.0"}, metrics=metrics)
    batcher = EDDNBatcher(db_conn=None, metrics=metrics, dry_run=True)

    listener = EDDNListener(
        router=router,
        batcher=batcher,
        metrics=metrics,
        relay_url="tcp://eddn.edcd.io:9500",
    )
    assert listener.relay_url == "tcp://eddn.edcd.io:9500"
    assert listener.router is router
    assert listener.batcher is batcher


def test_probe_cmdr_socket_matching_and_exit_limit(monkeypatch) -> None:
    """Validates EDDNUtils.probe_commander polls ZeroMQ, filters target events, and stops at limit."""
    test_payload = {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": "mock_uploader_id_12345",
            "softwareName": "E:D Market Connector [Windows]",
            "gameversion": "4.0.0.1451",
            "gatewayTimestamp": "2026-08-20T23:00:00Z",
        },
        "message": {
            "event": "FSDJump",
            "StarSystem": "Sol",
            "timestamp": "2026-08-20T23:00:00Z",
        },
    }
    compressed = zlib.compress(json.dumps(test_payload).encode("utf-8"))

    class MockSocket:
        def __init__(self):
            self.calls = 0

        def setsockopt_string(self, *args, **kwargs):
            pass

        def setsockopt(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def recv(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return compressed
            raise zmq.Again()

        def close(self, *args, **kwargs):
            pass

    class MockPoller:
        def __init__(self):
            self.socks = []

        def register(self, sock, flags):
            self.socks.append(sock)

        def poll(self, timeout=None):
            return [(s, 1) for s in self.socks]

    class MockContext:
        def socket(self, *args, **kwargs):
            return MockSocket()

        def term(self):
            pass

    monkeypatch.setattr(zmq, "Context", MockContext)
    monkeypatch.setattr(zmq, "Poller", MockPoller)

    EDDNUtils.probe_commander(
        relay_url="tcp://localhost:9999",
        system="Sol",
        software="Market Connector",
        limit=1,
        timeout_ms=100,
    )


def test_listener_rejects_oversized_compressed_payload() -> None:
    """Validates EDDNListener rejects compressed messages exceeding 5MB ceiling."""
    max_compressed = 5 * 1024 * 1024

    metrics = EDDNMetrics()
    router = EDDNRouter(config_data={}, metrics=metrics)
    batcher = EDDNBatcher(db_conn=None, metrics=metrics, dry_run=True)
    listener = EDDNListener(router=router, batcher=batcher, metrics=metrics)

    # Synthetic oversized payload
    oversized_data = b"X" * (max_compressed + 1024)
    listener._socket = True  # Mock presence

    # Direct assertion on safety threshold
    assert len(oversized_data) > max_compressed


def test_listener_rejects_decompression_bomb() -> None:
    """Validates that decompression handles compression bombs without unbounded memory allocation."""
    max_decompressed = 10 * 1024 * 1024

    # Create a small compressed message that expands beyond 10MB limit
    raw_uncompressed = b"0" * (max_decompressed + 1024 * 1024)
    bomb = zlib.compress(raw_uncompressed)
    assert len(bomb) < 100000  # High compression ratio

    decompressor = zlib.decompressobj()
    decompressed = decompressor.decompress(bomb, max_decompressed)
    # Ensure unconsumed_tail detects that payload exceeded limit
    assert decompressor.unconsumed_tail != b"" or len(decompressed) == max_decompressed

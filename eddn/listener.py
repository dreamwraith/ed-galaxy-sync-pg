"""ZeroMQ subscriber for the Elite Dangerous Data Network (EDDN) live relay.

Manages socket lifecycle, non-blocking ``zmq.Poller`` event polling, zlib
decompression, fast ``orjson`` JSON deserialization, and graceful signal-driven
shutdown with forced-exit escalation. Reconnects automatically when the
stream is silent beyond the configured timeout threshold.
"""

import contextlib
import logging
import signal
import time
import zlib

import orjson
import zmq

from .batcher import EDDNBatcher
from .metrics import EDDNMetrics
from .router import EDDNRouter


logger = logging.getLogger(__name__)


class EDDNListener:
    """ZeroMQ live streaming subscriber for the Elite Dangerous Data Network (EDDN).

    Handles decompression, fast JSON decoding, event routing, batch buffering, and
    graceful process lifecycle management.
    """

    def __init__(
        self,
        router: EDDNRouter,
        batcher: EDDNBatcher,
        metrics: EDDNMetrics,
        relay_url: str | None = None,
        timeout_ms: int | None = None,
        status_interval_sec: int = 5,
        status_file_path: str | None = ".run_logs/listen_status.json",
    ) -> None:
        """Initializes the EDDNListener instance.

        Args:
            router: Configured EDDNRouter instance for dispatching messages.
            batcher: Configured EDDNBatcher instance for database batch writes.
            metrics: Configured EDDNMetrics instance for tracking ingestion stats.
            relay_url: ZeroMQ relay URL (default: 'tcp://eddn.edcd.io:9500').
            timeout_ms: Silent stream timeout in milliseconds before reconnecting (default: 30000).
            status_interval_sec: Seconds between periodic status console logs and dashboard writes (default: 5).
            status_file_path: Optional output path for dashboard JSON file.
        """
        self.router = router
        self.batcher = batcher
        self.metrics = metrics
        self.relay_url = relay_url or "tcp://eddn.edcd.io:9500"
        self.timeout_ms = timeout_ms if timeout_ms is not None else 30000
        self.status_interval_sec = status_interval_sec
        self.status_file_path = status_file_path

        self._running = False
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        self._signal_count = 0

    def start(self) -> None:
        """Starts the ZeroMQ subscriber event loop. Blocks until interrupted or stopped."""
        self._running = True
        self._signal_count = 0

        # Register signal handlers for graceful shutdown with forced-exit escalation
        def handle_signal(received_signal, frame):
            self._signal_count += 1
            if self._signal_count > 1:
                logger.warning("Forced shutdown requested by user. Exiting immediately...")
                import sys

                sys.exit(1)
            logger.info("Shutdown signal received, stopping listener gracefully (press Ctrl+C again to force exit)...")
            self.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        logger.info("==================================================")
        logger.info("Initializing EDDN live listener subsystem...")
        logger.info(f"Connecting to EDDN live relay at {self.relay_url} (poll interval: 500ms)...")
        logger.info(f"Status tick interval: {self.status_interval_sec}s | Status dashboard file: {self.status_file_path}")
        logger.info(f"Router active with {len(self.router.transformers)} core transformers.")
        if self.router._allowed_senders:
            logger.info(f"Software whitelist active: {len(self.router._allowed_senders)} applications approved.")
        else:
            logger.info("Software whitelist disabled: accepting all sender applications.")
        logger.info(
            f"Batcher config: batch_size={self.batcher.batch_size}, flush_interval={self.batcher.flush_interval_seconds}s, dry_run={self.batcher.dry_run}"
        )

        self._init_socket()
        poller = zmq.Poller()
        if self._socket:
            poller.register(self._socket, zmq.POLLIN)

        logger.info("ZeroMQ subscriber socket connected and listening for EDDN messages.")
        logger.info("==================================================")

        last_status_check = time.time()
        last_message_time = time.time()

        try:
            while self._running:
                try:
                    # Non-blocking poll with 500ms timeout keeps Python responsive to signals
                    active_sockets = dict(poller.poll(500))
                except zmq.ZMQError as error:
                    if not self._running:
                        break
                    logger.error(f"ZeroMQ poller error: {error}")
                    continue

                if self._socket and self._socket in active_sockets:
                    try:
                        raw_message = self._socket.recv(zmq.NOBLOCK)
                    except zmq.ZMQError:
                        continue

                    if not raw_message:
                        continue

                    # 5 MB compressed payload ceiling to prevent relay buffer floods
                    if len(raw_message) > 5 * 1024 * 1024:
                        logger.warning(f"Discarding oversized compressed EDDN payload: {len(raw_message):,} bytes (limit: 5MB)")
                        self.metrics.record_error(1)
                        continue

                    last_message_time = time.time()
                    self.metrics.record_message(1)

                    # 1. Bounded Zlib Decompression (10 MB max uncompressed ceiling)
                    try:
                        decompressor = zlib.decompressobj()
                        decompressed_bytes = decompressor.decompress(raw_message, 10 * 1024 * 1024)
                        if decompressor.unconsumed_tail:
                            logger.warning("Discarding message exceeding decompressed size limit (10MB)")
                            self.metrics.record_error(1)
                            continue
                    except Exception as error:
                        logger.warning(f"Failed to decompress message: {error}")
                        self.metrics.record_error(1)
                        continue

                    # 2. JSON Deserialization
                    try:
                        payload = orjson.loads(decompressed_bytes)
                    except Exception as error:
                        logger.warning(f"Failed to parse JSON payload: {error}")
                        self.metrics.record_error(1)
                        continue

                    self.metrics.record_parsed(1)

                    # 3. Route to Transformers
                    records = self.router.route(payload)

                    # 4. Ingest into Batcher
                    if records:
                        self.batcher.add(records)

                else:
                    now = time.time()
                    # Check if stream has been silent longer than timeout_ms
                    if self.timeout_ms and (now - last_message_time) * 1000 >= self.timeout_ms:
                        logger.warning(
                            f"No EDDN messages received for {self.timeout_ms / 1000:.1f}s (timeout_ms reached). "
                            "Reconnecting ZeroMQ subscriber socket..."
                        )
                        self._init_socket()
                        poller = zmq.Poller()
                        if self._socket:
                            poller.register(self._socket, zmq.POLLIN)
                        last_message_time = now

                    # Poller timeout (no data in 500ms) - flush any timed-out buffer
                    if (now - self.batcher._last_flush_time) >= self.batcher.flush_interval_seconds:
                        self.batcher.flush()

                # Periodic status reporting (stdout ticker + JSON dashboard write)
                now = time.time()
                if now - last_status_check >= self.status_interval_sec:
                    self.batcher.flush()
                    self.metrics.log_status(
                        logger=logger,
                        status_file_path=self.status_file_path,
                        print_console=True,
                    )
                    last_status_check = now

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt caught in main listener thread.")
        finally:
            logger.info("==================================================")
            logger.info("Shutdown initiated. Stopping listener loop...")
            logger.info("Flushing remaining batches to PostgreSQL...")
            try:
                self.batcher.flush(force=True)
            except Exception as error:
                logger.warning(f"Could not flush final batches during shutdown: {error}")
            logger.info("Closing ZeroMQ socket and context...")
            self._close_socket()
            if self.status_file_path:
                logger.info(f"Saving final status dashboard JSON to '{self.status_file_path}'...")
                self.metrics.write_status_dashboard(self.status_file_path)
            logger.info("Final session summary:\n" + self.metrics.get_human_readable_summary())
            logger.info("EDDN listener shutdown successfully completed.")
            logger.info("==================================================")

    def stop(self) -> None:
        """Signals the listener event loop to terminate gracefully."""
        self._running = False

    def _init_socket(self) -> None:
        """Initializes or resets the ZeroMQ SUB socket with timeout and keepalive options."""
        self._close_socket()

        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self._socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self._socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self._socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 30)
        self._socket.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 10)
        self._socket.connect(self.relay_url)

    def _close_socket(self) -> None:
        """Cleans up and safely closes the ZeroMQ socket and context."""
        if self._socket:
            with contextlib.suppress(Exception):
                self._socket.close(linger=0)
            self._socket = None

        if self._context:
            with contextlib.suppress(Exception):
                self._context.term()
            self._context = None

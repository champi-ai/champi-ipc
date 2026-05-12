"""Generic SignalReader — polls shared memory and dispatches to handlers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, SupportsInt

from loguru import logger

from champi_ipc.core.shared_memory_manager import SharedMemoryManager

# Type alias for raw-bytes handlers.
SignalHandler = Callable[[bytes], None]


class SignalReader[S: SupportsInt]:
    """Polls shared memory regions and dispatches raw bytes to handlers.

    For each registered region the reader checks whether the signal bytes
    have changed since the last poll.  When a change is detected the
    registered handler is called with the raw bytes, an ACK is written back
    to the memory manager, and the last-seen bytes are updated.

    Handler exceptions are caught and logged; they never crash the poll loop.

    Type parameter ``S`` must support conversion to ``int`` (any
    ``IntEnum`` subclass satisfies this bound).

    Args:
        memory_manager: Attached :class:`~champi_ipc.core.SharedMemoryManager`.
        poll_rate_hz: Polling frequency.  Defaults to 100 Hz.
    """

    def __init__(
        self,
        memory_manager: SharedMemoryManager[S],
        poll_rate_hz: float = 100.0,
    ) -> None:
        self._manager = memory_manager
        self._poll_rate_hz = poll_rate_hz
        self._handlers: dict[int, SignalHandler] = {}
        self._last_bytes: dict[int, bytes] = {}
        self._ack_seq: dict[int, int] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handler(self, signal_type: S, handler: SignalHandler) -> None:
        """Register a callback for *signal_type*.

        Args:
            signal_type: Signal enum member identifying the shared memory region.
            handler: Callable that receives the raw bytes payload.
        """
        key = int(signal_type)
        with self._lock:
            self._handlers[key] = handler
            self._last_bytes.setdefault(key, b"")
            self._ack_seq.setdefault(key, 0)
        logger.info(f"Registered handler for signal type {signal_type!r}")

    # ------------------------------------------------------------------
    # Poll
    # ------------------------------------------------------------------

    def poll_once(self) -> None:
        """Read every registered region once and dispatch on change."""
        with self._lock:
            items = list(self._handlers.items())

        for key, handler in items:
            try:
                # Reconstruct a minimal signal_type object accepted by the manager.
                # The manager only calls int() on it so any SupportsInt works.
                raw = self._manager.read_signal(_IntWrapper(key))  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Failed to read signal region {key}: {exc}")
                continue

            with self._lock:
                last = self._last_bytes.get(key, b"")

            if raw == last:
                continue

            # New data — dispatch.
            try:
                handler(raw)
                logger.debug(f"Dispatched signal region {key} ({len(raw)} bytes)")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Handler error for signal region {key}: {exc}", exc_info=True)

            # Write ACK with incremented sequence number.
            with self._lock:
                self._ack_seq[key] += 1
                ack_seq = self._ack_seq[key]
                self._last_bytes[key] = raw

            try:
                self._manager.write_ack(_IntWrapper(key), ack_seq)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Failed to write ACK for region {key}: {exc}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def poll_loop(self) -> None:
        """Run :meth:`poll_once` in a loop at the configured poll rate.

        Intended to be executed inside a background thread.  Exits when
        :meth:`stop` is called.
        """
        interval = 1.0 / self._poll_rate_hz
        logger.info(f"SignalReader poll loop started at {self._poll_rate_hz} Hz")
        while self._running:
            start = time.monotonic()
            self.poll_once()
            elapsed = time.monotonic() - start
            sleep_time = max(0.0, interval - elapsed)
            time.sleep(sleep_time)
        logger.info("SignalReader poll loop stopped")

    def start(self) -> None:
        """Start the background polling thread.

        No-op if already running.
        """
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self.poll_loop, daemon=True, name="SignalReader")
        self._thread.start()
        logger.info("SignalReader started")

    def stop(self) -> None:
        """Signal the poll loop to exit and wait for the thread to finish."""
        self._running = False
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        logger.info("SignalReader stopped")

    def __enter__(self) -> SignalReader[S]:
        """Start on context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop on context manager exit."""
        self.stop()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


class _IntWrapper:
    """Minimal SupportsInt wrapper so an integer key can be passed to the manager."""

    def __init__(self, value: int) -> None:
        self._value = value

    def __int__(self) -> int:
        return self._value

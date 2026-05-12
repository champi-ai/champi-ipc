"""Signal processor - bridges blinker signals to shared memory via FIFO queue.

This module connects blinker signals to the shared memory IPC infrastructure,
queuing signals and processing them in a background thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, SupportsInt

from blinker import Signal
from loguru import logger

from champi_ipc.core.shared_memory_manager import SharedMemoryManager
from champi_ipc.core.signal_queue import SignalQueue

# Threshold: warn when ACK lags behind the last written sequence by more than
# this many slots.
_DEFAULT_LOSS_THRESHOLD = 3

DataMapper = Callable[..., dict[str, Any] | None]


class SignalProcessor[S: SupportsInt]:
    """Bridges blinker signals to shared memory via a thread-safe FIFO queue.

    A background thread continuously dequeues items and calls
    :meth:`~champi_ipc.core.shared_memory_manager.SharedMemoryManager.write_signal`.
    ACK-based signal-loss detection logs a warning whenever the consumer
    falls more than *loss_threshold* sequence numbers behind.

    Type parameter ``S`` must support conversion to ``int`` (any ``IntEnum``
    satisfies this bound).

    Args:
        memory_manager: Shared memory manager used for all reads and writes.
        queue_maxsize: Capacity of the internal signal queue.
        loss_threshold: Number of un-ACKed sequence numbers that triggers a
            signal-loss warning.
    """

    def __init__(
        self,
        memory_manager: SharedMemoryManager[S],
        queue_maxsize: int = 100,
        loss_threshold: int = _DEFAULT_LOSS_THRESHOLD,
    ) -> None:
        """Initialise the signal processor.

        Args:
            memory_manager: Shared memory manager instance.
            queue_maxsize: Maximum items held in the internal queue.
            loss_threshold: ACK-lag threshold above which a warning is emitted.
        """
        self._memory_manager = memory_manager
        self._queue: SignalQueue[S] = SignalQueue(maxsize=queue_maxsize)
        self._loss_threshold = loss_threshold
        self._running = False
        self._thread: threading.Thread | None = None
        self._connected: list[tuple[Signal, Callable[..., None]]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect_signal(
        self,
        signal: Signal,
        signal_type: S,
        data_mapper: DataMapper | None = None,
    ) -> None:
        """Subscribe *signal* so that each emission enqueues a work item.

        Args:
            signal: Blinker signal to connect.
            signal_type: Identifies the target shared memory channel.
            data_mapper: Optional callable that transforms the raw signal
                ``**kwargs`` into the dict passed to :meth:`SignalQueue.put`.
                Return ``None`` to discard an emission.
        """

        def _handler(sender: Any, **kwargs: Any) -> None:
            if data_mapper is not None:
                payload = data_mapper(**kwargs)
                if payload is None:
                    return
            else:
                payload = kwargs

            seq = self._queue.put(signal_type, **payload)
            logger.debug(
                "Queued signal {} (seq={}, queue_size={})",
                _type_name(signal_type),
                seq,
                self._queue.size(),
            )

        signal.connect(_handler, weak=False)
        self._connected.append((signal, _handler))
        logger.info("Connected signal processor for {}", _type_name(signal_type))

    def start(self) -> None:
        """Start the background processing thread."""
        if self._running:
            logger.warning("SignalProcessor is already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._process_loop,
            daemon=True,
            name="SignalProcessor",
        )
        self._thread.start()
        logger.info("SignalProcessor started")

    def stop(self) -> None:
        """Stop the background thread and disconnect all signal handlers.

        Blocks until the thread exits or a 2-second timeout elapses.
        """
        self._running = False
        self.disconnect_all()

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("SignalProcessor thread did not stop within timeout")
            self._thread = None

        logger.info("SignalProcessor stopped")

    def disconnect_all(self) -> None:
        """Disconnect every registered signal handler."""
        for sig, handler in self._connected:
            sig.disconnect(handler)
        self._connected.clear()
        logger.info("Disconnected all signal handlers")

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> SignalProcessor[S]:
        """Start the processor and return self."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Stop the processor on context exit."""
        self.stop()

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _process_loop(self) -> None:
        """Dequeue items and write them to shared memory."""
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except Exception as exc:
                logger.error("Error dequeuing item: {}", exc)
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(
                        "Too many consecutive queue errors ({}), stopping processor",
                        consecutive_errors,
                    )
                    self._running = False
                continue

            if item is None:
                continue

            consecutive_errors = 0

            try:
                self._handle_item(item.signal_type, item.seq_num, item.data)
            except Exception as exc:
                logger.error(
                    "Unexpected error processing signal {}: {}",
                    _type_name(item.signal_type),
                    exc,
                    exc_info=True,
                )
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(
                        "Too many consecutive processing errors ({}), stopping processor",
                        consecutive_errors,
                    )
                    self._running = False

    def _handle_item(self, signal_type: S, seq_num: int, data: dict[str, Any]) -> None:
        """Process a single dequeued item.

        Args:
            signal_type: Signal channel identifier.
            seq_num: Sequence number of the item.
            data: Payload dict forwarded to the pack callable.
        """
        # ACK-based signal-loss detection.
        try:
            ack_seq = self._memory_manager.read_ack(signal_type)
        except Exception as exc:
            logger.error("Failed to read ACK for {}: {}", _type_name(signal_type), exc)
            ack_seq = 0

        lag = (seq_num - 1) - ack_seq
        if lag > self._loss_threshold:
            logger.warning(
                "Potential signal loss for {}: ACK at seq {}, writing seq {} ({} signals may be skipped)",
                _type_name(signal_type),
                ack_seq,
                seq_num,
                lag,
            )
        elif lag > 0:
            logger.debug(
                "Consumer slightly behind for {}: {} signal(s) pending",
                _type_name(signal_type),
                lag,
            )

        # Serialise and write.
        try:
            packed = self._memory_manager._registry.pack(signal_type, **data)
        except (ValueError, KeyError, TypeError) as exc:
            logger.error(
                "Failed to pack signal {} (seq={}): {}  data={}",
                _type_name(signal_type),
                seq_num,
                exc,
                data,
            )
            return

        try:
            self._memory_manager.write_signal(signal_type, packed)
            logger.debug(
                "Wrote {} to shared memory (seq={})",
                _type_name(signal_type),
                seq_num,
            )
        except (KeyError, ValueError) as exc:
            logger.error(
                "Failed to write signal {} to shared memory: {}",
                _type_name(signal_type),
                exc,
            )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _type_name(signal_type: SupportsInt) -> str:
    """Return a human-readable name for *signal_type*.

    Uses ``.name`` when available (IntEnum), otherwise falls back to ``repr``.
    """
    return getattr(signal_type, "name", repr(signal_type))

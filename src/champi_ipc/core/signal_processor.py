"""Signal processor - bridges blinker signals to shared memory via FIFO queue.

This module connects blinker signals to the shared memory IPC infrastructure,
queuing signals and processing them in a background thread.
"""

import threading
from collections.abc import Callable
from typing import Any, TypeVar

from blinker import Signal
from loguru import logger

from champi_ipc.base.protocols import SignalTypeProtocol
from champi_ipc.core.shared_memory import SharedMemoryManager
from champi_ipc.core.signal_queue import SignalQueue

SignalT = TypeVar("SignalT", bound=SignalTypeProtocol)

# Type alias for data mapper functions
DataMapper = Callable[..., dict[str, Any] | None]


class SignalProcessor:
    """Bridges blinker signals to shared memory via FIFO queue.

    This class connects to blinker signals, queues them in a thread-safe
    FIFO queue, and processes them in a background thread, writing to
    shared memory.

    Example:
        >>> from blinker import signal
        >>>
        >>> # Create processor
        >>> processor = SignalProcessor(memory_manager)
        >>>
        >>> # Connect signals
        >>> my_signal = signal('my-signal')
        >>> processor.connect_signal(
        ...     my_signal,
        ...     MySignals.SIGNAL_A,
        ...     data_mapper=lambda text: {'text': text}
        ... )
        >>>
        >>> # Start processing
        >>> processor.start()
        >>>
        >>> # Emit signal (will be queued and written to shared memory)
        >>> my_signal.send(text="Hello")
    """

    def __init__(self, memory_manager: SharedMemoryManager) -> None:
        """Initialize signal processor.

        Args:
            memory_manager: Shared memory manager for writing signals
        """
        self.memory_manager = memory_manager
        self.queue = SignalQueue(maxsize=100)
        self.running = False
        self.processor_thread: threading.Thread | None = None
        self.connected_signals: list[tuple[Signal, Callable]] = []

    def connect_signal(
        self,
        signal: Signal,
        signal_type: SignalT,
        data_mapper: DataMapper | None = None,
    ) -> None:
        """Connect a blinker signal to the processor.

        Args:
            signal: Blinker signal to connect
            signal_type: Signal type enum value
            data_mapper: Optional function to map signal kwargs to queue data
                        Signature: (sender, **kwargs) -> dict | None
                        Return None to skip queueing this signal

        Example:
            >>> # Simple mapper extracting specific fields
            >>> def mapper(text, **kwargs):
            ...     return {'text': text[:100]}  # Truncate to 100 chars
            >>>
            >>> processor.connect_signal(my_signal, MySignals.TEXT, mapper)
        """

        def signal_handler(sender, **kwargs):
            # Map signal data if mapper provided
            if data_mapper:
                queue_data = data_mapper(**kwargs)
                # Skip if mapper returns None
                if queue_data is None:
                    return
            else:
                queue_data = kwargs

            # Add to queue
            seq_num = self.queue.put(signal_type, **queue_data)
            logger.debug(
                f"Queued {signal_type.name} (seq: {seq_num}, queue: {self.queue.size()})"
            )

        signal.connect(signal_handler, weak=False)
        self.connected_signals.append((signal, signal_handler))

        logger.info(f"Connected signal processor for {signal_type.name}")

    def start(self) -> None:
        """Start processing signals from queue.

        Launches background thread that pulls from queue and writes to
        shared memory.
        """
        if self.running:
            logger.warning("Signal processor already running")
            return

        self.running = True
        self.processor_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="SignalProcessor"
        )
        self.processor_thread.start()

        logger.info("Signal processor started")

    def stop(self) -> None:
        """Stop processing signals.

        Waits up to 2 seconds for processor thread to finish current item.
        """
        self.running = False

        if self.processor_thread:
            self.processor_thread.join(timeout=2.0)
            self.processor_thread = None

        logger.info("Signal processor stopped")

    def _process_loop(self) -> None:
        """Main processing loop - pulls from queue and writes to shared memory.

        Runs in background thread until stop() is called.
        """
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self.running:
            # Get next item from queue (blocks with timeout)
            try:
                item = self.queue.get(timeout=0.5)

                if item is None:
                    continue  # Timeout, check if still running

                # Reset error counter on successful get
                consecutive_errors = 0

            except Exception as e:
                logger.error(f"Error getting item from queue: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(
                        f"Too many consecutive queue errors ({consecutive_errors}), stopping"
                    )
                    self.running = False
                continue

            try:
                # Check ACK to detect missed signals
                try:
                    ack_seq = self.memory_manager.read_ack(item.signal_type)
                except ValueError as e:
                    logger.error(f"Failed to read ACK for {item.signal_type.name}: {e}")
                    ack_seq = 0  # Assume no ACK

                expected_ack = item.seq_num - 1

                if ack_seq < expected_ack:
                    missed_count = expected_ack - ack_seq
                    logger.warning(
                        f"⚠️  Signal loss for {item.signal_type.name}: "
                        f"Reader at {ack_seq}, writing {item.seq_num} "
                        f"({missed_count} signals skipped)"
                    )

                # Pack signal data into binary struct
                try:
                    packed_data = self.memory_manager.registry.pack(
                        item.signal_type, item.seq_num, **item.data
                    )
                except (ValueError, KeyError, TypeError) as e:
                    logger.error(
                        f"Failed to pack signal {item.signal_type.name} (seq: {item.seq_num}): {e}. "
                        f"Data: {item.data}"
                    )
                    continue

                # Write to shared memory
                try:
                    self.memory_manager.write_signal(item.signal_type, packed_data)
                    logger.debug(
                        f"Wrote {item.signal_type.name} to shared memory (seq: {item.seq_num})"
                    )
                except ValueError as e:
                    logger.error(
                        f"Failed to write signal {item.signal_type.name} to shared memory: {e}"
                    )
                    continue

            except Exception as e:
                logger.error(
                    f"Unexpected error processing signal {item.signal_type.name}: {e}",
                    exc_info=True,
                )
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(
                        f"Too many consecutive processing errors ({consecutive_errors}), stopping"
                    )
                    self.running = False

    def disconnect_all(self) -> None:
        """Disconnect all signal handlers."""
        for signal, handler in self.connected_signals:
            signal.disconnect(handler)

        self.connected_signals.clear()
        logger.info("Disconnected all signal handlers")

    def __enter__(self) -> "SignalProcessor":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
        self.disconnect_all()

"""Signal reader - reads signals from shared memory and dispatches to handlers.

Consumer process (e.g., UI) uses this to poll for new signals and process them.
"""

import struct
import time
from collections.abc import Callable
from typing import Any, TypeVar

from loguru import logger

from champi_ipc.base.protocols import SignalData, SignalTypeProtocol
from champi_ipc.core.shared_memory import SharedMemoryManager

SignalT = TypeVar("SignalT", bound=SignalTypeProtocol)

# Type alias for signal handlers
SignalHandler = Callable[[SignalData], None]


class SignalReader:
    """Reads signals from shared memory and dispatches to handlers.

    Consumer process (e.g., UI) uses this to poll for new signals
    and process them.

    Example:
        >>> # Create reader
        >>> reader = SignalReader(memory_manager)
        >>>
        >>> # Register handlers
        >>> def handle_text(signal_data):
        ...     print(f"Text: {signal_data.data['text']}")
        >>>
        >>> reader.register_handler(MySignals.TEXT, handle_text)
        >>>
        >>> # Poll loop
        >>> reader.poll_loop(poll_rate_hz=60)
    """

    def __init__(self, memory_manager: SharedMemoryManager) -> None:
        """Initialize signal reader.

        Args:
            memory_manager: Shared memory manager for reading signals
        """
        self.memory_manager = memory_manager
        self.handlers: dict[SignalT, SignalHandler] = {}
        self.last_seq_nums: dict[SignalT, int] = dict.fromkeys(
            memory_manager.signal_type_enum, 0
        )
        self.running = False

    def register_handler(self, signal_type: SignalT, handler: SignalHandler) -> None:
        """Register a handler function for a signal type.

        Args:
            signal_type: Signal type to handle
            handler: Callback function
                    Signature: (signal_data: SignalData) -> None

        Example:
            >>> def my_handler(signal_data):
            ...     print(f"Seq: {signal_data.seq_num}")
            ...     print(f"Type: {signal_data.signal_type}")
            ...     print(f"Data: {signal_data.data}")
            >>>
            >>> reader.register_handler(MySignals.TEXT, my_handler)
        """
        self.handlers[signal_type] = handler
        logger.info(f"Registered handler for {signal_type.name}")

    def poll_once(self) -> None:
        """Poll all signal regions once and dispatch any new signals.

        Call this repeatedly in your main loop, or use poll_loop().
        """
        for signal_type in self.memory_manager.signal_type_enum:
            try:
                # Read from shared memory
                try:
                    raw_data = self.memory_manager.read_signal(signal_type)
                except ValueError as e:
                    logger.debug(f"No memory region for {signal_type.name}: {e}")
                    continue

                # Skip uninitialized memory: all structs start with a uint64 seq_num (=Q);
                # a zero seq_num means no signal has been written to this region yet.
                if len(raw_data) < 8 or struct.unpack_from('=Q', raw_data)[0] == 0:
                    continue

                # Unpack struct
                try:
                    signal_data = self.memory_manager.registry.unpack(
                        signal_type, raw_data
                    )
                except (ValueError, struct.error) as e:
                    logger.error(
                        f"Failed to unpack signal {signal_type.name}: {e}. "
                        f"Data length: {len(raw_data)} bytes"
                    )
                    continue

                # Check if this is a new signal (sequence number changed)
                if signal_data.seq_num > self.last_seq_nums[signal_type]:
                    # Detect signal loss
                    expected_seq = self.last_seq_nums[signal_type] + 1
                    if signal_data.seq_num > expected_seq:
                        missed = signal_data.seq_num - expected_seq
                        logger.warning(
                            f"⚠️  Signal loss detected for {signal_type.name}: "
                            f"expected seq {expected_seq}, got {signal_data.seq_num} "
                            f"({missed} signals missed)"
                        )

                    self.last_seq_nums[signal_type] = signal_data.seq_num

                    # Dispatch to handler if registered
                    if signal_type in self.handlers:
                        try:
                            self.handlers[signal_type](signal_data)
                            logger.debug(
                                f"Dispatched {signal_type.name} (seq: {signal_data.seq_num})"
                            )
                        except Exception as e:
                            logger.error(
                                f"Handler error for {signal_type.name} (seq: {signal_data.seq_num}): {e}",
                                exc_info=True,
                            )
                            # Continue processing despite handler error

                    # Write ACK after successfully processing signal
                    try:
                        self.memory_manager.write_ack(signal_type, signal_data.seq_num)
                        logger.debug(
                            f"ACKed {signal_type.name} (seq: {signal_data.seq_num})"
                        )
                    except ValueError as e:
                        logger.error(f"Failed to write ACK for {signal_type.name}: {e}")

            except Exception as e:
                logger.error(
                    f"Unexpected error reading signal {signal_type.name}: {e}",
                    exc_info=True,
                )

    def poll_loop(self, poll_rate_hz: int = 60) -> None:
        """Continuously poll for new signals.

        Args:
            poll_rate_hz: Polling frequency in Hz (default 60)

        Blocks until stop() is called.
        """
        self.running = True
        poll_interval = 1.0 / poll_rate_hz

        logger.info(f"Starting poll loop at {poll_rate_hz} Hz")

        while self.running:
            start_time = time.time()

            self.poll_once()

            # Sleep to maintain poll rate
            elapsed = time.time() - start_time
            sleep_time = max(0, poll_interval - elapsed)
            time.sleep(sleep_time)

        logger.info("Poll loop stopped")

    def stop(self) -> None:
        """Stop the poll loop."""
        self.running = False

    def __enter__(self) -> "SignalReader":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

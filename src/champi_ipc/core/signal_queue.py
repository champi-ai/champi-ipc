"""FIFO signal queue for ordered signal processing.

Thread-safe queue that maintains signal order and generates sequence numbers.
"""

import threading
from collections import deque
from typing import Any, TypeVar

from champi_ipc.base.protocols import SignalTypeProtocol

SignalT = TypeVar("SignalT", bound=SignalTypeProtocol)


class SignalQueueItem:
    """Item in the signal queue.

    Attributes:
        signal_type: Type of signal
        seq_num: Sequence number (monotonically increasing)
        data: Signal-specific data as keyword arguments
    """

    def __init__(self, signal_type: SignalT, seq_num: int, **kwargs: Any):
        """Initialize queue item.

        Args:
            signal_type: Type of signal
            seq_num: Sequence number
            **kwargs: Signal data
        """
        self.signal_type = signal_type
        self.seq_num = seq_num
        self.data = kwargs


class SignalQueue:
    """Thread-safe FIFO queue for signals.

    This queue maintains signal order and automatically assigns
    sequence numbers. It's used by SignalProcessor to queue signals
    before writing them to shared memory.

    Example:
        >>> queue = SignalQueue(maxsize=100)
        >>> seq = queue.put(MySignals.MESSAGE, text="Hello")
        >>> item = queue.get(timeout=1.0)
        >>> print(item.seq_num, item.data)
        1 {'text': 'Hello'}
    """

    def __init__(self, maxsize: int = 100):
        """Initialize signal queue.

        Args:
            maxsize: Maximum queue size (older items dropped if exceeded)
        """
        self.maxsize = maxsize
        self._queue: deque[SignalQueueItem] = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._sequence_counter = 0

    def put(self, signal_type: SignalT, **kwargs: Any) -> int:
        """Add signal to queue.

        Args:
            signal_type: Type of signal
            **kwargs: Signal data

        Returns:
            Sequence number assigned to this signal
        """
        with self._lock:
            self._sequence_counter += 1
            seq_num = self._sequence_counter

            item = SignalQueueItem(signal_type, seq_num, **kwargs)
            self._queue.append(item)

            self._not_empty.notify()

            return seq_num

    def get(self, timeout: float | None = None) -> SignalQueueItem | None:
        """Get next signal from queue (blocks if empty).

        Args:
            timeout: Timeout in seconds (None = wait forever)

        Returns:
            Signal queue item or None on timeout
        """
        with self._not_empty:
            while len(self._queue) == 0:
                if not self._not_empty.wait(timeout=timeout):
                    return None  # Timeout

            return self._queue.popleft()

    def get_nowait(self) -> SignalQueueItem | None:
        """Get next signal without blocking.

        Returns:
            Signal queue item or None if empty
        """
        with self._lock:
            if len(self._queue) == 0:
                return None
            return self._queue.popleft()

    def size(self) -> int:
        """Get current queue size.

        Returns:
            Number of items in queue
        """
        with self._lock:
            return len(self._queue)

    def clear(self) -> None:
        """Clear all items from queue."""
        with self._lock:
            self._queue.clear()

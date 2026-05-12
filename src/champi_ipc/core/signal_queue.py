"""Thread-safe FIFO queue for IPC signals."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, SupportsInt


class SignalQueueItem[S: SupportsInt]:
    """A single entry held inside :class:`SignalQueue`."""

    def __init__(self, signal_type: S, seq_num: int, **kwargs: Any) -> None:
        """Initialise queue item.

        Args:
            signal_type: Identifies the signal channel.
            seq_num: Monotonic sequence number assigned at enqueue time.
            **kwargs: Arbitrary signal payload fields.
        """
        self.signal_type = signal_type
        self.seq_num = seq_num
        self.data: dict[str, Any] = kwargs


class SignalQueue[S: SupportsInt]:
    """Thread-safe FIFO queue for typed IPC signals.

    A bounded deque is used internally; when *maxsize* is reached the
    oldest item is silently dropped (ring-buffer behaviour).

    Type parameter ``S`` must support conversion to ``int`` (any
    ``IntEnum`` satisfies this bound).

    Args:
        maxsize: Maximum number of items to hold before dropping oldest entries.
    """

    def __init__(self, maxsize: int = 100) -> None:
        """Initialise an empty queue.

        Args:
            maxsize: Maximum capacity.
        """
        self.maxsize = maxsize
        self._queue: deque[SignalQueueItem[S]] = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._not_empty: threading.Condition = threading.Condition(self._lock)
        self._sequence_counter = 0

    def put(self, signal_type: S, **kwargs: Any) -> int:
        """Enqueue a signal item and return its sequence number.

        Args:
            signal_type: Identifies the signal channel.
            **kwargs: Arbitrary signal payload forwarded to the queue item.

        Returns:
            The monotonically increasing sequence number assigned to the item.
        """
        with self._not_empty:
            self._sequence_counter += 1
            seq_num = self._sequence_counter
            self._queue.append(SignalQueueItem(signal_type, seq_num, **kwargs))
            self._not_empty.notify()
            return seq_num

    def get(self, timeout: float | None = None) -> SignalQueueItem[S] | None:
        """Dequeue the oldest item, blocking until one is available.

        Args:
            timeout: Maximum seconds to wait.  ``None`` blocks indefinitely.

        Returns:
            The oldest :class:`SignalQueueItem`, or ``None`` if *timeout*
            elapsed before an item arrived.
        """
        with self._not_empty:
            while not self._queue:
                if not self._not_empty.wait(timeout=timeout):
                    return None
            return self._queue.popleft()

    def get_nowait(self) -> SignalQueueItem[S] | None:
        """Dequeue the oldest item without blocking.

        Returns:
            The oldest :class:`SignalQueueItem`, or ``None`` if the queue is empty.
        """
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def size(self) -> int:
        """Return the current number of items in the queue."""
        with self._lock:
            return len(self._queue)

    def clear(self) -> None:
        """Remove all items from the queue."""
        with self._lock:
            self._queue.clear()

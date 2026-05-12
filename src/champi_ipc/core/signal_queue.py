"""Thread-safe FIFO signal queue with sequence tracking."""

import threading
from collections import deque
from dataclasses import dataclass, field
from time import monotonic

from champi_ipc.base.protocols import SignalTypeProtocol


@dataclass
class SignalQueueItem:
    """A single entry in the signal queue.

    Attributes:
        signal_type: The signal type, satisfying SignalTypeProtocol.
        seq_num: Monotonically increasing sequence number assigned at enqueue time.
        data: Arbitrary keyword payload supplied by the caller.
        timestamp: Monotonic clock value at enqueue time (seconds).
    """

    signal_type: SignalTypeProtocol
    seq_num: int
    data: dict[str, object] = field(default_factory=dict)
    timestamp: float = field(default_factory=monotonic)


class SignalQueue:
    """Thread-safe FIFO queue for IPC signals with sequence tracking.

    Items are enqueued with put() and dequeued in FIFO order with get()
    or get_nowait(). Each item receives a monotonically increasing
    sequence number so consumers can detect dropped or out-of-order
    delivery.

    When the queue reaches *maxsize* the oldest item is silently
    dropped (deque behaviour with maxlen).
    """

    def __init__(self, maxsize: int = 100) -> None:
        """Initialise the queue.

        Args:
            maxsize: Maximum number of items the queue can hold.
                     When full, the oldest item is discarded on put().
        """
        self.maxsize = maxsize
        self._queue: deque[SignalQueueItem] = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._sequence_counter: int = 0

    def put(self, signal_type: SignalTypeProtocol, **kwargs: object) -> int:
        """Enqueue a signal.

        Args:
            signal_type: The signal type to enqueue.
            **kwargs: Arbitrary payload attached to the item's ``data`` dict.

        Returns:
            The sequence number assigned to this item.
        """
        with self._not_empty:
            self._sequence_counter += 1
            seq_num = self._sequence_counter
            item = SignalQueueItem(
                signal_type=signal_type,
                seq_num=seq_num,
                data=dict(kwargs),
            )
            self._queue.append(item)
            self._not_empty.notify()
            return seq_num

    def get(self, timeout: float | None = None) -> SignalQueueItem | None:
        """Dequeue the next signal, blocking until one is available.

        Args:
            timeout: Maximum seconds to wait.  ``None`` means wait forever.

        Returns:
            The next SignalQueueItem, or ``None`` if *timeout* expired.
        """
        with self._not_empty:
            while not self._queue:
                if not self._not_empty.wait(timeout=timeout):
                    return None
            return self._queue.popleft()

    def get_nowait(self) -> SignalQueueItem | None:
        """Dequeue the next signal without blocking.

        Returns:
            The next SignalQueueItem, or ``None`` if the queue is empty.
        """
        with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()

    def size(self) -> int:
        """Return the current number of items in the queue."""
        with self._lock:
            return len(self._queue)

    def clear(self) -> None:
        """Remove all items from the queue."""
        with self._lock:
            self._queue.clear()

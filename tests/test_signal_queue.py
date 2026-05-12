"""Unit tests for SignalQueue and SignalQueueItem."""

import threading
import time
from enum import IntEnum

import pytest

from champi_ipc.core.signal_queue import SignalQueue, SignalQueueItem


class FakeSignal(IntEnum):
    """Minimal signal type used exclusively in tests."""

    START = 1
    STOP = 2
    DATA = 3


# ---------------------------------------------------------------------------
# SignalQueueItem
# ---------------------------------------------------------------------------


class TestSignalQueueItem:
    """Tests for the SignalQueueItem dataclass."""

    def test_fields_stored(self) -> None:
        item = SignalQueueItem(signal_type=FakeSignal.START, seq_num=1)
        assert item.signal_type is FakeSignal.START
        assert item.seq_num == 1
        assert item.data == {}

    def test_data_payload(self) -> None:
        item = SignalQueueItem(signal_type=FakeSignal.DATA, seq_num=7, key="value")
        assert item.data == {"key": "value"}

    def test_data_nested(self) -> None:
        item = SignalQueueItem(signal_type=FakeSignal.DATA, seq_num=1, payload={"k": "v"})
        assert item.data == {"payload": {"k": "v"}}


# ---------------------------------------------------------------------------
# SignalQueue — basic put / get
# ---------------------------------------------------------------------------


class TestSignalQueuePutGet:
    """Tests for put() and get() round-trips."""

    def test_put_returns_sequence_number(self) -> None:
        q: SignalQueue = SignalQueue()
        seq = q.put(FakeSignal.START)
        assert seq == 1

    def test_sequence_numbers_increment(self) -> None:
        q: SignalQueue = SignalQueue()
        seqs = [q.put(FakeSignal.START) for _ in range(5)]
        assert seqs == [1, 2, 3, 4, 5]

    def test_get_returns_item(self) -> None:
        q: SignalQueue = SignalQueue()
        q.put(FakeSignal.START, value=42)
        item = q.get(timeout=1.0)
        assert item is not None
        assert item.signal_type is FakeSignal.START
        assert item.data == {"value": 42}

    def test_fifo_order(self) -> None:
        q: SignalQueue = SignalQueue()
        q.put(FakeSignal.START)
        q.put(FakeSignal.DATA)
        q.put(FakeSignal.STOP)

        types = [q.get(timeout=1.0).signal_type for _ in range(3)]  # type: ignore[union-attr]
        assert types == [FakeSignal.START, FakeSignal.DATA, FakeSignal.STOP]

    def test_get_timeout_returns_none_on_empty(self) -> None:
        q: SignalQueue = SignalQueue()
        result = q.get(timeout=0.05)
        assert result is None


# ---------------------------------------------------------------------------
# SignalQueue — get_nowait
# ---------------------------------------------------------------------------


class TestSignalQueueGetNowait:
    """Tests for non-blocking get_nowait()."""

    def test_returns_item_when_available(self) -> None:
        q: SignalQueue = SignalQueue()
        q.put(FakeSignal.STOP)
        item = q.get_nowait()
        assert item is not None
        assert item.signal_type is FakeSignal.STOP

    def test_returns_none_when_empty(self) -> None:
        q: SignalQueue = SignalQueue()
        assert q.get_nowait() is None


# ---------------------------------------------------------------------------
# SignalQueue — size and clear
# ---------------------------------------------------------------------------


class TestSignalQueueSizeAndClear:
    """Tests for size() and clear()."""

    def test_size_reflects_puts(self) -> None:
        q: SignalQueue = SignalQueue()
        assert q.size() == 0
        q.put(FakeSignal.START)
        assert q.size() == 1
        q.put(FakeSignal.STOP)
        assert q.size() == 2

    def test_size_decreases_after_get(self) -> None:
        q: SignalQueue = SignalQueue()
        q.put(FakeSignal.START)
        q.get(timeout=1.0)
        assert q.size() == 0

    def test_clear_empties_queue(self) -> None:
        q: SignalQueue = SignalQueue()
        for _ in range(5):
            q.put(FakeSignal.DATA)
        q.clear()
        assert q.size() == 0
        assert q.get_nowait() is None


# ---------------------------------------------------------------------------
# SignalQueue — maxsize / overflow behaviour
# ---------------------------------------------------------------------------


class TestSignalQueueMaxsize:
    """Tests for maxsize overflow (oldest item dropped)."""

    def test_overflow_drops_oldest(self) -> None:
        q: SignalQueue = SignalQueue(maxsize=3)
        q.put(FakeSignal.START)   # seq 1 — will be dropped
        q.put(FakeSignal.DATA)    # seq 2
        q.put(FakeSignal.STOP)    # seq 3
        q.put(FakeSignal.START)   # seq 4 — pushes seq 1 out

        assert q.size() == 3
        first = q.get(timeout=1.0)
        assert first is not None
        assert first.seq_num == 2  # seq 1 was evicted

    def test_maxsize_one(self) -> None:
        q: SignalQueue = SignalQueue(maxsize=1)
        q.put(FakeSignal.START)
        q.put(FakeSignal.STOP)
        item = q.get(timeout=1.0)
        assert item is not None
        assert item.signal_type is FakeSignal.STOP


# ---------------------------------------------------------------------------
# SignalQueue — thread safety
# ---------------------------------------------------------------------------


class TestSignalQueueThreadSafety:
    """Thread-safety smoke tests."""

    def test_concurrent_producers_all_items_consumed(self) -> None:
        q: SignalQueue = SignalQueue(maxsize=1000)
        n_threads = 10
        items_per_thread = 50

        def producer() -> None:
            for _ in range(items_per_thread):
                q.put(FakeSignal.DATA)

        threads = [threading.Thread(target=producer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert q.size() == n_threads * items_per_thread

    def test_producer_consumer_pair(self) -> None:
        q: SignalQueue = SignalQueue()
        received: list[int] = []
        total = 20

        def producer() -> None:
            for _ in range(total):
                q.put(FakeSignal.DATA)

        def consumer() -> None:
            for _ in range(total):
                item = q.get(timeout=2.0)
                assert item is not None
                received.append(item.seq_num)

        t_prod = threading.Thread(target=producer)
        t_cons = threading.Thread(target=consumer)
        t_cons.start()
        t_prod.start()
        t_prod.join()
        t_cons.join()

        assert len(received) == total
        assert received == sorted(received)


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


def test_public_import() -> None:
    """Verify the public API import path works."""
    from champi_ipc import SignalQueue as SQ
    from champi_ipc import SignalQueueItem as SQI

    assert SQ is SignalQueue
    assert SQI is SignalQueueItem


@pytest.mark.parametrize("maxsize", [1, 10, 100])
def test_default_get_blocks_then_receives(maxsize: int) -> None:
    """A blocking get() unblocks when a producer puts an item."""
    q: SignalQueue = SignalQueue(maxsize=maxsize)
    result: list[SignalQueueItem] = []

    def consumer() -> None:
        item = q.get()  # blocks indefinitely
        if item is not None:
            result.append(item)

    t = threading.Thread(target=consumer)
    t.start()
    time.sleep(0.02)  # give consumer time to block
    q.put(FakeSignal.START)
    t.join(timeout=2.0)

    assert len(result) == 1
    assert result[0].signal_type is FakeSignal.START

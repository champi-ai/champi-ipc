"""Unit tests for SignalQueue."""

import time
from enum import IntEnum
from threading import Thread

import pytest

from champi_ipc.core.signal_queue import SignalQueue


class TestSignals(IntEnum):
    SIGNAL_A = 1
    SIGNAL_B = 2
    SIGNAL_C = 3


def test_queue_initialization():
    """Test queue initializes with sequence number 0."""
    queue = SignalQueue()
    assert queue._sequence_counter == 0


def test_put_increments_sequence():
    """Test that put increments sequence numbers."""
    queue = SignalQueue()

    seq1 = queue.put(TestSignals.SIGNAL_A, value=1)
    seq2 = queue.put(TestSignals.SIGNAL_B, value=2)
    seq3 = queue.put(TestSignals.SIGNAL_C, value=3)

    assert seq1 == 1
    assert seq2 == 2
    assert seq3 == 3


def test_get_returns_items_in_order():
    """Test that get returns items in FIFO order."""
    queue = SignalQueue()

    queue.put(TestSignals.SIGNAL_A, value="first")
    queue.put(TestSignals.SIGNAL_B, value="second")
    queue.put(TestSignals.SIGNAL_C, value="third")

    item1 = queue.get(timeout=0.1)
    item2 = queue.get(timeout=0.1)
    item3 = queue.get(timeout=0.1)

    assert item1 is not None
    assert item1.signal_type == TestSignals.SIGNAL_A
    assert item1.seq_num == 1
    assert item1.data["value"] == "first"

    assert item2 is not None
    assert item2.signal_type == TestSignals.SIGNAL_B
    assert item2.seq_num == 2

    assert item3 is not None
    assert item3.signal_type == TestSignals.SIGNAL_C
    assert item3.seq_num == 3


def test_get_empty_queue_timeout():
    """Test that get returns None on timeout when queue is empty."""
    queue = SignalQueue()

    start = time.time()
    item = queue.get(timeout=0.1)
    elapsed = time.time() - start

    assert item is None
    assert elapsed >= 0.1
    assert elapsed < 0.2  # Should not wait much longer than timeout


def test_get_blocking_until_item_available():
    """Test that get blocks until item is available."""
    queue = SignalQueue()

    def delayed_put():
        time.sleep(0.1)
        queue.put(TestSignals.SIGNAL_A, value="delayed")

    # Start thread that will put item after 0.1s
    thread = Thread(target=delayed_put)
    thread.start()

    # This should block until item is available
    start = time.time()
    item = queue.get(timeout=1.0)
    elapsed = time.time() - start

    thread.join()

    assert item is not None
    assert item.data["value"] == "delayed"
    assert elapsed >= 0.1
    assert elapsed < 0.5  # Should unblock soon after put


def test_multiple_data_fields():
    """Test that multiple data fields are preserved."""
    queue = SignalQueue()

    queue.put(TestSignals.SIGNAL_A, x=10, y=20, text="hello", flag=True)

    item = queue.get(timeout=0.1)
    assert item is not None
    assert item.data["x"] == 10
    assert item.data["y"] == 20
    assert item.data["text"] == "hello"
    assert item.data["flag"] is True


def test_empty_data():
    """Test that signals can be put with no data."""
    queue = SignalQueue()

    queue.put(TestSignals.SIGNAL_A)

    item = queue.get(timeout=0.1)
    assert item is not None
    assert item.signal_type == TestSignals.SIGNAL_A
    assert item.data == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

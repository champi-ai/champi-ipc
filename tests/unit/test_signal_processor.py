"""Unit tests for SignalProcessor."""

import struct
import time
from enum import IntEnum

import pytest
from blinker import signal

from champi_ipc import SignalData, StructRegistry
from champi_ipc.core.shared_memory import SharedMemoryManager
from champi_ipc.core.signal_processor import SignalProcessor


class TestSignals(IntEnum):
    SIGNAL_A = 1
    SIGNAL_B = 2


TEST_STRUCT = struct.Struct("=QB23s")


def pack_signal_a(seq_num: int = 0, **kwargs: object) -> bytes:
    text = kwargs.get("text", "")
    assert isinstance(text, str)
    text_bytes = text.encode()[:23].ljust(23, b"\x00")
    return TEST_STRUCT.pack(seq_num, TestSignals.SIGNAL_A, text_bytes)


def unpack_signal_a(data: bytes) -> SignalData:
    seq_num, signal_type, text_bytes = TEST_STRUCT.unpack(data)
    return SignalData(
        signal_type=TestSignals(signal_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )


def pack_signal_b(seq_num: int = 0, **kwargs: object) -> bytes:
    value = kwargs.get("value", 0)
    assert isinstance(value, int)
    text_bytes = str(value).encode()[:23].ljust(23, b"\x00")
    return TEST_STRUCT.pack(seq_num, TestSignals.SIGNAL_B, text_bytes)


def unpack_signal_b(data: bytes) -> SignalData:
    seq_num, signal_type, text_bytes = TEST_STRUCT.unpack(data)
    value_str = text_bytes.rstrip(b"\x00").decode()
    return SignalData(
        signal_type=TestSignals(signal_type),
        seq_num=seq_num,
        data={"value": int(value_str) if value_str else 0},
    )


@pytest.fixture
def registry():
    """Create test registry."""
    reg = StructRegistry()
    reg.register(TestSignals.SIGNAL_A, TEST_STRUCT.size, pack_signal_a, unpack_signal_a)
    reg.register(TestSignals.SIGNAL_B, TEST_STRUCT.size, pack_signal_b, unpack_signal_b)
    return reg


@pytest.fixture
def manager(registry):
    """Create test manager."""
    mgr = SharedMemoryManager("champi_ipc_test_proc", registry)
    mgr.create_regions([TestSignals.SIGNAL_A, TestSignals.SIGNAL_B])
    yield mgr
    mgr.cleanup()


@pytest.fixture
def processor(manager):
    """Create test processor."""
    proc = SignalProcessor(manager)
    yield proc
    if proc._running:
        proc.stop()


def test_processor_initialization(manager):
    """Test processor initializes correctly."""
    processor = SignalProcessor(manager)

    assert processor._memory_manager == manager
    assert processor._running is False
    assert processor._thread is None


def test_connect_signal(processor):
    """Test connecting blinker signal to processor."""
    test_signal = signal("test_signal")

    processor.connect_signal(test_signal, TestSignals.SIGNAL_A)

    assert len(processor._connected) > 0


def test_connect_signal_with_mapper(processor):
    """Test connecting signal with data mapper."""
    test_signal = signal("test_signal_mapper")

    def mapper(x, y):
        return {"text": f"{x},{y}"}

    processor.connect_signal(test_signal, TestSignals.SIGNAL_A, mapper)

    assert len(processor._connected) > 0


def test_start_stop(processor):
    """Test starting and stopping processor."""
    processor.start()

    assert processor._running is True
    assert processor._thread is not None
    assert processor._thread.is_alive()

    processor.stop()

    assert processor._running is False


def test_signal_emitted_and_written(processor, manager, registry):
    """Test that emitted signals are written to shared memory."""
    test_signal = signal("test_emit")

    processor.connect_signal(
        test_signal, TestSignals.SIGNAL_A, lambda text: {"text": text}
    )

    processor.start()

    # Emit signal
    test_signal.send(text="test message")

    # Give processor time to process
    time.sleep(0.1)

    # Read from shared memory
    raw_data = manager.read_signal(TestSignals.SIGNAL_A)
    signal_data = registry.unpack(TestSignals.SIGNAL_A, raw_data)

    assert signal_data.signal_type == TestSignals.SIGNAL_A
    assert signal_data.data["text"] == "test message"

    processor.stop()


def test_multiple_signals_queued(processor, manager, registry):
    """Test that multiple signals are queued and processed in order."""
    test_signal = signal("test_multi")

    processor.connect_signal(
        test_signal, TestSignals.SIGNAL_A, lambda text: {"text": text}
    )

    processor.start()

    # Emit multiple signals quickly
    test_signal.send(text="first")
    test_signal.send(text="second")
    test_signal.send(text="third")

    # Give time to process all
    time.sleep(0.2)

    # The last one written should be visible
    raw_data = manager.read_signal(TestSignals.SIGNAL_A)
    signal_data = registry.unpack(TestSignals.SIGNAL_A, raw_data)

    assert signal_data.data["text"] == "third"

    processor.stop()


def test_queue_processing(processor, manager):
    """Test that signals are queued and processed."""
    test_signal = signal("test_queue")

    processor.connect_signal(
        test_signal, TestSignals.SIGNAL_B, lambda value: {"value": value}
    )

    processor.start()

    test_signal.send(value=42)

    time.sleep(0.2)

    # Verify signal was queued (queue should be empty after processing)
    assert processor._queue.size() == 0

    processor.stop()


def test_stop_without_start(processor):
    """Test that stopping without starting doesn't error."""
    processor.stop()  # Should not raise


def test_multiple_signal_types(processor, manager, registry):
    """Test processing multiple signal types."""
    signal_a = signal("multi_a")
    signal_b = signal("multi_b")

    processor.connect_signal(
        signal_a, TestSignals.SIGNAL_A, lambda text: {"text": text}
    )
    processor.connect_signal(
        signal_b, TestSignals.SIGNAL_B, lambda value: {"value": value}
    )

    processor.start()

    signal_a.send(text="hello")
    signal_b.send(value=123)

    time.sleep(0.2)

    raw_a = manager.read_signal(TestSignals.SIGNAL_A)
    raw_b = manager.read_signal(TestSignals.SIGNAL_B)

    data_a = registry.unpack(TestSignals.SIGNAL_A, raw_a)
    data_b = registry.unpack(TestSignals.SIGNAL_B, raw_b)

    assert data_a.data["text"] == "hello"
    assert data_b.data["value"] == 123

    processor.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

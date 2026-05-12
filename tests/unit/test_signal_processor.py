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


def pack_signal_a(seq_num: int, **kwargs) -> bytes:
    """Pack signal A."""
    text = kwargs.get("text", "")
    text_bytes = text.encode()[:23].ljust(23, b"\x00")
    return TEST_STRUCT.pack(seq_num, TestSignals.SIGNAL_A, text_bytes)


def unpack_signal_a(data: bytes) -> SignalData:
    """Unpack signal A."""
    seq_num, signal_type, text_bytes = TEST_STRUCT.unpack(data)
    return SignalData(
        signal_type=TestSignals(signal_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )


def pack_signal_b(seq_num: int, **kwargs) -> bytes:
    """Pack signal B."""
    value = kwargs.get("value", 0)
    text_bytes = str(value).encode()[:23].ljust(23, b"\x00")
    return TEST_STRUCT.pack(seq_num, TestSignals.SIGNAL_B, text_bytes)


def unpack_signal_b(data: bytes) -> SignalData:
    """Unpack signal B."""
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
    mgr = SharedMemoryManager("test_processor", TestSignals, registry)
    mgr.create_regions()
    yield mgr
    mgr.cleanup()


@pytest.fixture
def processor(manager):
    """Create test processor."""
    proc = SignalProcessor(manager)
    yield proc
    if proc.running:
        proc.stop()


def test_processor_initialization(manager):
    """Test processor initializes correctly."""
    processor = SignalProcessor(manager)

    assert processor.memory_manager == manager
    assert processor.running is False
    assert processor.processor_thread is None


def test_connect_signal(processor):
    """Test connecting blinker signal to processor."""
    test_signal = signal("test_signal")

    processor.connect_signal(test_signal, TestSignals.SIGNAL_A)

    # Signal should be in connections
    assert len(processor.connected_signals) > 0


def test_connect_signal_with_mapper(processor):
    """Test connecting signal with data mapper."""
    test_signal = signal("test_signal_mapper")

    def mapper(x, y):
        return {"text": f"{x},{y}"}

    processor.connect_signal(test_signal, TestSignals.SIGNAL_A, mapper)

    assert len(processor.connected_signals) > 0


def test_start_stop(processor):
    """Test starting and stopping processor."""
    processor.start()

    assert processor.running is True
    assert processor.processor_thread is not None
    assert processor.processor_thread.is_alive()

    processor.stop()

    assert processor.running is False
    # Thread should be cleaned up (set to None by stop())
    assert processor.processor_thread is None


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
    assert signal_data.seq_num == 1

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

    # Sequence number should be 3 (third signal)
    assert signal_data.seq_num == 3

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
    assert processor.queue.size() == 0

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

"""Unit tests for SignalReader."""

import struct
from enum import IntEnum

import pytest

from champi_ipc import SignalData, StructRegistry
from champi_ipc.core.shared_memory import SharedMemoryManager
from champi_ipc.core.signal_reader import SignalReader


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
    mgr = SharedMemoryManager("test_reader", TestSignals, registry)
    mgr.create_regions()
    yield mgr
    mgr.cleanup()


@pytest.fixture
def reader(manager):
    """Create test reader."""
    return SignalReader(manager)


def test_reader_initialization(manager):
    """Test reader initializes correctly."""
    reader = SignalReader(manager)

    assert reader.memory_manager == manager
    assert reader.handlers == {}
    assert reader.last_seq_nums == {TestSignals.SIGNAL_A: 0, TestSignals.SIGNAL_B: 0}


def test_register_handler(reader):
    """Test registering signal handler."""

    def handler(signal_data):
        pass

    reader.register_handler(TestSignals.SIGNAL_A, handler)

    assert TestSignals.SIGNAL_A in reader.handlers
    assert reader.handlers[TestSignals.SIGNAL_A] == handler


def test_poll_once_no_new_signals(reader):
    """Test polling when no new signals."""
    # Don't write anything, just poll
    reader.poll_once()

    # Should keep last_seq_nums at 0
    assert reader.last_seq_nums.get(TestSignals.SIGNAL_A, 0) == 0
    assert reader.last_seq_nums.get(TestSignals.SIGNAL_B, 0) == 0


def test_poll_once_with_new_signal(reader, manager, registry):
    """Test polling reads new signal and calls handler."""
    received_signals = []

    def handler(signal_data):
        received_signals.append(signal_data)

    reader.register_handler(TestSignals.SIGNAL_A, handler)

    # Write a signal
    packed = registry.pack(TestSignals.SIGNAL_A, 1, text="test")
    manager.write_signal(TestSignals.SIGNAL_A, packed)
    manager.write_ack(TestSignals.SIGNAL_A, 1)

    # Poll
    reader.poll_once()

    # Handler should have been called
    assert len(received_signals) == 1
    assert received_signals[0].seq_num == 1
    assert received_signals[0].data["text"] == "test"

    # last_seq_nums should be updated
    assert reader.last_seq_nums[TestSignals.SIGNAL_A] == 1


def test_poll_multiple_signals(reader, manager, registry):
    """Test polling with multiple signals."""
    received_a = []
    received_b = []

    reader.register_handler(TestSignals.SIGNAL_A, lambda s: received_a.append(s))
    reader.register_handler(TestSignals.SIGNAL_B, lambda s: received_b.append(s))

    # Write signals
    packed_a = registry.pack(TestSignals.SIGNAL_A, 1, text="first")
    manager.write_signal(TestSignals.SIGNAL_A, packed_a)
    manager.write_ack(TestSignals.SIGNAL_A, 1)

    packed_b = registry.pack(TestSignals.SIGNAL_B, 1, value=42)
    manager.write_signal(TestSignals.SIGNAL_B, packed_b)
    manager.write_ack(TestSignals.SIGNAL_B, 1)

    # Poll
    reader.poll_once()

    assert len(received_a) == 1
    assert received_a[0].data["text"] == "first"

    assert len(received_b) == 1
    assert received_b[0].data["value"] == 42


def test_poll_only_new_signals(reader, manager, registry):
    """Test that poll only processes new signals."""
    received = []

    reader.register_handler(TestSignals.SIGNAL_A, lambda s: received.append(s))

    # Write and poll first signal
    packed = registry.pack(TestSignals.SIGNAL_A, 1, text="first")
    manager.write_signal(TestSignals.SIGNAL_A, packed)
    manager.write_ack(TestSignals.SIGNAL_A, 1)
    reader.poll_once()

    assert len(received) == 1

    # Poll again without new signal
    reader.poll_once()

    # Should not receive again
    assert len(received) == 1

    # Write new signal
    packed2 = registry.pack(TestSignals.SIGNAL_A, 2, text="second")
    manager.write_signal(TestSignals.SIGNAL_A, packed2)
    manager.write_ack(TestSignals.SIGNAL_A, 2)
    reader.poll_once()

    # Should receive only new signal
    assert len(received) == 2
    assert received[1].seq_num == 2


def test_detect_signal_loss(reader, manager, registry):
    """Test detection of signal loss."""
    received = []
    reader.register_handler(TestSignals.SIGNAL_A, lambda s: received.append(s))

    # Write signal with seq_num 5 (skipping 1-4)
    packed = registry.pack(TestSignals.SIGNAL_A, 5, text="test")
    manager.write_signal(TestSignals.SIGNAL_A, packed)
    manager.write_ack(TestSignals.SIGNAL_A, 5)

    # Poll should handle it (last_seq_nums starts at 0, so loss is detected)
    reader.poll_once()

    # Should still receive the signal despite loss
    assert len(received) == 1
    assert received[0].seq_num == 5


def test_no_handler_registered(reader, manager, registry):
    """Test polling signal type with no handler."""
    # Write signal but don't register handler
    packed = registry.pack(TestSignals.SIGNAL_A, 1, text="test")
    manager.write_signal(TestSignals.SIGNAL_A, packed)
    manager.write_ack(TestSignals.SIGNAL_A, 1)

    # Poll should not error
    reader.poll_once()


def test_handler_exception_doesnt_crash(reader, manager, registry):
    """Test that handler exceptions don't crash polling."""

    def bad_handler(signal_data):
        raise ValueError("Handler error!")

    reader.register_handler(TestSignals.SIGNAL_A, bad_handler)

    packed = registry.pack(TestSignals.SIGNAL_A, 1, text="test")
    manager.write_signal(TestSignals.SIGNAL_A, packed)
    manager.write_ack(TestSignals.SIGNAL_A, 1)

    # Poll should handle exception gracefully (not crash)
    reader.poll_once()

    # ACK should still be written despite handler error
    ack = manager.read_ack(TestSignals.SIGNAL_A)
    assert ack == 1


def test_sequence_number_overflow(reader, manager, registry):
    """Test handling of large sequence numbers."""
    received = []
    reader.register_handler(TestSignals.SIGNAL_A, lambda s: received.append(s))

    # Start with large seq num
    large_seq = 2**60
    packed = registry.pack(TestSignals.SIGNAL_A, large_seq, text="test")
    manager.write_signal(TestSignals.SIGNAL_A, packed)
    manager.write_ack(TestSignals.SIGNAL_A, large_seq)

    reader.poll_once()

    assert len(received) == 1
    assert received[0].seq_num == large_seq


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

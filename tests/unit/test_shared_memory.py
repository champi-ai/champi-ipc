"""Unit tests for SharedMemoryManager."""

import struct
from enum import IntEnum

import pytest

from champi_ipc import SignalData, StructRegistry
from champi_ipc.core.shared_memory import SharedMemoryManager


class TestSignals(IntEnum):
    SIGNAL_A = 1
    SIGNAL_B = 2


# Define struct for testing
TEST_STRUCT = struct.Struct("=QB23s")  # seq_num, signal_type, data (total 32 bytes)


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
    """Create a test registry."""
    reg = StructRegistry()
    reg.register(TestSignals.SIGNAL_A, TEST_STRUCT.size, pack_signal_a, unpack_signal_a)
    reg.register(TestSignals.SIGNAL_B, TEST_STRUCT.size, pack_signal_b, unpack_signal_b)
    return reg


@pytest.fixture
def manager(registry):
    """Create a test manager."""
    mgr = SharedMemoryManager("test_manager", TestSignals, registry)
    yield mgr
    # Cleanup after test
    try:
        mgr.cleanup()
    except Exception:  # noqa: S110
        pass


def test_manager_initialization(registry):
    """Test manager initializes correctly."""
    manager = SharedMemoryManager("test_init", TestSignals, registry)

    assert manager.name_prefix == "test_init"
    assert manager.signal_type_enum == TestSignals
    assert manager.registry == registry
    assert manager.memory_regions == {}
    assert manager.ack_regions == {}


def test_create_regions(manager):
    """Test creating shared memory regions."""
    manager.create_regions()

    # Should have regions for both signal types
    assert TestSignals.SIGNAL_A in manager.memory_regions
    assert TestSignals.SIGNAL_B in manager.memory_regions
    assert TestSignals.SIGNAL_A in manager.ack_regions
    assert TestSignals.SIGNAL_B in manager.ack_regions

    # Check region names
    region_a = manager.memory_regions[TestSignals.SIGNAL_A]
    assert region_a.name == "test_manager_signal_a"


def test_attach_regions(registry):
    """Test attaching to existing regions."""
    # First create regions
    creator = SharedMemoryManager("test_attach", TestSignals, registry)
    creator.create_regions()

    try:
        # Now attach to them
        attacher = SharedMemoryManager("test_attach", TestSignals, registry)
        attacher.attach_regions()

        # Should have regions
        assert TestSignals.SIGNAL_A in attacher.memory_regions
        assert TestSignals.SIGNAL_B in attacher.memory_regions
        assert TestSignals.SIGNAL_A in attacher.ack_regions
        assert TestSignals.SIGNAL_B in attacher.ack_regions

        attacher.cleanup()
    finally:
        creator.cleanup()


def test_attach_nonexistent_regions(manager):
    """Test attaching to non-existent regions raises error."""
    with pytest.raises(FileNotFoundError):
        manager.attach_regions()


def test_write_signal(manager, registry):
    """Test writing signal to shared memory."""
    manager.create_regions()

    # Pack data first
    packed = registry.pack(TestSignals.SIGNAL_A, 1, text="hello")

    # Write signal
    manager.write_signal(TestSignals.SIGNAL_A, packed)

    # Read it back directly from shared memory
    region = manager.memory_regions[TestSignals.SIGNAL_A]
    data = bytes(region.buf[: TEST_STRUCT.size])

    signal_data = unpack_signal_a(data)
    assert signal_data.seq_num == 1
    assert signal_data.data["text"] == "hello"


def test_read_signal(manager):
    """Test reading signal from shared memory."""
    manager.create_regions()

    # Write signal directly to shared memory
    packed = pack_signal_b(42, value=999)
    region = manager.memory_regions[TestSignals.SIGNAL_B]
    region.buf[: TEST_STRUCT.size] = packed

    # Read it back using manager
    raw_data = manager.read_signal(TestSignals.SIGNAL_B)
    signal_data = unpack_signal_b(raw_data)

    assert signal_data.seq_num == 42
    assert signal_data.data["value"] == 999


def test_write_ack(manager):
    """Test writing ACK."""
    manager.create_regions()

    manager.write_ack(TestSignals.SIGNAL_A, 123)

    # Read ACK directly
    ack_region = manager.ack_regions[TestSignals.SIGNAL_A]
    ack_bytes = bytes(ack_region.buf[:8])
    ack_seq = int.from_bytes(ack_bytes, "little")

    assert ack_seq == 123


def test_read_ack(manager):
    """Test reading ACK."""
    manager.create_regions()

    # Write ACK directly
    ack_region = manager.ack_regions[TestSignals.SIGNAL_B]
    ack_region.buf[:8] = (456).to_bytes(8, "little")

    # Read it back
    ack_seq = manager.read_ack(TestSignals.SIGNAL_B)
    assert ack_seq == 456


def test_context_manager(registry):
    """Test using manager as context manager."""
    with SharedMemoryManager("test_context", TestSignals, registry) as manager:
        manager.create_regions()
        assert TestSignals.SIGNAL_A in manager.memory_regions

    # After exiting context, regions should be cleaned up
    # (Can't easily verify this without trying to attach, which would recreate)


def test_cleanup(manager):
    """Test cleanup removes regions."""
    manager.create_regions()

    # Verify regions exist
    assert len(manager.memory_regions) > 0
    assert len(manager.ack_regions) > 0

    manager.cleanup()

    # Verify regions are cleared
    assert len(manager.memory_regions) == 0
    assert len(manager.ack_regions) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

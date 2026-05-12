"""Unit tests for StructRegistry."""

from enum import IntEnum

import pytest

from champi_ipc import SignalData, StructRegistry


class TestSignals(IntEnum):
    SIGNAL_A = 1
    SIGNAL_B = 2


def pack_signal_a(seq_num: int, **kwargs) -> bytes:
    """Pack signal A as simple bytes."""
    return seq_num.to_bytes(8, "little") + b"\x01" + b"\x00" * 23


def unpack_signal_a(data: bytes) -> SignalData:
    """Unpack signal A."""
    return SignalData(
        signal_type=TestSignals.SIGNAL_A,
        seq_num=int.from_bytes(data[:8], "little"),
        data={},
    )


def test_register_signal_type():
    """Test registering a signal type."""
    registry = StructRegistry()
    registry.register(TestSignals.SIGNAL_A, 32, pack_signal_a, unpack_signal_a)

    assert registry.get_struct_size(TestSignals.SIGNAL_A) == 32


def test_pack_unpack():
    """Test packing and unpacking signals."""
    registry = StructRegistry()
    registry.register(TestSignals.SIGNAL_A, 32, pack_signal_a, unpack_signal_a)

    # Pack
    packed = registry.pack(TestSignals.SIGNAL_A, 42)
    assert len(packed) == 32

    # Unpack
    signal_data = registry.unpack(TestSignals.SIGNAL_A, packed)
    assert signal_data.seq_num == 42
    assert signal_data.signal_type == TestSignals.SIGNAL_A


def test_missing_signal_type():
    """Test error when accessing unregistered signal type."""
    registry = StructRegistry()

    with pytest.raises(KeyError):
        registry.get_struct_size(TestSignals.SIGNAL_A)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

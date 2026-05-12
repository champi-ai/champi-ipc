"""Unit tests for StructRegistry and ack helpers."""

import struct
from enum import IntEnum

import pytest

from champi_ipc.base.exceptions import SignalTypeNotRegisteredError
from champi_ipc.base.struct_registry import StructRegistry
from champi_ipc.utils.ack import get_ack_size, pack_ack, unpack_ack

# ---------------------------------------------------------------------------
# Fixtures — minimal signal enum and pack/unpack callables
# ---------------------------------------------------------------------------

_POINT_STRUCT = struct.Struct("=ff")  # two little-endian floats: x, y


class FakeSignal(IntEnum):
    """Minimal signal type used exclusively in tests."""

    POINT = 1
    LABEL = 2
    UNUSED = 99


def _pack_point(*, x: float = 0.0, y: float = 0.0) -> bytes:
    return _POINT_STRUCT.pack(x, y)


def _unpack_point(data: bytes) -> tuple[float, float]:
    x, y = _POINT_STRUCT.unpack(data[: _POINT_STRUCT.size])
    return x, y


# ---------------------------------------------------------------------------
# StructRegistry — register
# ---------------------------------------------------------------------------


class TestStructRegistryRegister:
    """Tests for register()."""

    def test_register_succeeds(self) -> None:
        reg: StructRegistry[FakeSignal] = StructRegistry()
        reg.register(FakeSignal.POINT, _POINT_STRUCT.size, _pack_point, _unpack_point)

    def test_duplicate_raises_value_error(self) -> None:
        reg: StructRegistry[FakeSignal] = StructRegistry()
        reg.register(FakeSignal.POINT, _POINT_STRUCT.size, _pack_point, _unpack_point)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(
                FakeSignal.POINT, _POINT_STRUCT.size, _pack_point, _unpack_point
            )

    def test_multiple_signal_types(self) -> None:
        reg: StructRegistry[FakeSignal] = StructRegistry()
        reg.register(FakeSignal.POINT, _POINT_STRUCT.size, _pack_point, _unpack_point)
        reg.register(FakeSignal.LABEL, 4, lambda **kw: b"\x00" * 4, lambda d: None)


# ---------------------------------------------------------------------------
# StructRegistry — get_size
# ---------------------------------------------------------------------------


class TestStructRegistryGetSize:
    """Tests for get_size()."""

    def test_returns_registered_size(self) -> None:
        reg: StructRegistry[FakeSignal] = StructRegistry()
        reg.register(FakeSignal.POINT, _POINT_STRUCT.size, _pack_point, _unpack_point)
        assert reg.get_size(FakeSignal.POINT) == _POINT_STRUCT.size

    def test_unknown_raises_signal_type_not_registered_error(self) -> None:
        reg: StructRegistry[FakeSignal] = StructRegistry()
        with pytest.raises(SignalTypeNotRegisteredError):
            reg.get_size(FakeSignal.UNUSED)


# ---------------------------------------------------------------------------
# StructRegistry — pack / unpack round-trip
# ---------------------------------------------------------------------------


class TestStructRegistryPackUnpack:
    """Tests for pack() and unpack()."""

    def _make_registry(self) -> StructRegistry[FakeSignal]:
        reg: StructRegistry[FakeSignal] = StructRegistry()
        reg.register(FakeSignal.POINT, _POINT_STRUCT.size, _pack_point, _unpack_point)
        return reg

    def test_pack_returns_bytes(self) -> None:
        reg = self._make_registry()
        result = reg.pack(FakeSignal.POINT, x=1.0, y=2.0)
        assert isinstance(result, bytes)
        assert len(result) == _POINT_STRUCT.size

    def test_unpack_round_trip(self) -> None:
        reg = self._make_registry()
        packed = reg.pack(FakeSignal.POINT, x=3.14, y=-1.5)
        x, y = reg.unpack(FakeSignal.POINT, packed)  # type: ignore[misc]
        assert x == pytest.approx(3.14, rel=1e-5)
        assert y == pytest.approx(-1.5, rel=1e-5)

    def test_pack_unknown_raises(self) -> None:
        reg = self._make_registry()
        with pytest.raises(SignalTypeNotRegisteredError):
            reg.pack(FakeSignal.UNUSED)

    def test_unpack_unknown_raises(self) -> None:
        reg = self._make_registry()
        with pytest.raises(SignalTypeNotRegisteredError):
            reg.unpack(FakeSignal.UNUSED, b"\x00" * 8)


# ---------------------------------------------------------------------------
# ACK helpers
# ---------------------------------------------------------------------------


class TestAck:
    """Tests for pack_ack, unpack_ack, get_ack_size."""

    def test_size_is_eight(self) -> None:
        assert get_ack_size() == 8

    def test_round_trip_zero(self) -> None:
        assert unpack_ack(pack_ack(0)) == 0

    def test_round_trip_max_u64(self) -> None:
        max_seq = 2**64 - 1
        assert unpack_ack(pack_ack(max_seq)) == max_seq

    @pytest.mark.parametrize("seq", [1, 42, 1_000_000, 2**32])
    def test_round_trip_various(self, seq: int) -> None:
        assert unpack_ack(pack_ack(seq)) == seq

    def test_packed_length(self) -> None:
        assert len(pack_ack(7)) == get_ack_size()


# ---------------------------------------------------------------------------
# Public import smoke test
# ---------------------------------------------------------------------------


def test_public_import_struct_registry() -> None:
    """Verify StructRegistry is importable from the top-level package."""
    from champi_ipc import StructRegistry as SR

    assert SR is StructRegistry


def test_public_import_ack_helpers() -> None:
    """Verify ACK helpers are importable from the top-level package."""
    from champi_ipc import get_ack_size as gas
    from champi_ipc import pack_ack as pa
    from champi_ipc import unpack_ack as ua

    assert gas is get_ack_size
    assert pa is pack_ack
    assert ua is unpack_ack

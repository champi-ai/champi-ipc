"""Tests for SharedMemoryManager: create/attach cycle, read/write, cleanup."""

from __future__ import annotations

import struct
from enum import IntEnum

import pytest

from champi_ipc.base.exceptions import RegionNotFoundError
from champi_ipc.base.struct_registry import StructRegistry
from champi_ipc.core.shared_memory_manager import SharedMemoryManager
from champi_ipc.utils.ack import pack_ack, unpack_ack

# ---------------------------------------------------------------------------
# Minimal signal enum and serialisation helpers
# ---------------------------------------------------------------------------

_PT_STRUCT = struct.Struct("=ff")  # two native-order floats: x, y


class Sig(IntEnum):
    POINT = 1
    LABEL = 2


def _pack_point(*, x: float = 0.0, y: float = 0.0) -> bytes:
    return _PT_STRUCT.pack(x, y)


def _unpack_point(data: bytes) -> tuple[float, float]:
    return _PT_STRUCT.unpack(data)  # type: ignore[return-value]


def _build_registry() -> StructRegistry[Sig]:
    reg: StructRegistry[Sig] = StructRegistry()
    reg.register(Sig.POINT, _PT_STRUCT.size, _pack_point, _unpack_point)
    return reg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PREFIX = "test_smm_champi"


def _mgr(prefix: str = _PREFIX) -> SharedMemoryManager[Sig]:
    return SharedMemoryManager(prefix=prefix, registry=_build_registry())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateAndCleanup:
    def test_create_and_cleanup_removes_regions(self) -> None:
        mgr = _mgr()
        mgr.create_regions([Sig.POINT])
        mgr.cleanup()
        # After cleanup the creator should have unlinked; attaching must fail.
        attacher = _mgr()
        with pytest.raises(RegionNotFoundError):
            attacher.attach_regions([Sig.POINT])

    def test_context_manager_cleans_up_on_normal_exit(self) -> None:
        with _mgr() as mgr:
            mgr.create_regions([Sig.POINT])
        attacher = _mgr()
        with pytest.raises(RegionNotFoundError):
            attacher.attach_regions([Sig.POINT])

    def test_context_manager_cleans_up_on_exception(self) -> None:
        try:
            with _mgr() as mgr:
                mgr.create_regions([Sig.POINT])
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        attacher = _mgr()
        with pytest.raises(RegionNotFoundError):
            attacher.attach_regions([Sig.POINT])

    def test_cleanup_is_idempotent(self) -> None:
        mgr = _mgr()
        mgr.create_regions([Sig.POINT])
        mgr.cleanup()
        mgr.cleanup()  # must not raise


class TestWriteReadSignal:
    def test_write_read_roundtrip_preserves_bytes(self) -> None:
        prefix = "test_smm_rtrip"
        with SharedMemoryManager(prefix=prefix, registry=_build_registry()) as mgr:
            mgr.create_regions([Sig.POINT])
            payload = _pack_point(x=3.14, y=-2.71)
            mgr.write_signal(Sig.POINT, payload)
            result = mgr.read_signal(Sig.POINT)
        assert result == payload

    def test_write_signal_rejects_oversized_data(self) -> None:
        prefix = "test_smm_oversize"
        with SharedMemoryManager(prefix=prefix, registry=_build_registry()) as mgr:
            mgr.create_regions([Sig.POINT])
            big = bytes(_PT_STRUCT.size + 1)
            with pytest.raises(ValueError, match="exceeds region size"):
                mgr.write_signal(Sig.POINT, big)

    def test_read_signal_without_region_raises(self) -> None:
        mgr = _mgr("test_smm_noreg")
        with pytest.raises(KeyError):
            mgr.read_signal(Sig.POINT)


class TestWriteReadAck:
    def test_write_read_ack_roundtrip(self) -> None:
        prefix = "test_smm_ack"
        with SharedMemoryManager(prefix=prefix, registry=_build_registry()) as mgr:
            mgr.create_regions([Sig.POINT])
            mgr.write_ack(Sig.POINT, 42)
            seq = mgr.read_ack(Sig.POINT)
        assert seq == 42

    def test_ack_consistent_with_pack_unpack_helpers(self) -> None:
        prefix = "test_smm_ack_helpers"
        with SharedMemoryManager(prefix=prefix, registry=_build_registry()) as mgr:
            mgr.create_regions([Sig.POINT])
            expected_seq = 999
            mgr.write_ack(Sig.POINT, expected_seq)
            seq = mgr.read_ack(Sig.POINT)
        assert seq == unpack_ack(pack_ack(expected_seq))

    def test_read_ack_without_region_raises(self) -> None:
        mgr = _mgr("test_smm_ack_noreg")
        with pytest.raises(KeyError):
            mgr.read_ack(Sig.POINT)


class TestAttachCycle:
    def test_attach_to_created_regions(self) -> None:
        prefix = "test_smm_attach"
        creator = SharedMemoryManager(prefix=prefix, registry=_build_registry())
        creator.create_regions([Sig.POINT])
        try:
            attacher = SharedMemoryManager(prefix=prefix, registry=_build_registry())
            attacher.attach_regions([Sig.POINT])
            payload = _pack_point(x=1.0, y=2.0)
            creator.write_signal(Sig.POINT, payload)
            assert attacher.read_signal(Sig.POINT) == payload
        finally:
            attacher.cleanup()  # type: ignore[possibly-undefined]
            creator.cleanup()

    def test_attach_missing_region_raises(self) -> None:
        mgr = _mgr("test_smm_attach_missing")
        with pytest.raises(RegionNotFoundError):
            mgr.attach_regions([Sig.POINT])

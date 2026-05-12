"""Unit tests for SharedMemoryManager."""

import struct
from enum import IntEnum

import pytest

from champi_ipc import SharedMemoryManager, StructRegistry


class SampleSignals(IntEnum):
    SIGNAL_A = 1
    SIGNAL_B = 2


_STRUCT = struct.Struct("=Q32s")


def _pack(seq_num: int, **kwargs: object) -> bytes:
    text = kwargs.get("text", b"")
    if isinstance(text, str):
        text = text.encode()
    assert isinstance(text, bytes)
    return _STRUCT.pack(seq_num, text[:32].ljust(32, b"\x00"))


def _unpack(data: bytes) -> object:
    return _STRUCT.unpack(data)


@pytest.fixture
def registry() -> StructRegistry[SampleSignals]:
    reg: StructRegistry[SampleSignals] = StructRegistry()
    reg.register(SampleSignals.SIGNAL_A, _STRUCT.size, _pack, _unpack)
    reg.register(SampleSignals.SIGNAL_B, _STRUCT.size, _pack, _unpack)
    return reg


@pytest.fixture
def manager(registry: StructRegistry[SampleSignals]):
    mgr = SharedMemoryManager("champi_ipc_test_mgr", registry)
    mgr.create_regions([SampleSignals.SIGNAL_A, SampleSignals.SIGNAL_B])
    yield mgr
    mgr.cleanup()


def test_create_regions(registry):
    mgr = SharedMemoryManager("champi_ipc_test_create", registry)
    mgr.create_regions([SampleSignals.SIGNAL_A, SampleSignals.SIGNAL_B])
    mgr.cleanup()


def test_attach_regions(registry):
    creator = SharedMemoryManager("champi_ipc_test_attach", registry)
    creator.create_regions([SampleSignals.SIGNAL_A, SampleSignals.SIGNAL_B])
    try:
        attacher = SharedMemoryManager("champi_ipc_test_attach", registry)
        attacher.attach_regions([SampleSignals.SIGNAL_A, SampleSignals.SIGNAL_B])
        attacher.cleanup()
    finally:
        creator.cleanup()


def test_write_and_read_signal(manager, registry):
    packed = registry.pack(SampleSignals.SIGNAL_A, seq_num=1, text=b"hello")
    manager.write_signal(SampleSignals.SIGNAL_A, packed)
    result = manager.read_signal(SampleSignals.SIGNAL_A)
    assert result == packed


def test_write_and_read_ack(manager):
    manager.write_ack(SampleSignals.SIGNAL_A, 42)
    assert manager.read_ack(SampleSignals.SIGNAL_A) == 42


def test_context_manager(registry):
    with SharedMemoryManager("champi_ipc_test_ctx", registry) as mgr:
        mgr.create_regions([SampleSignals.SIGNAL_A])
        packed = registry.pack(SampleSignals.SIGNAL_A, seq_num=1, text=b"ctx")
        mgr.write_signal(SampleSignals.SIGNAL_A, packed)
        assert mgr.read_signal(SampleSignals.SIGNAL_A) == packed


def test_read_unregistered_region_raises(registry):
    mgr = SharedMemoryManager("champi_ipc_test_unreg", registry)
    with pytest.raises(Exception):  # noqa: B017
        mgr.read_signal(SampleSignals.SIGNAL_A)

"""Unit tests for SignalReader."""

import struct
from enum import IntEnum

import pytest

from champi_ipc import SharedMemoryManager, StructRegistry
from champi_ipc.core.signal_reader import SignalReader


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


def _unpack_raw(data: bytes) -> tuple[int, bytes]:
    seq, payload = _STRUCT.unpack(data)
    return seq, payload


@pytest.fixture
def registry() -> StructRegistry[SampleSignals]:
    reg: StructRegistry[SampleSignals] = StructRegistry()
    reg.register(SampleSignals.SIGNAL_A, _STRUCT.size, _pack, _unpack_raw)
    reg.register(SampleSignals.SIGNAL_B, _STRUCT.size, _pack, _unpack_raw)
    return reg


@pytest.fixture
def manager(registry: StructRegistry[SampleSignals]):
    mgr = SharedMemoryManager("champi_ipc_test_reader", registry)
    mgr.create_regions([SampleSignals.SIGNAL_A, SampleSignals.SIGNAL_B])
    yield mgr
    mgr.cleanup()


@pytest.fixture
def reader(manager):
    return SignalReader(manager)


def test_reader_initialization(manager):
    reader = SignalReader(manager)
    assert reader._manager == manager
    assert reader._handlers == {}


def test_register_handler(reader):
    def handler(raw: bytes) -> None:
        pass

    reader.register_handler(SampleSignals.SIGNAL_A, handler)
    assert int(SampleSignals.SIGNAL_A) in reader._handlers


def test_poll_once_no_new_signals(reader):
    # Polling on empty regions should not raise
    reader.poll_once()


def test_poll_once_with_new_signal(reader, manager, registry):
    received: list[bytes] = []
    reader.register_handler(SampleSignals.SIGNAL_A, lambda raw: received.append(raw))

    packed = registry.pack(SampleSignals.SIGNAL_A, seq_num=1, text=b"test")
    manager.write_signal(SampleSignals.SIGNAL_A, packed)
    reader.poll_once()

    assert len(received) == 1
    assert received[0] == packed


def test_poll_multiple_signal_types(reader, manager, registry):
    received_a: list[bytes] = []
    received_b: list[bytes] = []
    reader.register_handler(SampleSignals.SIGNAL_A, lambda raw: received_a.append(raw))
    reader.register_handler(SampleSignals.SIGNAL_B, lambda raw: received_b.append(raw))

    packed_a = registry.pack(SampleSignals.SIGNAL_A, seq_num=1, text=b"hello")
    packed_b = registry.pack(SampleSignals.SIGNAL_B, seq_num=2, text=b"world")
    manager.write_signal(SampleSignals.SIGNAL_A, packed_a)
    manager.write_signal(SampleSignals.SIGNAL_B, packed_b)
    reader.poll_once()

    assert len(received_a) == 1
    assert len(received_b) == 1


def test_poll_only_new_signals(reader, manager, registry):
    received: list[bytes] = []
    reader.register_handler(SampleSignals.SIGNAL_A, lambda raw: received.append(raw))

    packed = registry.pack(SampleSignals.SIGNAL_A, seq_num=1, text=b"first")
    manager.write_signal(SampleSignals.SIGNAL_A, packed)
    reader.poll_once()
    assert len(received) == 1

    # Poll again without new data — should not fire again
    reader.poll_once()
    assert len(received) == 1

    # New write — should fire
    packed2 = registry.pack(SampleSignals.SIGNAL_A, seq_num=2, text=b"second")
    manager.write_signal(SampleSignals.SIGNAL_A, packed2)
    reader.poll_once()
    assert len(received) == 2


def test_no_handler_registered(reader, manager, registry):
    packed = registry.pack(SampleSignals.SIGNAL_A, seq_num=1, text=b"test")
    manager.write_signal(SampleSignals.SIGNAL_A, packed)
    reader.poll_once()  # Should not raise


def test_handler_exception_doesnt_crash(reader, manager, registry):
    def bad_handler(raw: bytes) -> None:
        raise ValueError("boom")

    reader.register_handler(SampleSignals.SIGNAL_A, bad_handler)
    packed = registry.pack(SampleSignals.SIGNAL_A, seq_num=1, text=b"test")
    manager.write_signal(SampleSignals.SIGNAL_A, packed)
    reader.poll_once()  # Should not propagate the exception

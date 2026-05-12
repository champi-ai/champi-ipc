"""Tests for SignalProcessor: connect, emit, queue, write, stop, signal-loss."""

from __future__ import annotations

import struct
import time
from collections.abc import Generator
from enum import IntEnum

import pytest
from blinker import Signal

from champi_ipc.base.struct_registry import StructRegistry
from champi_ipc.core.shared_memory_manager import SharedMemoryManager
from champi_ipc.core.signal_processor import SignalProcessor

# ---------------------------------------------------------------------------
# Minimal signal enum and serialisation helpers
# ---------------------------------------------------------------------------

_STRUCT = struct.Struct("=If")  # uint32 seq, float value


class Sig(IntEnum):
    ALPHA = 1
    BETA = 2


def _pack(*, seq: int = 0, value: float = 0.0) -> bytes:
    return _STRUCT.pack(seq, value)


def _unpack(data: bytes) -> object:
    return _STRUCT.unpack(data)


@pytest.fixture()
def registry() -> StructRegistry[Sig]:
    reg: StructRegistry[Sig] = StructRegistry()
    reg.register(Sig.ALPHA, _STRUCT.size, _pack, _unpack)
    reg.register(Sig.BETA, _STRUCT.size, _pack, _unpack)
    return reg


@pytest.fixture()
def manager(registry: StructRegistry[Sig]) -> Generator[SharedMemoryManager[Sig], None, None]:
    mgr: SharedMemoryManager[Sig] = SharedMemoryManager(
        prefix="test_sp", registry=registry
    )
    mgr.create_regions([Sig.ALPHA, Sig.BETA])
    yield mgr
    mgr.cleanup()


@pytest.fixture()
def processor(manager: SharedMemoryManager[Sig]) -> Generator[SignalProcessor[Sig], None, None]:
    proc: SignalProcessor[Sig] = SignalProcessor(manager)
    proc.start()
    yield proc
    proc.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_writes_bytes_to_shared_memory(
    processor: SignalProcessor[Sig],
    manager: SharedMemoryManager[Sig],
) -> None:
    """Emitting a blinker signal results in bytes appearing in shared memory."""
    sig = Signal()
    processor.connect_signal(sig, Sig.ALPHA)

    sig.send(None, seq=7, value=3.14)

    # Allow background thread to process the item.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        data = manager.read_signal(Sig.ALPHA)
        seq, value = _STRUCT.unpack(data)
        if seq == 7:
            break
        time.sleep(0.01)

    assert seq == 7
    assert abs(value - 3.14) < 1e-4


def test_data_mapper_transforms_payload(
    processor: SignalProcessor[Sig],
    manager: SharedMemoryManager[Sig],
) -> None:
    """A data_mapper can transform signal kwargs before they reach the queue."""
    sig = Signal()

    def mapper(**kwargs: object) -> dict[str, object]:
        return {"seq": 99, "value": float(kwargs.get("raw", 0.0))}  # type: ignore[arg-type]

    processor.connect_signal(sig, Sig.ALPHA, data_mapper=mapper)
    sig.send(None, raw=2.5)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        data = manager.read_signal(Sig.ALPHA)
        seq, value = _STRUCT.unpack(data)
        if seq == 99:
            break
        time.sleep(0.01)

    assert seq == 99
    assert abs(value - 2.5) < 1e-4


def test_data_mapper_returning_none_discards_emission(
    processor: SignalProcessor[Sig],
    manager: SharedMemoryManager[Sig],
) -> None:
    """A data_mapper that returns None should discard the emission silently."""
    sig = Signal()
    processor.connect_signal(sig, Sig.ALPHA, data_mapper=lambda **kw: None)
    sig.send(None, seq=1, value=1.0)

    time.sleep(0.15)
    data = manager.read_signal(Sig.ALPHA)
    seq, _ = _STRUCT.unpack(data)
    # The region was zero-initialised; nothing should have been written.
    assert seq == 0


def test_stop_joins_thread_within_two_seconds(
    manager: SharedMemoryManager[Sig],
) -> None:
    """stop() must join the background thread within 2 seconds."""
    proc: SignalProcessor[Sig] = SignalProcessor(manager)
    proc.start()
    assert proc._thread is not None
    assert proc._thread.is_alive()

    t0 = time.monotonic()
    proc.stop()
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0
    assert proc._thread is None


def test_disconnect_all_removes_handlers(
    manager: SharedMemoryManager[Sig],
) -> None:
    """disconnect_all() should remove every registered handler."""
    proc: SignalProcessor[Sig] = SignalProcessor(manager)
    sig = Signal()
    proc.connect_signal(sig, Sig.ALPHA)
    assert len(proc._connected) == 1

    proc.disconnect_all()
    assert len(proc._connected) == 0


def test_signal_loss_warning_logged_when_ack_lags(
    manager: SharedMemoryManager[Sig],
) -> None:
    """A warning should be logged when ACK lags by more than the threshold."""
    from loguru import logger

    warnings_captured: list[str] = []

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        if record["level"].name == "WARNING":
            warnings_captured.append(record["message"])

    sink_id = logger.add(_sink, level="WARNING")
    try:
        proc: SignalProcessor[Sig] = SignalProcessor(manager, loss_threshold=2)

        # Simulate ACK stuck at 0; enqueue several items manually so lag > 2.
        for i in range(1, 6):
            proc._queue.put(Sig.ALPHA, seq=i, value=float(i))

        proc.start()
        time.sleep(0.5)
        proc.stop()
    finally:
        logger.remove(sink_id)

    assert any(
        "signal loss" in t.lower() or "may be skipped" in t
        for t in warnings_captured
    ), f"Expected signal-loss warning, got: {warnings_captured}"


def test_start_idempotent(manager: SharedMemoryManager[Sig]) -> None:
    """Calling start() twice should not create a second thread."""
    proc: SignalProcessor[Sig] = SignalProcessor(manager)
    proc.start()
    thread_before = proc._thread
    proc.start()  # second call — should be a no-op
    assert proc._thread is thread_before
    proc.stop()


def test_context_manager(manager: SharedMemoryManager[Sig]) -> None:
    """Using SignalProcessor as a context manager starts and stops it."""
    with SignalProcessor(manager) as proc:
        assert proc._running is True
        assert proc._thread is not None and proc._thread.is_alive()

    assert proc._running is False

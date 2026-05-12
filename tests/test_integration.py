"""Integration test: full signal flow from blinker emit to SignalReader dispatch."""

from __future__ import annotations

import struct
import threading
import time
from enum import IntEnum

import pytest
from blinker import Signal

from champi_ipc import (
    SharedMemoryManager,
    SignalProcessor,
    SignalReader,
    StructRegistry,
)

# ---------------------------------------------------------------------------
# Signal definitions
# ---------------------------------------------------------------------------

_PAYLOAD_STRUCT = struct.Struct("=I")  # single unsigned int: value


class PingSignal(IntEnum):
    """Minimal signal enum used by the integration test."""

    PING = 1


def _pack(*, value: int = 0) -> bytes:
    return _PAYLOAD_STRUCT.pack(value)


def _unpack(data: bytes) -> dict[str, int]:
    (value,) = _PAYLOAD_STRUCT.unpack(data)
    return {"value": value}


def _build_registry() -> StructRegistry[PingSignal]:
    reg: StructRegistry[PingSignal] = StructRegistry()
    reg.register(PingSignal.PING, _PAYLOAD_STRUCT.size, _pack, _unpack)
    return reg


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

_PREFIX = "test_integ_flow"
_TIMEOUT = 0.2  # seconds — handler must fire within 200 ms


class TestFullSignalFlow:
    """End-to-end round-trip: blinker → SignalProcessor → shm → SignalReader."""

    def test_signal_dispatched_within_timeout(self) -> None:
        """Emit a blinker signal and assert the reader handler fires within 200 ms."""
        registry = _build_registry()
        ping_signal: Signal = Signal("test-integ-ping")

        # Use a sentinel value that differs from the zero-initialised region so
        # the reader does not fire prematurely on first poll.
        _SENTINEL = 42
        received: list[bytes] = []
        dispatched = threading.Event()

        def handler(raw: bytes) -> None:
            unpacked = _unpack(raw)
            if unpacked["value"] == _SENTINEL:
                received.append(raw)
                dispatched.set()

        creator = SharedMemoryManager(prefix=_PREFIX, registry=registry)
        creator.create_regions([PingSignal.PING])

        attacher = SharedMemoryManager(prefix=_PREFIX, registry=registry)
        attacher.attach_regions([PingSignal.PING])

        processor: SignalProcessor[PingSignal] = SignalProcessor(creator)
        processor.connect_signal(
            ping_signal,
            PingSignal.PING,
            data_mapper=lambda value=0, **_kw: {"value": value},
        )
        processor.start()

        reader: SignalReader[PingSignal] = SignalReader(attacher, poll_rate_hz=200.0)
        reader.register_handler(PingSignal.PING, handler)
        reader.start()

        try:
            ping_signal.send(None, value=42)
            fired = dispatched.wait(timeout=_TIMEOUT)
        finally:
            processor.stop()
            reader.stop()
            attacher.cleanup()
            creator.cleanup()

        assert fired, f"Handler not dispatched within {_TIMEOUT * 1000:.0f} ms"
        assert len(received) == 1
        unpacked = _unpack(received[0])
        assert unpacked["value"] == 42

    def test_multiple_signals_all_dispatched(self) -> None:
        """Fire several distinct signals and assert each reaches the handler."""
        registry = _build_registry()
        ping_signal: Signal = Signal("test-integ-multi")

        received: list[int] = []
        lock = threading.Lock()
        count_event = threading.Event()
        expected_count = 3
        # Only count dispatches with a value we actually sent (non-zero).
        sent_values = {10, 20, 30}

        def handler(raw: bytes) -> None:
            unpacked = _unpack(raw)
            if unpacked["value"] not in sent_values:
                return
            with lock:
                received.append(unpacked["value"])
                if len(received) >= expected_count:
                    count_event.set()

        creator = SharedMemoryManager(prefix=_PREFIX + "_multi", registry=registry)
        creator.create_regions([PingSignal.PING])

        attacher = SharedMemoryManager(prefix=_PREFIX + "_multi", registry=registry)
        attacher.attach_regions([PingSignal.PING])

        processor: SignalProcessor[PingSignal] = SignalProcessor(creator)
        processor.connect_signal(
            ping_signal,
            PingSignal.PING,
            data_mapper=lambda value=0, **_kw: {"value": value},
        )
        processor.start()

        reader: SignalReader[PingSignal] = SignalReader(attacher, poll_rate_hz=200.0)
        reader.register_handler(PingSignal.PING, handler)
        reader.start()

        try:
            for v in (10, 20, 30):
                ping_signal.send(None, value=v)
                # Small gap so the reader sees each write as a distinct change.
                time.sleep(0.02)
            fired = count_event.wait(timeout=1.0)
        finally:
            processor.stop()
            reader.stop()
            attacher.cleanup()
            creator.cleanup()

        assert fired, f"Expected {expected_count} dispatches, got {len(received)}"
        assert len(received) == expected_count

    def test_no_handler_no_error(self) -> None:
        """Reader with no registered handler should not raise on poll."""
        registry = _build_registry()
        ping_signal: Signal = Signal("test-integ-nohandler")

        creator = SharedMemoryManager(prefix=_PREFIX + "_nh", registry=registry)
        creator.create_regions([PingSignal.PING])

        attacher = SharedMemoryManager(prefix=_PREFIX + "_nh", registry=registry)
        attacher.attach_regions([PingSignal.PING])

        processor: SignalProcessor[PingSignal] = SignalProcessor(creator)
        processor.connect_signal(
            ping_signal,
            PingSignal.PING,
            data_mapper=lambda value=0, **_kw: {"value": value},
        )
        processor.start()

        reader: SignalReader[PingSignal] = SignalReader(attacher, poll_rate_hz=200.0)
        # Deliberately no handler registered.
        reader.start()

        try:
            ping_signal.send(None, value=7)
            time.sleep(0.1)
        finally:
            processor.stop()
            reader.stop()
            attacher.cleanup()
            creator.cleanup()

        # Test passes if no exception was raised.


@pytest.fixture(autouse=True)
def _cleanup_shm_regions() -> None:
    """Best-effort cleanup of any leftover test regions before each test."""
    from champi_ipc import cleanup_orphaned_regions

    cleanup_orphaned_regions(_PREFIX)
    cleanup_orphaned_regions(_PREFIX + "_multi")
    cleanup_orphaned_regions(_PREFIX + "_nh")

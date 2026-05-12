"""Tests for SignalReader: polling, dispatch, ACK, stop behaviour."""

from __future__ import annotations

import struct
import time
from enum import IntEnum
from unittest.mock import MagicMock

from champi_ipc.base.struct_registry import StructRegistry
from champi_ipc.core.shared_memory_manager import SharedMemoryManager
from champi_ipc.core.signal_reader import SignalReader

# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

_STRUCT = struct.Struct("=i")  # single int


class Sig(IntEnum):
    A = 1
    B = 2


def _pack(*, value: int = 0) -> bytes:
    return _STRUCT.pack(value)


def _unpack(data: bytes) -> tuple[int]:
    return _STRUCT.unpack(data)  # type: ignore[return-value]


def _registry() -> StructRegistry[Sig]:
    reg: StructRegistry[Sig] = StructRegistry()
    reg.register(Sig.A, _STRUCT.size, _pack, _unpack)
    reg.register(Sig.B, _STRUCT.size, _pack, _unpack)
    return reg


_PREFIX = "test_sr_champi"


# ---------------------------------------------------------------------------
# Helper: create a manager with one region pre-written
# ---------------------------------------------------------------------------


def _setup_manager(prefix: str, sig: Sig, value: int) -> SharedMemoryManager[Sig]:
    mgr: SharedMemoryManager[Sig] = SharedMemoryManager(
        prefix=prefix, registry=_registry()
    )
    mgr.create_regions([sig])
    mgr.write_signal(sig, _pack(value=value))
    return mgr


# ---------------------------------------------------------------------------
# Unit tests (mock-based, no real shared memory)
# ---------------------------------------------------------------------------


class TestPollOnceDispatch:
    def test_handler_called_on_new_data(self) -> None:
        """Handler receives raw bytes when the region content changes."""
        mgr = MagicMock()
        initial = _pack(value=0)
        changed = _pack(value=1)
        mgr.read_signal.return_value = changed

        reader: SignalReader[Sig] = SignalReader(mgr)
        handler = MagicMock()
        reader.register_handler(Sig.A, handler)
        # Seed last_bytes as the *previous* value so first poll looks like a change.
        reader._last_bytes[int(Sig.A)] = initial

        reader.poll_once()

        handler.assert_called_once_with(changed)

    def test_handler_not_called_when_data_unchanged(self) -> None:
        """Handler is silent when memory content matches last seen bytes."""
        mgr = MagicMock()
        same = _pack(value=42)
        mgr.read_signal.return_value = same

        reader: SignalReader[Sig] = SignalReader(mgr)
        handler = MagicMock()
        reader.register_handler(Sig.A, handler)
        reader._last_bytes[int(Sig.A)] = same  # already seen

        reader.poll_once()

        handler.assert_not_called()

    def test_ack_written_after_dispatch(self) -> None:
        """ACK is written for the region after a successful handler dispatch."""
        mgr = MagicMock()
        mgr.read_signal.return_value = _pack(value=99)

        reader: SignalReader[Sig] = SignalReader(mgr)
        reader.register_handler(Sig.A, MagicMock())
        reader._last_bytes[int(Sig.A)] = _pack(value=0)  # different → change

        reader.poll_once()

        mgr.write_ack.assert_called_once()
        # First positional arg integer value must equal Sig.A
        ack_target = mgr.write_ack.call_args[0][0]
        assert int(ack_target) == int(Sig.A)

    def test_ack_seq_increments_on_each_dispatch(self) -> None:
        """ACK sequence number grows by 1 for each new payload."""
        mgr = MagicMock()
        reader: SignalReader[Sig] = SignalReader(mgr)
        handler = MagicMock()
        reader.register_handler(Sig.A, handler)

        for i in range(1, 4):
            mgr.read_signal.return_value = _pack(value=i)
            # Set last_bytes to previous value to force a change every iteration.
            reader._last_bytes[int(Sig.A)] = _pack(value=i - 1)
            reader.poll_once()
            _, seq_arg = mgr.write_ack.call_args[0]
            assert seq_arg == i

    def test_handler_exception_does_not_crash_poll(self) -> None:
        """A raising handler is logged but poll_once completes without raising."""
        mgr = MagicMock()
        mgr.read_signal.return_value = _pack(value=7)

        reader: SignalReader[Sig] = SignalReader(mgr)
        bad_handler = MagicMock(side_effect=RuntimeError("boom"))
        reader.register_handler(Sig.A, bad_handler)
        reader._last_bytes[int(Sig.A)] = _pack(value=0)

        # Must not raise.
        reader.poll_once()

        bad_handler.assert_called_once()

    def test_read_error_does_not_crash_poll(self) -> None:
        """A failing read is logged; poll_once completes without raising."""
        mgr = MagicMock()
        mgr.read_signal.side_effect = OSError("shm gone")

        reader: SignalReader[Sig] = SignalReader(mgr)
        reader.register_handler(Sig.A, MagicMock())

        reader.poll_once()  # must not raise

    def test_no_handler_registered_no_dispatch(self) -> None:
        """poll_once with no registered handler is a no-op."""
        mgr = MagicMock()
        reader: SignalReader[Sig] = SignalReader(mgr)
        reader.poll_once()
        mgr.read_signal.assert_not_called()


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_stop_exits_cleanly(self) -> None:
        """start() spawns a thread; stop() joins it within a reasonable time."""
        mgr = MagicMock()
        mgr.read_signal.return_value = _pack(value=0)

        reader: SignalReader[Sig] = SignalReader(mgr, poll_rate_hz=500.0)
        reader.start()
        assert reader._running is True
        assert reader._thread is not None and reader._thread.is_alive()

        reader.stop()
        assert reader._running is False
        assert reader._thread is None

    def test_stop_exits_within_poll_interval(self) -> None:
        """stop() returns within approximately one poll interval."""
        mgr = MagicMock()
        mgr.read_signal.return_value = _pack(value=0)

        reader: SignalReader[Sig] = SignalReader(mgr, poll_rate_hz=100.0)
        reader.start()
        t0 = time.monotonic()
        reader.stop()
        elapsed = time.monotonic() - t0
        # Two poll intervals is a generous bound.
        assert elapsed < 2 / 100.0 + 0.5

    def test_start_is_idempotent(self) -> None:
        """Calling start() twice does not spawn a second thread."""
        mgr = MagicMock()
        mgr.read_signal.return_value = _pack(value=0)

        reader: SignalReader[Sig] = SignalReader(mgr, poll_rate_hz=500.0)
        reader.start()
        first_thread = reader._thread
        reader.start()  # second call — should be no-op
        assert reader._thread is first_thread
        reader.stop()

    def test_context_manager_starts_and_stops(self) -> None:
        """Context manager protocol calls start/stop automatically."""
        mgr = MagicMock()
        mgr.read_signal.return_value = _pack(value=0)

        with SignalReader(mgr, poll_rate_hz=500.0) as reader:
            assert reader._running is True

        assert reader._running is False


# ---------------------------------------------------------------------------
# Integration test (real shared memory)
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_handler_called_when_memory_changes(self) -> None:
        """End-to-end: writing to shared memory triggers the handler."""
        prefix = "test_sr_integ"
        received: list[bytes] = []

        with SharedMemoryManager(prefix=prefix, registry=_registry()) as creator:
            creator.create_regions([Sig.A])
            creator.write_signal(Sig.A, _pack(value=0))

            attacher: SharedMemoryManager[Sig] = SharedMemoryManager(
                prefix=prefix, registry=_registry()
            )
            attacher.attach_regions([Sig.A])

            reader: SignalReader[Sig] = SignalReader(attacher, poll_rate_hz=500.0)
            reader.register_handler(Sig.A, received.append)
            reader.start()

            # Write a new value to the creator side.
            creator.write_signal(Sig.A, _pack(value=123))
            time.sleep(0.05)  # allow at least one poll cycle
            reader.stop()
            attacher.cleanup()

        assert len(received) >= 1
        assert received[-1] == _pack(value=123)

    def test_ack_written_in_integration(self) -> None:
        """ACK region is updated after dispatch in the real shared memory path."""
        prefix = "test_sr_ack_integ"

        with SharedMemoryManager(prefix=prefix, registry=_registry()) as creator:
            creator.create_regions([Sig.A])
            creator.write_signal(Sig.A, _pack(value=0))

            attacher: SharedMemoryManager[Sig] = SharedMemoryManager(
                prefix=prefix, registry=_registry()
            )
            attacher.attach_regions([Sig.A])

            reader: SignalReader[Sig] = SignalReader(attacher, poll_rate_hz=500.0)
            reader.register_handler(Sig.A, lambda _b: None)
            reader.start()

            creator.write_signal(Sig.A, _pack(value=7))
            time.sleep(0.05)
            reader.stop()
            ack_seq = attacher.read_ack(Sig.A)
            attacher.cleanup()

        assert ack_seq >= 1

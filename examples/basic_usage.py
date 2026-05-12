"""Basic usage example of champi-ipc.

Demonstrates a producer-consumer pattern using champi-ipc for
inter-process communication over named POSIX shared memory.

Run with:
    python examples/basic_usage.py
"""

import struct
import time
from enum import IntEnum
from multiprocessing import Process
from typing import cast

from blinker import signal

from champi_ipc import (
    SharedMemoryManager,
    SignalProcessor,
    SignalReader,
    StructRegistry,
)

# ---------------------------------------------------------------------------
# 1. Define a signal enum
# ---------------------------------------------------------------------------


class MySignals(IntEnum):
    """Signal types used in this example."""

    MESSAGE = 1


# ---------------------------------------------------------------------------
# 2. Register the signal in a StructRegistry
# ---------------------------------------------------------------------------

MESSAGE_STRUCT = struct.Struct("=256s")


def _pack_message(text: str) -> bytes:
    """Pack a text string into 256-byte fixed-width bytes."""
    return MESSAGE_STRUCT.pack(text.encode()[:256].ljust(256, b"\x00"))


def _unpack_message(data: bytes) -> str:
    """Unpack 256-byte fixed-width bytes to a text string."""
    (raw,) = MESSAGE_STRUCT.unpack(data)
    return cast(bytes, raw).rstrip(b"\x00").decode()


registry: StructRegistry[MySignals] = StructRegistry()
registry.register(
    MySignals.MESSAGE,
    MESSAGE_STRUCT.size,
    _pack_message,
    _unpack_message,
)


# ---------------------------------------------------------------------------
# 3. Producer: create regions, start SignalProcessor, fire signals
# ---------------------------------------------------------------------------


def producer_process() -> None:
    """Producer: writes signals to shared memory."""
    print("[Producer] Starting...")

    manager: SharedMemoryManager[MySignals] = SharedMemoryManager(
        "example_app", registry
    )
    manager.create_regions([MySignals.MESSAGE])

    processor: SignalProcessor[MySignals] = SignalProcessor(manager)

    msg_signal = signal("message")
    processor.connect_signal(
        msg_signal,
        MySignals.MESSAGE,
        lambda text: {"text": text},
    )

    processor.start()

    for i in range(5):
        msg = f"Message #{i}"
        print(f"[Producer] Sending: {msg}")
        msg_signal.send(None, text=msg)
        time.sleep(0.4)

    time.sleep(0.5)

    processor.stop()
    manager.cleanup()
    print("[Producer] Done!")


# ---------------------------------------------------------------------------
# 4. Consumer: attach regions, start SignalReader, receive signals
# ---------------------------------------------------------------------------


def consumer_process() -> None:
    """Consumer: reads signals from shared memory."""
    print("[Consumer] Starting...")
    time.sleep(0.3)

    manager: SharedMemoryManager[MySignals] = SharedMemoryManager(
        "example_app", registry
    )
    manager.attach_regions([MySignals.MESSAGE])

    reader: SignalReader[MySignals] = SignalReader(manager, poll_rate_hz=60.0)

    received: list[str] = []

    def handle_message(raw: bytes) -> None:
        text = _unpack_message(raw)
        print(f"[Consumer] Received: {text}")
        received.append(text)

    reader.register_handler(MySignals.MESSAGE, handle_message)
    reader.start()

    time.sleep(5)

    reader.stop()
    manager.cleanup()
    print(f"[Consumer] Done! Received {len(received)} message(s).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("champi-ipc Basic Usage Example")
    print("=" * 50)

    producer = Process(target=producer_process)
    consumer = Process(target=consumer_process)

    producer.start()
    consumer.start()

    producer.join()
    consumer.join()

    print("=" * 50)
    print("Example complete!")
    print("=" * 50)

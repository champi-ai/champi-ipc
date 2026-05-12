"""Basic usage example of champi-ipc.

This example demonstrates a simple producer-consumer pattern using
champi-ipc for inter-process communication.
"""

from enum import IntEnum
import struct
import time
from multiprocessing import Process

from blinker import signal
from champi_ipc import (
    SharedMemoryManager,
    SignalProcessor,
    SignalReader,
    StructRegistry,
    SignalData,
)

# Define signal types
class MySignals(IntEnum):
    MESSAGE = 1


# Define struct (seq_num, signal_type, text)
MESSAGE_STRUCT = struct.Struct("=QB256s")


def pack_message(seq_num: int, text: str) -> bytes:
    """Pack message signal into binary format."""
    text_bytes = text.encode()[:256].ljust(256, b"\x00")
    return MESSAGE_STRUCT.pack(seq_num, MySignals.MESSAGE, text_bytes)


def unpack_message(data: bytes) -> SignalData:
    """Unpack message signal from binary format."""
    seq_num, signal_type, text_bytes = MESSAGE_STRUCT.unpack(data)
    return SignalData(
        signal_type=MySignals(signal_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )


# Create registry
registry = StructRegistry()
registry.register(MySignals.MESSAGE, MESSAGE_STRUCT.size, pack_message, unpack_message)


def producer_process():
    """Producer process that emits signals."""
    print("[Producer] Starting...")

    # Create memory manager
    manager = SharedMemoryManager("example_app", MySignals, registry)
    manager.create_regions()

    # Create processor
    processor = SignalProcessor(manager)

    # Connect signal
    msg_signal = signal("message")
    processor.connect_signal(
        msg_signal, MySignals.MESSAGE, lambda text: {"text": text}
    )

    processor.start()

    # Emit messages
    for i in range(5):
        msg = f"Message #{i}"
        print(f"[Producer] Sending: {msg}")
        msg_signal.send(text=msg)
        time.sleep(0.5)

    # Give time for last message to be processed
    time.sleep(1)

    # Cleanup
    processor.stop()
    manager.cleanup()
    print("[Producer] Done!")


def consumer_process():
    """Consumer process that reads signals."""
    print("[Consumer] Starting...")
    time.sleep(0.5)  # Wait for producer to create regions

    # Attach to regions
    manager = SharedMemoryManager("example_app", MySignals, registry)
    manager.attach_regions()

    # Create reader
    reader = SignalReader(manager)

    # Register handler
    def handle_message(signal_data: SignalData):
        print(f"[Consumer] Received: {signal_data.data['text']}")

    reader.register_handler(MySignals.MESSAGE, handle_message)

    # Poll for 6 seconds
    import threading

    stop_event = threading.Event()

    def poll():
        while not stop_event.is_set():
            reader.poll_once()
            time.sleep(1.0 / 60)  # 60 Hz

    poll_thread = threading.Thread(target=poll)
    poll_thread.start()

    time.sleep(6)
    stop_event.set()
    poll_thread.join()

    # Cleanup
    manager.cleanup()
    print("[Consumer] Done!")


if __name__ == "__main__":
    print("=" * 50)
    print("champi-ipc Basic Usage Example")
    print("=" * 50)

    # Start producer
    producer = Process(target=producer_process)
    producer.start()

    # Start consumer
    consumer = Process(target=consumer_process)
    consumer.start()

    # Wait for both
    producer.join()
    consumer.join()

    print("=" * 50)
    print("Example complete!")
    print("=" * 50)

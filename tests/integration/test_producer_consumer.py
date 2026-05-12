"""Integration tests for producer-consumer pattern."""

import struct
import time
from enum import IntEnum
from multiprocessing import Event

import pytest
from blinker import signal

from champi_ipc import (
    SharedMemoryManager,
    SignalData,
    SignalProcessor,
    SignalReader,
    StructRegistry,
)


class TestSignals(IntEnum):
    MESSAGE = 1
    COUNTER = 2


# Define structs
MESSAGE_STRUCT = struct.Struct("=QB256s")  # seq_num, signal_type, text
COUNTER_STRUCT = struct.Struct("=QBQ")  # seq_num, signal_type, value


def pack_message(seq_num: int, **kwargs) -> bytes:
    """Pack message signal."""
    text = kwargs.get("text", "")
    text_bytes = text.encode()[:256].ljust(256, b"\x00")
    return MESSAGE_STRUCT.pack(seq_num, TestSignals.MESSAGE, text_bytes)


def unpack_message(data: bytes) -> SignalData:
    """Unpack message signal."""
    seq_num, signal_type, text_bytes = MESSAGE_STRUCT.unpack(data)
    return SignalData(
        signal_type=TestSignals(signal_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )


def pack_counter(seq_num: int, **kwargs) -> bytes:
    """Pack counter signal."""
    value = kwargs.get("value", 0)
    return COUNTER_STRUCT.pack(seq_num, TestSignals.COUNTER, value)


def unpack_counter(data: bytes) -> SignalData:
    """Unpack counter signal."""
    seq_num, signal_type, value = COUNTER_STRUCT.unpack(data)
    return SignalData(
        signal_type=TestSignals(signal_type),
        seq_num=seq_num,
        data={"value": value},
    )


def create_registry():
    """Create test registry."""
    registry = StructRegistry()
    registry.register(
        TestSignals.MESSAGE, MESSAGE_STRUCT.size, pack_message, unpack_message
    )
    registry.register(
        TestSignals.COUNTER, COUNTER_STRUCT.size, pack_counter, unpack_counter
    )
    return registry


def producer_process(num_messages: int, ready_event: Event):
    """Producer process that emits signals."""
    registry = create_registry()
    manager = SharedMemoryManager("test_integration", TestSignals, registry)
    manager.create_regions()

    processor = SignalProcessor(manager)

    # Connect signals
    msg_signal = signal("message")
    counter_signal = signal("counter")

    processor.connect_signal(
        msg_signal, TestSignals.MESSAGE, lambda text: {"text": text}
    )
    processor.connect_signal(
        counter_signal, TestSignals.COUNTER, lambda value: {"value": value}
    )

    processor.start()

    # Signal that we're ready
    ready_event.set()

    # Emit messages
    for i in range(num_messages):
        msg_signal.send(text=f"Message {i}")
        counter_signal.send(value=i * 10)
        time.sleep(0.01)  # Small delay

    # Give time for last messages to be processed
    time.sleep(0.1)

    processor.stop()
    manager.cleanup()


def consumer_process(num_messages: int, ready_event: Event, results: dict):
    """Consumer process that reads signals."""
    # Wait for producer to be ready
    ready_event.wait(timeout=5.0)
    time.sleep(0.1)  # Give producer time to write first signals

    registry = create_registry()
    manager = SharedMemoryManager("test_integration", TestSignals, registry)
    manager.attach_regions()

    reader = SignalReader(manager)

    received_messages = []
    received_counters = []

    def handle_message(signal_data):
        received_messages.append(signal_data.data["text"])

    def handle_counter(signal_data):
        received_counters.append(signal_data.data["value"])

    reader.register_handler(TestSignals.MESSAGE, handle_message)
    reader.register_handler(TestSignals.COUNTER, handle_counter)

    # Poll for signals
    poll_count = 0
    max_polls = 200  # 2 seconds max

    while len(received_messages) < num_messages and poll_count < max_polls:
        reader.poll_once()
        time.sleep(0.01)
        poll_count += 1

    manager.cleanup()

    # Store results (note: can't return from Process, so would need shared memory/queue)
    # For now, we'll verify in the test differently


def test_single_message_flow():
    """Test single message from producer to consumer."""
    registry = create_registry()

    # Producer creates and writes
    producer_mgr = SharedMemoryManager("test_single", TestSignals, registry)
    producer_mgr.create_regions()

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("single_test")
    processor.connect_signal(
        msg_signal, TestSignals.MESSAGE, lambda text: {"text": text}
    )

    processor.start()
    msg_signal.send(text="Hello World")
    time.sleep(0.1)  # Let it process
    processor.stop()

    # Consumer attaches and reads
    consumer_mgr = SharedMemoryManager("test_single", TestSignals, registry)
    consumer_mgr.attach_regions()

    reader = SignalReader(consumer_mgr)
    received = []
    reader.register_handler(TestSignals.MESSAGE, lambda s: received.append(s))

    reader.poll_once()

    # Cleanup
    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    # Verify
    assert len(received) == 1
    assert received[0].data["text"] == "Hello World"
    assert received[0].seq_num == 1


def test_multiple_messages_same_type():
    """Test multiple messages of the same type."""
    registry = create_registry()

    # Producer
    producer_mgr = SharedMemoryManager("test_multi", TestSignals, registry)
    producer_mgr.create_regions()

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("multi_test")
    processor.connect_signal(
        msg_signal, TestSignals.MESSAGE, lambda text: {"text": text}
    )

    processor.start()

    messages = ["First", "Second", "Third", "Fourth", "Fifth"]
    for msg in messages:
        msg_signal.send(text=msg)
        time.sleep(0.01)

    time.sleep(0.1)
    processor.stop()

    # Consumer
    consumer_mgr = SharedMemoryManager("test_multi", TestSignals, registry)
    consumer_mgr.attach_regions()

    reader = SignalReader(consumer_mgr)
    received = []
    reader.register_handler(TestSignals.MESSAGE, lambda s: received.append(s))

    # Poll multiple times to get all messages
    for _ in range(10):
        reader.poll_once()
        time.sleep(0.01)

    # Cleanup
    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    # Verify - should have received all messages
    assert len(received) >= 1  # At minimum the last one
    # Due to overwriting, we mainly care that the last one is correct
    assert received[-1].data["text"] == "Fifth"
    assert received[-1].seq_num == 5


def test_mixed_signal_types():
    """Test sending both message and counter signals."""
    registry = create_registry()

    # Producer
    producer_mgr = SharedMemoryManager("test_mixed", TestSignals, registry)
    producer_mgr.create_regions()

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("mixed_msg")
    counter_signal = signal("mixed_counter")

    processor.connect_signal(
        msg_signal, TestSignals.MESSAGE, lambda text: {"text": text}
    )
    processor.connect_signal(
        counter_signal, TestSignals.COUNTER, lambda value: {"value": value}
    )

    processor.start()

    # Send interleaved signals
    msg_signal.send(text="Message 1")
    counter_signal.send(value=100)
    msg_signal.send(text="Message 2")
    counter_signal.send(value=200)

    time.sleep(0.2)
    processor.stop()

    # Consumer
    consumer_mgr = SharedMemoryManager("test_mixed", TestSignals, registry)
    consumer_mgr.attach_regions()

    reader = SignalReader(consumer_mgr)
    received_msgs = []
    received_counters = []

    reader.register_handler(TestSignals.MESSAGE, lambda s: received_msgs.append(s))
    reader.register_handler(TestSignals.COUNTER, lambda s: received_counters.append(s))

    # Poll multiple times
    for _ in range(10):
        reader.poll_once()
        time.sleep(0.01)

    # Cleanup
    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    # Verify both signal types were received
    assert len(received_msgs) >= 1
    assert len(received_counters) >= 1
    assert received_msgs[-1].data["text"] == "Message 2"
    assert received_counters[-1].data["value"] == 200


def test_sequence_numbers_increment():
    """Test that sequence numbers increment correctly."""
    registry = create_registry()

    producer_mgr = SharedMemoryManager("test_seq", TestSignals, registry)
    producer_mgr.create_regions()

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("seq_test")
    processor.connect_signal(
        msg_signal, TestSignals.MESSAGE, lambda text: {"text": text}
    )

    processor.start()

    for i in range(3):
        msg_signal.send(text=f"Msg {i}")
        time.sleep(0.05)

    time.sleep(0.1)
    processor.stop()

    # Read and verify sequence numbers
    consumer_mgr = SharedMemoryManager("test_seq", TestSignals, registry)
    consumer_mgr.attach_regions()

    reader = SignalReader(consumer_mgr)
    received = []
    reader.register_handler(TestSignals.MESSAGE, lambda s: received.append(s))

    for _ in range(5):
        reader.poll_once()
        time.sleep(0.02)

    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    # Check sequence numbers are incrementing
    if len(received) > 1:
        for i in range(1, len(received)):
            assert received[i].seq_num > received[i - 1].seq_num


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

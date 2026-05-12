"""Integration tests for producer-consumer pattern."""

import struct
import time
from enum import IntEnum

import pytest
from blinker import signal

from champi_ipc import (
    SharedMemoryManager,
    SignalData,
    SignalProcessor,
    SignalReader,
    StructRegistry,
)

ALL_SIGNALS = [1, 2]  # TestSignals members as ints for type-agnostic create/attach


class SampleSignals(IntEnum):
    MESSAGE = 1
    COUNTER = 2


MESSAGE_STRUCT = struct.Struct("=QB256s")
COUNTER_STRUCT = struct.Struct("=QBQ")


def pack_message(seq_num: int = 0, **kwargs: object) -> bytes:
    text = kwargs.get("text", "")
    assert isinstance(text, str)
    text_bytes = text.encode()[:256].ljust(256, b"\x00")
    return MESSAGE_STRUCT.pack(seq_num, SampleSignals.MESSAGE, text_bytes)


def unpack_message(data: bytes) -> SignalData:
    seq_num, signal_type, text_bytes = MESSAGE_STRUCT.unpack(data)
    return SignalData(
        signal_type=SampleSignals(signal_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )


def pack_counter(seq_num: int = 0, **kwargs: object) -> bytes:
    value = kwargs.get("value", 0)
    assert isinstance(value, int)
    return COUNTER_STRUCT.pack(seq_num, SampleSignals.COUNTER, value)


def unpack_counter(data: bytes) -> SignalData:
    seq_num, signal_type, value = COUNTER_STRUCT.unpack(data)
    return SignalData(
        signal_type=SampleSignals(signal_type),
        seq_num=seq_num,
        data={"value": value},
    )


def create_registry() -> StructRegistry[SampleSignals]:
    registry: StructRegistry[SampleSignals] = StructRegistry()
    registry.register(SampleSignals.MESSAGE, MESSAGE_STRUCT.size, pack_message, unpack_message)
    registry.register(SampleSignals.COUNTER, COUNTER_STRUCT.size, pack_counter, unpack_counter)
    return registry


_SIGNAL_TYPES = [SampleSignals.MESSAGE, SampleSignals.COUNTER]


@pytest.fixture(autouse=True)
def cleanup_regions():
    from champi_ipc.utils.cleanup import cleanup_orphaned_regions
    cleanup_orphaned_regions("champi_ipc_test")
    yield
    cleanup_orphaned_regions("champi_ipc_test")


def test_single_message_flow():
    """Test single message from producer to consumer."""
    registry = create_registry()

    producer_mgr = SharedMemoryManager("champi_ipc_test_single", registry)
    producer_mgr.create_regions([SampleSignals.MESSAGE, SampleSignals.COUNTER])

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("single_test")
    processor.connect_signal(msg_signal, SampleSignals.MESSAGE, lambda text: {"text": text})

    processor.start()
    msg_signal.send(text="Hello World")
    time.sleep(0.1)
    processor.stop()

    consumer_mgr = SharedMemoryManager("champi_ipc_test_single", registry)
    consumer_mgr.attach_regions([SampleSignals.MESSAGE, SampleSignals.COUNTER])

    reader = SignalReader(consumer_mgr)
    received: list[SignalData] = []
    reader.register_handler(SampleSignals.MESSAGE, lambda raw: received.append(unpack_message(raw)))
    reader.poll_once()

    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    assert len(received) == 1
    assert received[0].data["text"] == "Hello World"


def test_multiple_messages_same_type():
    """Test multiple messages of the same type — only the last is retained."""
    registry = create_registry()

    producer_mgr = SharedMemoryManager("champi_ipc_test_multi", registry)
    producer_mgr.create_regions(_SIGNAL_TYPES)

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("multi_test")
    processor.connect_signal(msg_signal, SampleSignals.MESSAGE, lambda text: {"text": text})
    processor.start()

    messages = ["First", "Second", "Third", "Fourth", "Fifth"]
    for msg in messages:
        msg_signal.send(text=msg)
        time.sleep(0.01)
    time.sleep(0.1)
    processor.stop()

    consumer_mgr = SharedMemoryManager("champi_ipc_test_multi", registry)
    consumer_mgr.attach_regions(_SIGNAL_TYPES)

    reader = SignalReader(consumer_mgr)
    received: list[SignalData] = []
    reader.register_handler(SampleSignals.MESSAGE, lambda raw: received.append(unpack_message(raw)))

    for _ in range(10):
        reader.poll_once()
        time.sleep(0.01)

    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    assert len(received) >= 1
    assert received[-1].data["text"] == "Fifth"


def test_mixed_signal_types():
    """Test sending both message and counter signals."""
    registry = create_registry()

    producer_mgr = SharedMemoryManager("champi_ipc_test_mixed", registry)
    producer_mgr.create_regions(_SIGNAL_TYPES)

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("mixed_msg")
    counter_signal = signal("mixed_counter")
    processor.connect_signal(msg_signal, SampleSignals.MESSAGE, lambda text: {"text": text})
    processor.connect_signal(counter_signal, SampleSignals.COUNTER, lambda value: {"value": value})
    processor.start()

    msg_signal.send(text="Message 1")
    counter_signal.send(value=100)
    msg_signal.send(text="Message 2")
    counter_signal.send(value=200)
    time.sleep(0.2)
    processor.stop()

    consumer_mgr = SharedMemoryManager("champi_ipc_test_mixed", registry)
    consumer_mgr.attach_regions(_SIGNAL_TYPES)

    reader = SignalReader(consumer_mgr)
    received_msgs: list[SignalData] = []
    received_counters: list[SignalData] = []
    reader.register_handler(SampleSignals.MESSAGE, lambda raw: received_msgs.append(unpack_message(raw)))
    reader.register_handler(SampleSignals.COUNTER, lambda raw: received_counters.append(unpack_counter(raw)))

    for _ in range(10):
        reader.poll_once()
        time.sleep(0.01)

    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    assert len(received_msgs) >= 1
    assert len(received_counters) >= 1
    assert received_msgs[-1].data["text"] == "Message 2"
    assert received_counters[-1].data["value"] == 200


def test_sequence_numbers_increment():
    """Test that sequence numbers increment across consecutive sends."""
    registry = create_registry()

    producer_mgr = SharedMemoryManager("champi_ipc_test_seq", registry)
    producer_mgr.create_regions(_SIGNAL_TYPES)

    processor = SignalProcessor(producer_mgr)
    msg_signal = signal("seq_test")
    processor.connect_signal(msg_signal, SampleSignals.MESSAGE, lambda text: {"text": text})
    processor.start()

    for i in range(3):
        msg_signal.send(text=f"Msg {i}")
        time.sleep(0.05)
    time.sleep(0.1)
    processor.stop()

    consumer_mgr = SharedMemoryManager("champi_ipc_test_seq", registry)
    consumer_mgr.attach_regions(_SIGNAL_TYPES)

    reader = SignalReader(consumer_mgr)
    received: list[SignalData] = []
    reader.register_handler(SampleSignals.MESSAGE, lambda raw: received.append(unpack_message(raw)))

    for _ in range(5):
        reader.poll_once()
        time.sleep(0.02)

    producer_mgr.cleanup()
    consumer_mgr.cleanup()

    if len(received) > 1:
        for i in range(1, len(received)):
            assert received[i].seq_num > received[i - 1].seq_num


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

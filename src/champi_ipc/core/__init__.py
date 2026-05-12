"""Core IPC classes for champi-ipc."""

from champi_ipc.core.shared_memory import SharedMemoryManager
from champi_ipc.core.signal_processor import SignalProcessor
from champi_ipc.core.signal_queue import SignalQueue, SignalQueueItem
from champi_ipc.core.signal_reader import SignalReader

__all__ = [
    "SharedMemoryManager",
    "SignalProcessor",
    "SignalReader",
    "SignalQueue",
    "SignalQueueItem",
]

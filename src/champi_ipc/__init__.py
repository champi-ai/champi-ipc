"""champi-ipc: Shared Memory IPC Infrastructure.

A generic, reusable library for inter-process communication using
shared memory and blinker signals.
"""

from champi_ipc.base.exceptions import (
    IPCError,
    RegionExistsError,
    RegionNotFoundError,
    SignalTypeNotRegisteredError,
)
from champi_ipc.base.protocols import SignalTypeProtocol
from champi_ipc.base.struct_registry import StructRegistry
from champi_ipc.core.shared_memory_manager import SharedMemoryManager
from champi_ipc.core.signal_processor import SignalProcessor
from champi_ipc.core.signal_queue import SignalQueue, SignalQueueItem
from champi_ipc.core.signal_reader import SignalReader
from champi_ipc.utils.ack import get_ack_size, pack_ack, unpack_ack

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Base
    "SignalTypeProtocol",
    "StructRegistry",
    "SharedMemoryManager",
    "SignalProcessor",
    "SignalQueue",
    "SignalQueueItem",
    "SignalReader",
    # Exceptions
    "IPCError",
    "RegionExistsError",
    "RegionNotFoundError",
    "SignalTypeNotRegisteredError",
    # Utilities
    "get_ack_size",
    "pack_ack",
    "unpack_ack",
]

"""champi-ipc: Shared Memory IPC Infrastructure

A generic, reusable library for inter-process communication using
shared memory and blinker signals.

Example:
    >>> from champi_ipc import (
    ...     SharedMemoryManager,
    ...     SignalProcessor,
    ...     SignalReader,
    ...     StructRegistry,
    ...     cleanup_orphaned_regions
    ... )
    >>>
    >>> # Define your signal types
    >>> from enum import IntEnum
    >>> class MySignals(IntEnum):
    ...     SIGNAL_A = 1
    ...     SIGNAL_B = 2
    >>>
    >>> # Create registry
    >>> registry = StructRegistry()
    >>> registry.register(MySignals.SIGNAL_A, 32, pack_a, unpack_a)
    >>>
    >>> # Create manager
    >>> manager = SharedMemoryManager("my_app", MySignals, registry)
    >>> manager.create_regions()
"""

__version__ = "0.1.0"

# Core classes
from champi_ipc.base.exceptions import (
    IPCError,
    RegionExistsError,
    RegionNotFoundError,
    SignalTypeNotRegisteredError,
)

# Base protocols
from champi_ipc.base.protocols import SignalData, SignalTypeProtocol, StructRegistry
from champi_ipc.core.shared_memory import SharedMemoryManager
from champi_ipc.core.signal_processor import SignalProcessor
from champi_ipc.core.signal_queue import SignalQueue, SignalQueueItem
from champi_ipc.core.signal_reader import SignalReader
from champi_ipc.utils.ack import get_ack_size, pack_ack, unpack_ack

# Utilities
from champi_ipc.utils.cleanup import (
    cleanup_orphaned_regions,
    get_region_info,
    list_regions,
)

__all__ = [
    # Core
    "SharedMemoryManager",
    "SignalProcessor",
    "SignalReader",
    "SignalQueue",
    "SignalQueueItem",
    # Base
    "SignalTypeProtocol",
    "StructRegistry",
    "SignalData",
    # Exceptions
    "IPCError",
    "RegionNotFoundError",
    "RegionExistsError",
    "SignalTypeNotRegisteredError",
    # Utilities
    "cleanup_orphaned_regions",
    "list_regions",
    "get_region_info",
    "pack_ack",
    "unpack_ack",
    "get_ack_size",
]

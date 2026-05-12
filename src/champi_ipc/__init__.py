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
from champi_ipc.utils.ack import get_ack_size, pack_ack, unpack_ack
from champi_ipc.utils.cleanup import (
    CleanupResult,
    cleanup_orphaned_regions,
    get_region_info,
    list_regions,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Base
    "SignalTypeProtocol",
    "StructRegistry",
    # Exceptions
    "IPCError",
    "RegionExistsError",
    "RegionNotFoundError",
    "SignalTypeNotRegisteredError",
    # Utilities — ack
    "get_ack_size",
    "pack_ack",
    "unpack_ack",
    # Utilities — cleanup
    "CleanupResult",
    "cleanup_orphaned_regions",
    "get_region_info",
    "list_regions",
]

"""Base protocols and exceptions for champi-ipc."""

from champi_ipc.base.exceptions import (
    IPCError,
    RegionExistsError,
    RegionNotFoundError,
    SignalTypeNotRegisteredError,
)
from champi_ipc.base.protocols import SignalTypeProtocol
from champi_ipc.base.struct_registry import StructRegistry

__all__ = [
    "IPCError",
    "RegionExistsError",
    "RegionNotFoundError",
    "SignalTypeNotRegisteredError",
    "SignalTypeProtocol",
    "StructRegistry",
]

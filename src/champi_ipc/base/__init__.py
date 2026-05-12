"""Base protocols and exceptions for champi-ipc."""

from champi_ipc.base.exceptions import (
    IPCError,
    RegionExistsError,
    RegionNotFoundError,
    SignalTypeNotRegisteredError,
)
from champi_ipc.base.protocols import SignalData, SignalTypeProtocol, StructRegistry

__all__ = [
    "SignalTypeProtocol",
    "StructRegistry",
    "SignalData",
    "IPCError",
    "RegionNotFoundError",
    "RegionExistsError",
    "SignalTypeNotRegisteredError",
]

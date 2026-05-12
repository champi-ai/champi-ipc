"""Custom exceptions for champi-ipc."""


class IPCError(Exception):
    """Base exception for all champi-ipc errors."""


class RegionNotFoundError(IPCError):
    """Raised when a shared memory region does not exist."""


class RegionExistsError(IPCError):
    """Raised when a shared memory region already exists."""


class SignalTypeNotRegisteredError(IPCError):
    """Raised when a signal type has no entry in the StructRegistry."""

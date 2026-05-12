"""Custom exceptions for champi-ipc."""


class IPCError(Exception):
    """Base exception for IPC errors."""

    pass


class RegionNotFoundError(IPCError):
    """Shared memory region not found."""

    pass


class RegionExistsError(IPCError):
    """Shared memory region already exists."""

    pass


class SignalTypeNotRegisteredError(IPCError):
    """Signal type not registered in struct registry."""

    pass

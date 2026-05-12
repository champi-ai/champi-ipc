"""Custom exceptions for champi-ipc."""


class IPCError(Exception):
    """Base exception for all champi-ipc errors."""


class RegionNotFoundError(IPCError):
    """Raised when a shared memory region does not exist.

    Args:
        name: The region name that was not found.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Shared memory region not found: {name!r}")


class RegionExistsError(IPCError):
    """Raised when a shared memory region already exists."""


class SignalTypeNotRegisteredError(IPCError):
    """Raised when a signal type has no entry in the StructRegistry."""

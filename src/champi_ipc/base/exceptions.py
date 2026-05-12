"""Custom exceptions for champi-ipc."""


class IPCError(Exception):
    """Base exception for IPC errors."""

    pass


class RegionNotFoundError(IPCError):
    """Raised when a shared memory region does not exist.

    Args:
        name: The region name that was not found.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Shared memory region not found: {name!r}")


class RegionExistsError(IPCError):
    """Shared memory region already exists."""

    pass


class SignalTypeNotRegisteredError(IPCError):
    """Signal type not registered in struct registry."""

    pass

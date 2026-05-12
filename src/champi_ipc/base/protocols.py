"""Protocols and registries for champi-ipc signal types."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SignalTypeProtocol(Protocol):
    """Protocol for signal type enums.

    Any IntEnum satisfies this protocol naturally, as IntEnum members
    expose both ``name`` and ``value`` and support ``__int__``.
    """

    name: str
    value: int

    def __int__(self) -> int:
        """Return the integer value of the signal type."""
        ...

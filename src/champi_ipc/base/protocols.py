"""Protocol definitions and registries for champi-ipc.

This module provides the core abstractions that make the library generic
and reusable across different signal type enums.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SignalTypeProtocol(Protocol):
    """Protocol for signal type enums.

    Any IntEnum can be used as a signal type as long as it follows
    this protocol (which IntEnum naturally does).

    Example:
        >>> from enum import IntEnum
        >>> class MySignals(IntEnum):
        ...     SIGNAL_A = 1
        >>>
        >>> from champi_ipc.base.protocols import SignalTypeProtocol
        >>> assert isinstance(MySignals.SIGNAL_A, SignalTypeProtocol)
    """

    name: str
    value: int

    def __int__(self) -> int: ...


@dataclass
class SignalData:
    """Unpacked signal data returned by readers.

    Attributes:
        signal_type: Type of signal
        seq_num: Sequence number
        data: Dictionary containing signal-specific data
    """

    signal_type: SignalTypeProtocol  # type: ignore[assignment]  # runtime IntEnum, not statically checkable
    seq_num: int
    data: dict[str, Any]


class StructRegistry:
    """Registry for mapping signal types to struct definitions.

    Allows services to register custom signal types with their
    pack/unpack functions and struct sizes.

    This is the key to making the library generic - each service
    registers its own signal types and struct operations.

    Example:
        >>> from enum import IntEnum
        >>> import struct
        >>>
        >>> class MySignals(IntEnum):
        ...     MESSAGE = 1
        >>>
        >>> # Define pack/unpack functions
        >>> MSG_STRUCT = struct.Struct("=QB256s")
        >>>
        >>> def pack_msg(seq_num: int, text: str) -> bytes:
        ...     text_bytes = text.encode()[:256].ljust(256, b'\\x00')
        ...     return MSG_STRUCT.pack(seq_num, MySignals.MESSAGE, text_bytes)
        >>>
        >>> def unpack_msg(data: bytes) -> SignalData:
        ...     seq, sig_type, text_bytes = MSG_STRUCT.unpack(data)
        ...     return SignalData(
        ...         signal_type=MySignals(sig_type),
        ...         seq_num=seq,
        ...         data={'text': text_bytes.rstrip(b'\\x00').decode()}
        ...     )
        >>>
        >>> # Create registry and register signal type
        >>> registry = StructRegistry()
        >>> registry.register(MySignals.MESSAGE, MSG_STRUCT.size, pack_msg, unpack_msg)
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._struct_sizes: dict[int, int] = {}
        self._pack_funcs: dict[int, Callable[..., bytes]] = {}
        self._unpack_funcs: dict[int, Callable[[bytes], SignalData]] = {}

    def register(
        self,
        signal_type: SignalTypeProtocol,
        struct_size: int,
        pack_func: Callable[..., bytes],
        unpack_func: Callable[[bytes], SignalData],
    ) -> None:
        """Register a signal type with its struct operations.

        Args:
            signal_type: Signal type enum value
            struct_size: Size of packed struct in bytes
            pack_func: Function(seq_num: int, **kwargs) -> bytes
            unpack_func: Function(bytes) -> SignalData

        Example:
            >>> registry.register(
            ...     MySignals.MESSAGE,
            ...     256,
            ...     pack_message,
            ...     unpack_message
            ... )
        """
        type_id = int(signal_type)
        self._struct_sizes[type_id] = struct_size
        self._pack_funcs[type_id] = pack_func
        self._unpack_funcs[type_id] = unpack_func

    def get_struct_size(self, signal_type: SignalTypeProtocol) -> int:
        """Get struct size for signal type.

        Args:
            signal_type: Signal type to query

        Returns:
            Size in bytes

        Raises:
            KeyError: If signal type not registered
        """
        return self._struct_sizes[int(signal_type)]

    def pack(
        self, signal_type: SignalTypeProtocol, seq_num: int, **kwargs: Any
    ) -> bytes:
        """Pack signal using registered function.

        Args:
            signal_type: Type of signal
            seq_num: Sequence number
            **kwargs: Signal-specific data

        Returns:
            Packed binary data

        Raises:
            KeyError: If signal type not registered
        """
        return self._pack_funcs[int(signal_type)](seq_num, **kwargs)

    def unpack(self, signal_type: SignalTypeProtocol, data: bytes) -> SignalData:
        """Unpack signal using registered function.

        Args:
            signal_type: Type of signal
            data: Packed binary data

        Returns:
            SignalData with unpacked values

        Raises:
            KeyError: If signal type not registered
        """
        return self._unpack_funcs[int(signal_type)](data)

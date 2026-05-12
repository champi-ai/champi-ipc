"""StructRegistry — maps signal enum values to pack/unpack callables."""

from collections.abc import Callable
from typing import SupportsInt

from champi_ipc.base.exceptions import SignalTypeNotRegisteredError


class StructRegistry[S: SupportsInt]:
    """Maps signal type enum values to their binary serialisation triple.

    Each entry associates a signal type (identified by its integer value)
    with:
    - the fixed byte size of the packed struct,
    - a callable that serialises data into ``bytes``,
    - a callable that deserialises ``bytes`` back into an object.

    Type parameter ``S`` must support conversion to ``int`` (any
    ``IntEnum`` subclass satisfies this bound).
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._registry: dict[
            int, tuple[int, Callable[..., bytes], Callable[[bytes], object]]
        ] = {}

    def register(
        self,
        signal_type: S,
        size: int,
        pack_fn: Callable[..., bytes],
        unpack_fn: Callable[[bytes], object],
    ) -> None:
        """Register a signal type with its serialisation triple.

        Args:
            signal_type: The signal enum member to register.
            size: Fixed byte length of a packed struct for this signal.
            pack_fn: Callable that accepts arbitrary keyword arguments and
                returns packed ``bytes``.
            unpack_fn: Callable that accepts ``bytes`` and returns an
                unpacked object.

        Raises:
            ValueError: If *signal_type* is already registered.
        """
        key = int(signal_type)
        if key in self._registry:
            raise ValueError(
                f"Signal type {signal_type!r} (value={key}) is already registered."
            )
        self._registry[key] = (size, pack_fn, unpack_fn)

    def get_size(self, signal_type: S) -> int:
        """Return the packed byte size for *signal_type*.

        Args:
            signal_type: The signal enum member to look up.

        Returns:
            Fixed byte length of the packed struct.

        Raises:
            SignalTypeNotRegisteredError: If *signal_type* is not registered.
        """
        return self._lookup(signal_type)[0]

    def pack(self, signal_type: S, **kwargs: object) -> bytes:
        """Serialise *signal_type* data into bytes.

        Args:
            signal_type: The signal enum member identifying the struct format.
            **kwargs: Signal-specific data fields forwarded to the pack callable.

        Returns:
            Packed bytes.

        Raises:
            SignalTypeNotRegisteredError: If *signal_type* is not registered.
        """
        return self._lookup(signal_type)[1](**kwargs)

    def unpack(self, signal_type: S, data: bytes) -> object:
        """Deserialise *data* into a signal-specific object.

        Args:
            signal_type: The signal enum member identifying the struct format.
            data: Raw bytes to deserialise.

        Returns:
            Unpacked object produced by the registered unpack callable.

        Raises:
            SignalTypeNotRegisteredError: If *signal_type* is not registered.
        """
        return self._lookup(signal_type)[2](data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lookup(
        self, signal_type: S
    ) -> tuple[int, Callable[..., bytes], Callable[[bytes], object]]:
        key = int(signal_type)
        try:
            return self._registry[key]
        except KeyError:
            raise SignalTypeNotRegisteredError(
                f"Signal type {signal_type!r} (value={key}) is not registered."
            ) from None

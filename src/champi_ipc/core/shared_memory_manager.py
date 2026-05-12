"""Generic SharedMemoryManager for POSIX shared memory IPC regions."""

from __future__ import annotations

from multiprocessing import shared_memory
from types import TracebackType
from typing import SupportsInt, cast

from loguru import logger

from champi_ipc.base.exceptions import RegionExistsError, RegionNotFoundError
from champi_ipc.base.struct_registry import StructRegistry
from champi_ipc.utils.ack import get_ack_size, pack_ack, unpack_ack

_ACK_SIZE = get_ack_size()


class SharedMemoryManager[S: SupportsInt]:
    """Creates and manages named POSIX shared memory regions.

    Each logical channel consists of two regions:
    - A *signal* region that holds an arbitrary packed struct.
    - An *ACK* region that holds a single ``uint64`` sequence counter.

    The creator process calls :meth:`create_regions` and is responsible for
    unlinking regions on :meth:`cleanup`.  Attaching processes call
    :meth:`attach_regions` and only close (never unlink) on cleanup.

    Type parameter ``S`` must support conversion to ``int`` (any
    ``IntEnum`` subclass satisfies this bound).

    Args:
        prefix: Name prefix used for every shared memory region.
        registry: :class:`~champi_ipc.base.struct_registry.StructRegistry`
            that maps signal types to their binary serialisation callables.
    """

    def __init__(self, prefix: str, registry: StructRegistry[S]) -> None:
        self._prefix = prefix
        self._registry = registry
        self._signal_regions: dict[int, shared_memory.SharedMemory] = {}
        self._ack_regions: dict[int, shared_memory.SharedMemory] = {}
        self._is_creator = False
        self._seq_num = 0

    # ------------------------------------------------------------------
    # Region lifecycle
    # ------------------------------------------------------------------

    def create_regions(self, signal_types: list[S]) -> None:
        """Create shared memory regions for each signal type.

        Intended to be called by the producer/creator process.  If a region
        already exists (``FileExistsError``) it is attached rather than
        created, and a warning is logged.

        Args:
            signal_types: Signal enum members for which regions should be
                created.  Each member must be registered in *registry*.

        Raises:
            RegionExistsError: If a region already exists and re-attaching
                fails unexpectedly.
        """
        self._is_creator = True
        for sig_type in signal_types:
            key = int(sig_type)
            size = self._registry.get_size(sig_type)
            self._signal_regions[key] = self._create_or_attach(
                self._signal_name(key), size
            )
            self._ack_regions[key] = self._create_or_attach(
                self._ack_name(key), _ACK_SIZE
            )

    def attach_regions(self, signal_types: list[S]) -> None:
        """Attach to existing shared memory regions created by another process.

        Intended to be called by the consumer/attaching process.

        Args:
            signal_types: Signal enum members whose regions should be attached.

        Raises:
            RegionNotFoundError: If a required region does not exist yet.
        """
        self._is_creator = False
        for sig_type in signal_types:
            key = int(sig_type)
            self._signal_regions[key] = self._attach(self._signal_name(key))
            self._ack_regions[key] = self._attach(self._ack_name(key))

    # ------------------------------------------------------------------
    # Signal read/write
    # ------------------------------------------------------------------

    def write_signal(self, signal_type: S, data: bytes) -> None:
        """Write raw bytes into the signal region for *signal_type*.

        Args:
            signal_type: Identifies which region to write to.
            data: Packed bytes to store.  Length must not exceed the region
                size registered for *signal_type*.

        Raises:
            KeyError: If *signal_type* has no attached region.
            ValueError: If *data* is longer than the region size.
        """
        key = int(signal_type)
        region = self._require_signal_region(key)
        size = self._registry.get_size(signal_type)
        if len(data) > size:
            msg = f"Data length {len(data)} exceeds region size {size}"
            raise ValueError(msg)
        self._buf(region)[: len(data)] = data
        if len(data) < size:
            self._buf(region)[len(data) : size] = bytes(size - len(data))
        logger.debug(f"write_signal: {self._signal_name(key)} ({len(data)} bytes)")

    def read_signal(self, signal_type: S) -> bytes:
        """Read raw bytes from the signal region for *signal_type*.

        Args:
            signal_type: Identifies which region to read from.

        Returns:
            A ``bytes`` snapshot of the region contents.

        Raises:
            KeyError: If *signal_type* has no attached region.
        """
        key = int(signal_type)
        region = self._require_signal_region(key)
        size = self._registry.get_size(signal_type)
        data = bytes(self._buf(region)[:size])
        logger.debug(f"read_signal: {self._signal_name(key)} ({size} bytes)")
        return data

    # ------------------------------------------------------------------
    # ACK read/write
    # ------------------------------------------------------------------

    def write_ack(self, signal_type: S, seq: int) -> None:
        """Write an ACK sequence number for *signal_type*.

        Args:
            signal_type: Identifies which ACK region to write to.
            seq: Sequence number to acknowledge.

        Raises:
            KeyError: If *signal_type* has no attached ACK region.
        """
        key = int(signal_type)
        region = self._require_ack_region(key)
        self._buf(region)[:_ACK_SIZE] = pack_ack(seq)
        logger.debug(f"write_ack: {self._ack_name(key)} seq={seq}")

    def read_ack(self, signal_type: S) -> int:
        """Read the ACK sequence number for *signal_type*.

        Args:
            signal_type: Identifies which ACK region to read from.

        Returns:
            The sequence number stored in the ACK region.

        Raises:
            KeyError: If *signal_type* has no attached ACK region.
            struct.error: If the ACK region contains malformed data.
        """
        key = int(signal_type)
        region = self._require_ack_region(key)
        data = bytes(self._buf(region)[:_ACK_SIZE])
        seq = unpack_ack(data)
        logger.debug(f"read_ack: {self._ack_name(key)} seq={seq}")
        return seq

    # ------------------------------------------------------------------
    # Cleanup / context manager
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Close and, if this process is the creator, unlink all regions.

        Safe to call multiple times; regions already closed are skipped.
        """
        for regions in (self._signal_regions, self._ack_regions):
            for _name_key, region in list(regions.items()):
                shm_name = region.name
                try:
                    region.close()
                except Exception:  # noqa: BLE001
                    logger.warning(f"Error closing region {shm_name}")
                if self._is_creator:
                    try:
                        region.unlink()
                        logger.debug(f"Unlinked region: {shm_name}")
                    except FileNotFoundError:
                        pass
            regions.clear()

    def __enter__(self) -> SharedMemoryManager[S]:
        """Return self for use as a context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Call :meth:`cleanup` on exit regardless of exceptions."""
        self.cleanup()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _buf(shm: shared_memory.SharedMemory) -> memoryview:
        """Return the buffer of *shm* as a non-optional memoryview."""
        return cast(memoryview, shm.buf)

    def _signal_name(self, key: int) -> str:
        return f"{self._prefix}_sig_{key}"

    def _ack_name(self, key: int) -> str:
        return f"{self._prefix}_ack_{key}"

    def _create_or_attach(self, name: str, size: int) -> shared_memory.SharedMemory:
        try:
            shm = shared_memory.SharedMemory(name=name, create=True, size=size)
            self._buf(shm)[:size] = bytes(size)
            logger.debug(f"Created shared memory region: {name} ({size} bytes)")
            return shm
        except FileExistsError:
            logger.warning(f"Region {name!r} already exists — attaching instead")
            try:
                return shared_memory.SharedMemory(name=name, create=False)
            except FileNotFoundError as exc:
                raise RegionExistsError(
                    f"Region {name!r} exists but could not be attached"
                ) from exc

    def _attach(self, name: str) -> shared_memory.SharedMemory:
        try:
            shm = shared_memory.SharedMemory(name=name, create=False)
            logger.debug(f"Attached to shared memory region: {name}")
            return shm
        except FileNotFoundError as exc:
            raise RegionNotFoundError(
                f"Shared memory region {name!r} does not exist"
            ) from exc

    def _require_signal_region(self, key: int) -> shared_memory.SharedMemory:
        try:
            return self._signal_regions[key]
        except KeyError:
            raise KeyError(
                f"No signal region for key {key}. Call create_regions() or attach_regions() first."
            ) from None

    def _require_ack_region(self, key: int) -> shared_memory.SharedMemory:
        try:
            return self._ack_regions[key]
        except KeyError:
            raise KeyError(
                f"No ACK region for key {key}. Call create_regions() or attach_regions() first."
            ) from None

"""Generic shared memory manager for any signal type enum.

This module provides the core SharedMemoryManager class that handles
creation, attachment, and cleanup of shared memory regions for IPC.
"""

from multiprocessing import shared_memory
from typing import TypeVar

from loguru import logger

from champi_ipc.base.protocols import SignalTypeProtocol, StructRegistry
from champi_ipc.utils.ack import get_ack_size, pack_ack, unpack_ack

SignalT = TypeVar("SignalT", bound=SignalTypeProtocol)


class SharedMemoryManager:
    """Generic shared memory manager for any signal type enum.

    This class manages dedicated memory regions for each signal type,
    supporting data regions and ACK regions for signal loss detection.

    Type Parameters:
        SignalT: IntEnum type defining signal types

    Example:
        >>> from enum import IntEnum
        >>> class MySignals(IntEnum):
        ...     SIGNAL_A = 1
        ...     SIGNAL_B = 2
        >>>
        >>> # Create registry
        >>> registry = StructRegistry()
        >>> registry.register(MySignals.SIGNAL_A, 32, pack_a, unpack_a)
        >>>
        >>> # Create manager
        >>> mgr = SharedMemoryManager(
        ...     name_prefix="my_service",
        ...     signal_type_enum=MySignals,
        ...     struct_registry=registry
        ... )
        >>> mgr.create_regions()
    """

    def __init__(
        self,
        name_prefix: str,
        signal_type_enum: type[SignalT],
        struct_registry: StructRegistry,
    ):
        """Initialize shared memory manager.

        Args:
            name_prefix: Prefix for shared memory region names
            signal_type_enum: Enum class defining signal types
            struct_registry: Registry mapping signals to struct operations
        """
        self.name_prefix = name_prefix
        self.signal_type_enum = signal_type_enum
        self.registry = struct_registry
        self.memory_regions: dict[SignalT, shared_memory.SharedMemory] = {}
        self.ack_regions: dict[SignalT, shared_memory.SharedMemory] = {}
        self.is_creator = False

    def create_regions(self) -> None:
        """Create shared memory regions for all signal types (data + ACK).

        Creates two regions per signal type:
        - Data region: Stores packed signal struct
        - ACK region: Stores sequence number of last processed signal

        Raises:
            FileExistsError: If regions already exist (need cleanup first)
            PermissionError: If insufficient permissions to create regions
        """
        self.is_creator = True

        for signal_type in self.signal_type_enum:
            # Create data region
            region_name = f"{self.name_prefix}_{signal_type.name.lower()}"
            size = self.registry.get_struct_size(signal_type)

            try:
                # Try to unlink existing (cleanup from previous run)
                try:
                    existing = shared_memory.SharedMemory(name=region_name)
                    existing.close()
                    existing.unlink()
                except FileNotFoundError:
                    pass

                # Create new region
                shm = shared_memory.SharedMemory(
                    name=region_name, create=True, size=size
                )

                # Initialize with zeros
                shm.buf[:] = bytes(size)

                self.memory_regions[signal_type] = shm
                logger.debug(
                    f"Created shared memory region: {region_name} ({size} bytes)"
                )

            except Exception as e:
                logger.error(f"Failed to create region {region_name}: {e}")
                raise

            # Create ACK region
            ack_region_name = f"{self.name_prefix}_{signal_type.name.lower()}_ack"
            ack_size = get_ack_size()

            try:
                # Try to unlink existing
                try:
                    existing = shared_memory.SharedMemory(name=ack_region_name)
                    existing.close()
                    existing.unlink()
                except FileNotFoundError:
                    pass

                # Create new ACK region
                ack_shm = shared_memory.SharedMemory(
                    name=ack_region_name, create=True, size=ack_size
                )

                # Initialize with zeros
                ack_shm.buf[:] = bytes(ack_size)

                self.ack_regions[signal_type] = ack_shm
                logger.debug(
                    f"Created ACK region: {ack_region_name} ({ack_size} bytes)"
                )

            except Exception as e:
                logger.error(f"Failed to create ACK region {ack_region_name}: {e}")
                raise

    def attach_regions(self) -> None:
        """Attach to existing shared memory regions (data + ACK).

        Consumer processes call this instead of create_regions().

        Raises:
            FileNotFoundError: If regions don't exist (creator must create first)
        """
        self.is_creator = False

        for signal_type in self.signal_type_enum:
            # Attach to data region
            region_name = f"{self.name_prefix}_{signal_type.name.lower()}"

            try:
                shm = shared_memory.SharedMemory(name=region_name)
                self.memory_regions[signal_type] = shm
                logger.debug(f"Attached to region: {region_name}")
            except FileNotFoundError:
                logger.error(f"Region not found: {region_name}")
                raise

            # Attach to ACK region
            ack_region_name = f"{self.name_prefix}_{signal_type.name.lower()}_ack"

            try:
                ack_shm = shared_memory.SharedMemory(name=ack_region_name)
                self.ack_regions[signal_type] = ack_shm
                logger.debug(f"Attached to ACK region: {ack_region_name}")
            except FileNotFoundError:
                logger.error(f"ACK region not found: {ack_region_name}")
                raise

    def write_signal(self, signal_type: SignalT, data: bytes) -> None:
        """Write signal data to appropriate memory region.

        Args:
            signal_type: Type of signal
            data: Packed signal data (must match struct size)

        Raises:
            ValueError: If signal type not registered or data size mismatch
        """
        if signal_type not in self.memory_regions:
            raise ValueError(f"No memory region for: {signal_type}")

        shm = self.memory_regions[signal_type]
        expected_size = self.registry.get_struct_size(signal_type)

        if len(data) != expected_size:
            raise ValueError(
                f"Data size mismatch: expected {expected_size}, got {len(data)}"
            )

        # Atomic write to shared memory
        shm.buf[:expected_size] = data

    def read_signal(self, signal_type: SignalT) -> bytes:
        """Read signal data from memory region.

        Args:
            signal_type: Type of signal

        Returns:
            Packed signal data

        Raises:
            ValueError: If signal type not registered
        """
        if signal_type not in self.memory_regions:
            raise ValueError(f"No memory region for: {signal_type}")

        shm = self.memory_regions[signal_type]
        size = self.registry.get_struct_size(signal_type)

        return bytes(shm.buf[:size])

    def write_ack(self, signal_type: SignalT, seq_num: int) -> None:
        """Write ACK with sequence number to ACK region.

        Called by reader after successfully processing a signal.

        Args:
            signal_type: Type of signal
            seq_num: Sequence number to acknowledge
        """
        if signal_type not in self.ack_regions:
            raise ValueError(f"No ACK region for: {signal_type}")

        ack_data = pack_ack(seq_num)
        ack_shm = self.ack_regions[signal_type]
        ack_shm.buf[: len(ack_data)] = ack_data

    def read_ack(self, signal_type: SignalT) -> int:
        """Read ACK sequence number from ACK region.

        Used by processor to detect signal loss.

        Args:
            signal_type: Type of signal

        Returns:
            Last acknowledged sequence number
        """
        if signal_type not in self.ack_regions:
            raise ValueError(f"No ACK region for: {signal_type}")

        ack_shm = self.ack_regions[signal_type]
        ack_size = get_ack_size()
        ack_data = bytes(ack_shm.buf[:ack_size])
        return unpack_ack(ack_data)

    def cleanup(self) -> None:
        """Close and optionally unlink shared memory regions.

        If this instance created the regions (create_regions() was called),
        the regions will be unlinked. Otherwise they're just closed.
        """
        # Cleanup data regions
        for signal_type, shm in self.memory_regions.items():
            try:
                shm.close()

                if self.is_creator:
                    shm.unlink()
                    logger.debug(
                        f"Cleaned up region: {self.name_prefix}_{signal_type.name.lower()}"
                    )
            except Exception as e:
                logger.error(f"Error cleaning up {signal_type}: {e}")

        self.memory_regions.clear()

        # Cleanup ACK regions
        for signal_type, ack_shm in self.ack_regions.items():
            try:
                ack_shm.close()

                if self.is_creator:
                    ack_shm.unlink()
                    logger.debug(
                        f"Cleaned up ACK region: {self.name_prefix}_{signal_type.name.lower()}_ack"
                    )
            except Exception as e:
                logger.error(f"Error cleaning up ACK for {signal_type}: {e}")

        self.ack_regions.clear()

    def __enter__(self) -> "SharedMemoryManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

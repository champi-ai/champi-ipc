"""Compatibility shim — SharedMemoryManager lives in shared_memory_manager."""

from champi_ipc.core.shared_memory_manager import SharedMemoryManager

__all__ = ["SharedMemoryManager"]

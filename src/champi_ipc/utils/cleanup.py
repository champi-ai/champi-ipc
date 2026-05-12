"""Utilities for listing and cleaning up orphaned shared memory regions."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from multiprocessing import shared_memory

from loguru import logger


@dataclass
class CleanupResult:
    """Result of a cleanup operation.

    Attributes:
        removed: Names of regions that were successfully removed.
        failed: Names of regions that could not be removed.
    """

    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def total_removed(self) -> int:
        """Total number of successfully removed regions."""
        return len(self.removed)

    @property
    def total_failed(self) -> int:
        """Total number of regions that could not be removed."""
        return len(self.failed)


def list_regions(prefix: str) -> list[str]:
    """Return names of all shared memory regions whose names start with *prefix*.

    Currently supports Linux only (reads ``/dev/shm``).  On other platforms
    an empty list is returned.

    Args:
        prefix: Region name prefix to filter on.

    Returns:
        Sorted list of matching region names (without path components).
    """
    system = platform.system()
    regions: list[str] = []

    if system == "Linux":
        shm_dir = "/dev/shm"
        if os.path.isdir(shm_dir):
            for name in os.listdir(shm_dir):
                if name.startswith(prefix):
                    regions.append(name)
    else:
        logger.debug(
            "list_regions: unsupported platform {!r} — returning empty list", system
        )

    return sorted(regions)


def get_region_info(region_name: str) -> dict[str, object]:
    """Return metadata about a single shared memory region.

    Args:
        region_name: Name of the shared memory region (no path prefix).

    Returns:
        A dict with keys:

        - ``name`` (str): The region name.
        - ``exists`` (bool): Whether the region exists and is accessible.
        - ``size`` (int): Byte size, or 0 if the region does not exist.
    """
    info: dict[str, object] = {"name": region_name, "exists": False, "size": 0}
    try:
        shm = shared_memory.SharedMemory(name=region_name, create=False)
        info["exists"] = True
        info["size"] = shm.size
        shm.close()
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not inspect region {!r}: {}", region_name, exc)
    return info


def cleanup_orphaned_regions(prefix: str) -> CleanupResult:
    """Remove all shared memory regions whose names start with *prefix*.

    Intended to clean up regions left behind by crashed processes.  Safe
    to call even when no matching regions exist.

    Args:
        prefix: Region name prefix to match.

    Returns:
        :class:`CleanupResult` describing what was removed and what failed.
    """
    result = CleanupResult()

    for name in list_regions(prefix):
        try:
            shm = shared_memory.SharedMemory(name=name, create=False)
            shm.close()
            shm.unlink()
            result.removed.append(name)
            logger.info("Removed orphaned region: {}", name)
        except FileNotFoundError:
            # Already gone — count as removed.
            result.removed.append(name)
        except Exception as exc:  # noqa: BLE001
            result.failed.append(name)
            logger.warning("Failed to remove region {!r}: {}", name, exc)

    return result

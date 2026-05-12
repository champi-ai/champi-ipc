"""Shared memory cleanup utilities for champi services.

On Linux, POSIX shared memory regions are visible as files under
``/dev/shm``.  These utilities operate on that directory directly using
:mod:`pathlib`, which is simpler and more reliable than going through
:class:`multiprocessing.shared_memory.SharedMemory` for bulk operations.

macOS note
----------
macOS does not expose POSIX shared memory regions as files in a
predictable location accessible to ordinary processes.  Functions that
require filesystem enumeration (:func:`list_regions`,
:func:`cleanup_orphaned_regions`) emit a :class:`RuntimeWarning` and
return empty results on macOS.  :func:`get_region_info` falls back to
probing via :class:`multiprocessing.shared_memory.SharedMemory` and
works on any platform where the region name is known in advance.
"""

from __future__ import annotations

import platform
import sys
import warnings
from dataclasses import dataclass
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import TypedDict

from champi_ipc.base.exceptions import RegionNotFoundError

__all__ = [
    "CleanupResult",
    "RegionInfo",
    "RegionNotFoundError",
    "cleanup_orphaned_regions",
    "get_region_info",
    "list_regions",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SHM_DIR = Path("/dev/shm")
_IS_LINUX = sys.platform.startswith("linux")


def _shm_dir_available() -> bool:
    """Return True when /dev/shm is accessible on this platform."""
    return _IS_LINUX and _shm_dir_available._checked  # type: ignore[attr-defined]


# Evaluate once at import time.
_shm_dir_available._checked = _IS_LINUX and _SHM_DIR.is_dir()  # type: ignore[attr-defined]


def _warn_macos() -> None:
    warnings.warn(
        "Shared memory enumeration via /dev/shm is not available on this "
        "platform.  list_regions() and cleanup_orphaned_regions() are no-ops.",
        RuntimeWarning,
        stacklevel=3,
    )


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


class RegionInfo(TypedDict):
    """Information about a single shared memory region.

    Attributes:
        name: The region name (as passed to ``SharedMemory(name=...)``).
        size: Size in bytes, or ``0`` when the size cannot be determined.
        mtime: Last-modified time as a POSIX timestamp, or ``None`` when
            the backing file is not accessible.
        exists: ``True`` when the region can be opened for reading.
    """

    name: str
    size: int
    mtime: float | None
    exists: bool


@dataclass
class CleanupResult:
    """Outcome of a :func:`cleanup_orphaned_regions` call.

    Attributes:
        removed: Names of regions that were successfully unlinked.
        failed: Mapping of region name to the exception that prevented removal.
    """

    removed: list[str]
    failed: dict[str, Exception]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_regions(prefix: str = "") -> list[str]:
    """Return the names of all POSIX shared memory regions matching *prefix*.

    On Linux the function scans ``/dev/shm`` and returns the filename of
    every entry whose name starts with *prefix*.  On other platforms it
    emits a :class:`RuntimeWarning` and returns an empty list.

    Args:
        prefix: Optional name prefix to filter by.  Pass an empty string
            (the default) to list every region in ``/dev/shm``.

    Returns:
        Sorted list of matching region names, without a leading ``/``.
    """
    if not _shm_dir_available():
        _warn_macos()
        return []

    names = [
        entry.name
        for entry in _SHM_DIR.iterdir()
        if entry.is_file() and entry.name.startswith(prefix)
    ]
    return sorted(names)


def get_region_info(name: str) -> RegionInfo:
    """Return size, mtime, and existence flag for a named shared memory region.

    On Linux the function reads metadata from ``/dev/shm/<name>``.  On
    other platforms it attempts to open the region via
    :class:`multiprocessing.shared_memory.SharedMemory`; size is available
    but mtime is not.

    Args:
        name: The region name, without a leading ``/``.

    Returns:
        A :class:`RegionInfo` dict with keys ``name``, ``size``,
        ``mtime``, and ``exists``.

    Raises:
        RegionNotFoundError: When no region with the given name exists.
    """
    if _shm_dir_available():
        path = _SHM_DIR / name
        if not path.exists():
            raise RegionNotFoundError(name)
        stat = path.stat()
        return RegionInfo(
            name=name,
            size=stat.st_size,
            mtime=stat.st_mtime,
            exists=True,
        )

    # Non-Linux fallback: probe via the SharedMemory API.
    try:
        shm = SharedMemory(name=name, create=False)
    except FileNotFoundError:
        raise RegionNotFoundError(name) from None
    size = shm.size
    shm.close()
    return RegionInfo(name=name, size=size, mtime=None, exists=True)


def cleanup_orphaned_regions(prefix: str) -> CleanupResult:
    """Remove all POSIX shared memory regions whose name starts with *prefix*.

    The function does not attempt to detect whether a region is still in
    use; it removes every region matching the prefix.  Callers are
    responsible for ensuring that no live process holds the region open
    before calling this function.

    On Linux, each matching entry in ``/dev/shm`` is unlinked directly via
    :func:`pathlib.Path.unlink`.  On other platforms the function emits a
    :class:`RuntimeWarning` and returns an empty :class:`CleanupResult`.

    Args:
        prefix: Name prefix that identifies regions belonging to a champi
            service (e.g. ``"champi_"``).  Must be a non-empty string.

    Returns:
        A :class:`CleanupResult` with the names of successfully removed
        regions and a mapping of names to exceptions for any failures.

    Raises:
        ValueError: When *prefix* is an empty string, to prevent
            accidentally unlinking unrelated system-wide regions.
    """
    if not prefix:
        raise ValueError("prefix must be a non-empty string")

    if not _shm_dir_available():
        _warn_macos()
        return CleanupResult(removed=[], failed={})

    result = CleanupResult(removed=[], failed={})
    for entry in _SHM_DIR.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.startswith(prefix):
            continue
        try:
            entry.unlink()
            result.removed.append(entry.name)
        except OSError as exc:
            result.failed[entry.name] = exc

    result.removed.sort()
    return result


# ---------------------------------------------------------------------------
# Platform info helper (used by tests)
# ---------------------------------------------------------------------------


def _running_on_linux() -> bool:
    """Return True when the current platform is Linux."""
    return platform.system() == "Linux"

"""Cleanup utilities for orphaned shared memory regions.

Provides functions to clean up regions left behind by crashed processes
or improper shutdowns.
"""

import os
import platform
from multiprocessing import shared_memory
from typing import Any

from loguru import logger

from champi_ipc.base.protocols import SignalTypeProtocol


def cleanup_orphaned_regions(
    name_prefix: str, signal_type_enum: type[SignalTypeProtocol]
) -> list[str]:
    """Clean up orphaned shared memory regions.

    Removes regions left behind by crashed processes or improper shutdowns.
    Safe to call even if regions don't exist.

    Args:
        name_prefix: Memory region prefix to clean up
        signal_type_enum: Enum defining signal types

    Returns:
        List of cleaned region names

    Example:
        >>> from my_service import MySignals
        >>> cleaned = cleanup_orphaned_regions("my_service", MySignals)
        >>> print(f"Cleaned {len(cleaned)} regions")
    """
    cleaned_regions = []

    for signal_type in signal_type_enum:
        # Try to clean up data region
        region_name = f"{name_prefix}_{signal_type.name.lower()}"
        try:
            shm = shared_memory.SharedMemory(name=region_name)
            shm.close()
            shm.unlink()
            cleaned_regions.append(region_name)
            logger.info(f"Cleaned up orphaned region: {region_name}")
        except FileNotFoundError:
            pass  # Region doesn't exist, skip
        except Exception as e:
            logger.warning(f"Failed to clean up {region_name}: {e}")

        # Try to clean up ACK region
        ack_region_name = f"{name_prefix}_{signal_type.name.lower()}_ack"
        try:
            ack_shm = shared_memory.SharedMemory(name=ack_region_name)
            ack_shm.close()
            ack_shm.unlink()
            cleaned_regions.append(ack_region_name)
            logger.info(f"Cleaned up orphaned ACK region: {ack_region_name}")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Failed to clean up {ack_region_name}: {e}")

    return cleaned_regions


def list_regions(name_prefix: str) -> list[str]:
    """List all shared memory regions with given prefix.

    Args:
        name_prefix: Region prefix to search for

    Returns:
        List of region names

    Note:
        This function relies on OS-specific mechanisms:
        - Linux: /dev/shm/
        - macOS/BSD: /var/tmp/
        - Windows: Global\\ namespace
    """
    regions = []
    system = platform.system()

    if system == "Linux":
        shm_dir = "/dev/shm"
        if os.path.exists(shm_dir):
            for filename in os.listdir(shm_dir):
                if filename.startswith(name_prefix):
                    regions.append(filename)

    elif system == "Darwin":  # macOS
        # macOS uses /var/tmp for POSIX shared memory
        # Names are typically prefixed
        shm_dir = "/var/tmp"
        if os.path.exists(shm_dir):
            for filename in os.listdir(shm_dir):
                if filename.startswith(name_prefix):
                    regions.append(filename)

    elif system == "Windows":
        # Windows uses Global\\ namespace
        # More complex to enumerate, would need win32 API
        logger.warning("list_regions not fully implemented for Windows")
        pass

    return regions


def get_region_info(region_name: str) -> dict[str, Any]:
    """Get information about a shared memory region.

    Args:
        region_name: Name of the region

    Returns:
        Dictionary with region info:
        - name: Region name
        - size: Size in bytes
        - exists: Whether region exists
        - accessible: Whether we can access it

    Example:
        >>> info = get_region_info("my_service_signal_a")
        >>> print(f"Size: {info['size']} bytes")
    """
    info: dict[str, Any] = {
        "name": region_name,
        "size": 0,
        "exists": False,
        "accessible": False,
    }

    try:
        shm = shared_memory.SharedMemory(name=region_name)
        info["size"] = shm.size
        info["exists"] = True
        info["accessible"] = True
        shm.close()
    except FileNotFoundError:
        info["exists"] = False
    except PermissionError:
        info["exists"] = True
        info["accessible"] = False
    except Exception as e:
        logger.warning(f"Error getting info for {region_name}: {e}")

    return info

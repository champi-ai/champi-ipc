"""Tests for champi_ipc.utils.cleanup.

All tests that touch /dev/shm are skipped on non-Linux platforms, since
that directory is a Linux-specific facility.
"""

from __future__ import annotations

import sys
from multiprocessing.shared_memory import SharedMemory

import pytest

from champi_ipc.utils.cleanup import (
    CleanupResult,
    RegionNotFoundError,
    cleanup_orphaned_regions,
    get_region_info,
    list_regions,
)

_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(not _LINUX, reason="requires /dev/shm (Linux only)")

# Prefix used exclusively by these tests so they cannot interfere with real
# champi regions or other test runs.
_TEST_PREFIX = "_champi_test_cleanup_"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_shm(name: str, size: int = 64) -> SharedMemory:
    """Create a SharedMemory block and return it (caller must close/unlink)."""
    return SharedMemory(name=name, create=True, size=size)


# ---------------------------------------------------------------------------
# list_regions
# ---------------------------------------------------------------------------


class TestListRegions:
    """Tests for list_regions()."""

    @linux_only
    def test_empty_when_no_matching_regions(self) -> None:
        names = list_regions(prefix=_TEST_PREFIX)
        assert names == []

    @linux_only
    def test_finds_created_region(self) -> None:
        name = f"{_TEST_PREFIX}find_me"
        shm = _create_shm(name)
        try:
            found = list_regions(prefix=_TEST_PREFIX)
            assert name in found
        finally:
            shm.close()
            shm.unlink()

    @linux_only
    def test_returns_sorted_list(self) -> None:
        names = [f"{_TEST_PREFIX}z", f"{_TEST_PREFIX}a", f"{_TEST_PREFIX}m"]
        shms = [_create_shm(n) for n in names]
        try:
            result = list_regions(prefix=_TEST_PREFIX)
            matching = [r for r in result if r.startswith(_TEST_PREFIX)]
            assert matching == sorted(matching)
        finally:
            for s in shms:
                s.close()
                s.unlink()

    @linux_only
    def test_prefix_filters_correctly(self) -> None:
        wanted = f"{_TEST_PREFIX}wanted"
        other = "_champi_test_OTHER_unwanted"
        shm_w = _create_shm(wanted)
        shm_o = _create_shm(other)
        try:
            result = list_regions(prefix=_TEST_PREFIX)
            assert wanted in result
            assert other not in result
        finally:
            shm_w.close()
            shm_w.unlink()
            shm_o.close()
            shm_o.unlink()

    @linux_only
    def test_no_prefix_returns_all(self) -> None:
        name = f"{_TEST_PREFIX}any"
        shm = _create_shm(name)
        try:
            result = list_regions()
            assert name in result
        finally:
            shm.close()
            shm.unlink()

    def test_non_linux_returns_empty_with_warning(self) -> None:
        if _LINUX:
            pytest.skip("macOS/Windows-only branch")
        with pytest.warns(RuntimeWarning):
            result = list_regions(prefix="anything")
        assert result == []


# ---------------------------------------------------------------------------
# get_region_info
# ---------------------------------------------------------------------------


class TestGetRegionInfo:
    """Tests for get_region_info()."""

    @linux_only
    def test_returns_correct_size(self) -> None:
        name = f"{_TEST_PREFIX}info_size"
        shm = _create_shm(name, size=128)
        try:
            info = get_region_info(name)
            assert info["name"] == name
            assert info["size"] == 128
            assert info["exists"] is True
            assert info["mtime"] is not None
        finally:
            shm.close()
            shm.unlink()

    @linux_only
    def test_raises_for_unknown_name(self) -> None:
        with pytest.raises(RegionNotFoundError) as exc_info:
            get_region_info(f"{_TEST_PREFIX}does_not_exist_xyz")
        assert "does_not_exist_xyz" in str(exc_info.value)

    @linux_only
    def test_region_not_found_error_has_name_attr(self) -> None:
        bad_name = f"{_TEST_PREFIX}missing"
        with pytest.raises(RegionNotFoundError) as exc_info:
            get_region_info(bad_name)
        assert exc_info.value.name == bad_name

    def test_non_linux_raises_for_unknown_name(self) -> None:
        if _LINUX:
            pytest.skip("macOS/Windows-only branch")
        with pytest.raises(RegionNotFoundError):
            get_region_info(f"{_TEST_PREFIX}nonexistent_on_any_platform_xyz123")


# ---------------------------------------------------------------------------
# cleanup_orphaned_regions
# ---------------------------------------------------------------------------


class TestCleanupOrphanedRegions:
    """Tests for cleanup_orphaned_regions()."""

    @linux_only
    def test_removes_matching_regions(self) -> None:
        names = [f"{_TEST_PREFIX}rm1", f"{_TEST_PREFIX}rm2"]
        shms = [_create_shm(n) for n in names]
        for s in shms:
            s.close()  # close but do NOT unlink — simulate orphan

        result = cleanup_orphaned_regions(prefix=_TEST_PREFIX)

        assert isinstance(result, CleanupResult)
        for name in names:
            assert name in result.removed

        # Verify they are gone
        remaining = list_regions(prefix=_TEST_PREFIX)
        for name in names:
            assert name not in remaining

    @linux_only
    def test_does_not_remove_non_matching_regions(self) -> None:
        keep = "_champi_test_OTHER_keep_me"
        shm = _create_shm(keep)
        shm.close()
        try:
            cleanup_orphaned_regions(prefix=_TEST_PREFIX)
            still_there = list_regions(prefix="_champi_test_OTHER_keep_me")
            assert keep in still_there
        finally:
            shm2 = SharedMemory(name=keep, create=False)
            shm2.close()
            shm2.unlink()

    @linux_only
    def test_empty_result_when_no_matching_regions(self) -> None:
        result = cleanup_orphaned_regions(prefix=_TEST_PREFIX)
        assert result.removed == []
        assert result.failed == {}

    def test_raises_on_empty_prefix(self) -> None:
        with pytest.raises(ValueError, match="prefix"):
            cleanup_orphaned_regions(prefix="")

    def test_non_linux_returns_empty_with_warning(self) -> None:
        if _LINUX:
            pytest.skip("macOS/Windows-only branch")
        with pytest.warns(RuntimeWarning):
            result = cleanup_orphaned_regions(prefix="champi_")
        assert result.removed == []
        assert result.failed == {}


# ---------------------------------------------------------------------------
# Public import smoke test
# ---------------------------------------------------------------------------


def test_public_imports_from_top_level() -> None:
    """Verify cleanup symbols are reachable from the top-level package."""
    from champi_ipc import (
        RegionNotFoundError as RNF,
    )
    from champi_ipc import (
        cleanup_orphaned_regions as cor,
    )
    from champi_ipc import (
        get_region_info as gri,
    )
    from champi_ipc import (
        list_regions as lr,
    )

    assert RNF is RegionNotFoundError
    assert cor is cleanup_orphaned_regions
    assert gri is get_region_info
    assert lr is list_regions

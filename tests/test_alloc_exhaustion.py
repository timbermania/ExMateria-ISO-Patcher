"""FreeSpaceAllocator must raise RuntimeError when exhausted, and reuse
reservations when an existing key is requested again."""

from __future__ import annotations

import pytest

from fft_iso_patcher.free_space import FreeSpaceAllocator
from fft_iso_patcher.recipe import FreeSpace


def _alloc(ranges, reserved=None) -> FreeSpaceAllocator:
    return FreeSpaceAllocator.from_recipe(
        FreeSpace(ranges=tuple(tuple(r) for r in ranges), reserved_for_shishi=reserved)
    )


def test_allocate_consumes_low_range_first() -> None:
    a = _alloc([[1000, 1010], [2000, 2100]])
    assert a.allocate(5, "a") == 1000  # lowest range first
    assert a.allocate(5, "b") == 1005


def test_exhaustion_raises_runtime_error() -> None:
    a = _alloc([[500, 503]])
    a.allocate(2, "x")  # leaves 1 sector
    with pytest.raises(RuntimeError, match="no free range"):
        a.allocate(2, "y")


def test_reservation_idempotent() -> None:
    # Re-requesting the same key returns the prior LBA without consuming more.
    a = _alloc([[100, 110]])
    first = a.allocate(3, "music_41")
    second = a.allocate(3, "music_41")
    assert first == second == 100
    # Subsequent fresh allocations start where the first one ended.
    assert a.allocate(2, "music_42") == 103


def test_reserved_for_shishi_carves_range() -> None:
    # Reserve [105, 108) — splits [100, 110) into [100, 105) and [108, 110).
    a = _alloc([[100, 110]], reserved=(105, 108))
    assert a.allocate(5, "a") == 100  # fits in lower split
    with pytest.raises(RuntimeError):
        # Only 2 sectors left in upper split [108, 110) — request for 3 fails.
        a.allocate(3, "b")

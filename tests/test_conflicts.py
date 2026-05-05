"""_detect_conflicts must raise on overlapping BytePatches."""

from __future__ import annotations

import pytest

from fft_iso_patcher.assets.byte_patch import BytePatch
from fft_iso_patcher.patcher import _detect_conflicts


def test_non_overlapping_same_sector_passes() -> None:
    a = BytePatch(lba=100, offset_in_payload=0, data=b"\x01\x02", label="a")
    b = BytePatch(lba=100, offset_in_payload=4, data=b"\x03\x04", label="b")
    _detect_conflicts([a, b])  # adjacent but disjoint — must not raise


def test_different_sectors_pass() -> None:
    a = BytePatch(lba=100, offset_in_payload=0, data=b"\x01" * 100, label="a")
    b = BytePatch(lba=101, offset_in_payload=0, data=b"\x02" * 100, label="b")
    _detect_conflicts([a, b])


def test_overlapping_same_sector_raises() -> None:
    a = BytePatch(lba=100, offset_in_payload=0, data=b"\x01\x02\x03\x04", label="a")
    b = BytePatch(lba=100, offset_in_payload=2, data=b"\x05\x06", label="b")
    with pytest.raises(ValueError, match="LBA 100"):
        _detect_conflicts([a, b])


def test_identical_patches_raise() -> None:
    a = BytePatch(lba=42, offset_in_payload=10, data=b"\xff", label="a")
    b = BytePatch(lba=42, offset_in_payload=10, data=b"\xff", label="b")
    with pytest.raises(ValueError):
        _detect_conflicts([a, b])


def test_touching_boundary_does_not_overlap() -> None:
    # patch a covers offsets [0, 4); patch b covers [4, 8) — disjoint at 4.
    a = BytePatch(lba=200, offset_in_payload=0, data=b"\x00" * 4, label="a")
    b = BytePatch(lba=200, offset_in_payload=4, data=b"\x00" * 4, label="b")
    _detect_conflicts([a, b])

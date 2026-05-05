"""Verify the music LBA + size table in SCUS_942.21 decodes correctly."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from fft_iso_patcher.iso9660 import find_file
from fft_iso_patcher.iso_sectors import PsxDisc

from ._assets import ISO_PATH

MUSIC_TABLE_OFFSET = 0x37880


@pytest.fixture(scope="module")
def disc() -> PsxDisc:
    if not ISO_PATH.exists():
        pytest.skip(f"ISO not found at {ISO_PATH}")
    return PsxDisc(ISO_PATH)


def test_find_scus(disc: PsxDisc) -> None:
    rec = find_file(disc, "/SCUS_942.21;1")
    assert rec.lba > 0
    assert rec.size_bytes > 0


def test_decode_music_table(disc: PsxDisc) -> None:
    rec = find_file(disc, "/SCUS_942.21;1")
    n_sectors = (rec.size_bytes + 2047) // 2048
    scus = disc.read_user_data(rec.lba, n_sectors)

    # Decode the first 100 entries of the music table.
    table = scus[MUSIC_TABLE_OFFSET:MUSIC_TABLE_OFFSET + 100 * 8]
    entries = [struct.unpack_from("<II", table, i * 8) for i in range(100)]

    # Sanity check known values.
    assert entries[0] == (85249, 10240),  f"MUSIC_00: {entries[0]}"
    assert entries[18] == (85318, 18432), f"MUSIC_18: {entries[18]}"
    assert entries[41] == (85373, 2048),  f"MUSIC_41: {entries[41]}"
    assert entries[99] == (85508, 20480), f"MUSIC_99: {entries[99]}"

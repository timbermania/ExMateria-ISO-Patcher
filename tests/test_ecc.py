"""For known sectors on the original ISO, regen EDC+ECC over the user data
and assert the result matches the bytes already on disc."""

from __future__ import annotations

from pathlib import Path

import pytest

from fft_iso_patcher.iso_sectors import (
    EDC_OFFSET,
    P_PARITY_OFFSET,
    Q_PARITY_OFFSET,
    PsxDisc,
    SECTOR_SIZE,
    regenerate_edc_ecc,
)

from ._assets import ISO_PATH


@pytest.fixture(scope="module")
def disc() -> PsxDisc:
    if not ISO_PATH.exists():
        pytest.skip(f"ISO not found at {ISO_PATH}")
    return PsxDisc(ISO_PATH)


@pytest.mark.parametrize(
    "lba",
    [
        16,        # Primary Volume Descriptor
        85249,     # MUSIC_00
        85318,     # MUSIC_18
        85373,     # MUSIC_41
    ],
)
def test_regenerate_matches_disc(disc: PsxDisc, lba: int) -> None:
    original = disc.read_sector(lba)
    assert len(original) == SECTOR_SIZE
    sector = bytearray(original)
    regenerate_edc_ecc(sector)

    # EDC region (4 bytes)
    assert bytes(sector[EDC_OFFSET:EDC_OFFSET + 4]) == original[EDC_OFFSET:EDC_OFFSET + 4], (
        f"EDC mismatch at LBA {lba}"
    )
    # P parity (172 bytes)
    assert bytes(sector[P_PARITY_OFFSET:P_PARITY_OFFSET + 172]) == \
        original[P_PARITY_OFFSET:P_PARITY_OFFSET + 172], f"P parity mismatch at LBA {lba}"
    # Q parity (104 bytes)
    assert bytes(sector[Q_PARITY_OFFSET:Q_PARITY_OFFSET + 104]) == \
        original[Q_PARITY_OFFSET:Q_PARITY_OFFSET + 104], f"Q parity mismatch at LBA {lba}"
    # And the entire sector should be byte-identical.
    assert bytes(sector) == original

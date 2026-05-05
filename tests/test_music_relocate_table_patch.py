"""Phase 2 relocation: the SCUS music-table entry is rewritten to point
at the new LBA + size."""

from __future__ import annotations

import json
import struct
import textwrap
from pathlib import Path

import pytest

from fft_iso_patcher.iso9660 import find_file
from fft_iso_patcher.iso_sectors import PsxDisc, USER_DATA_SIZE
from fft_iso_patcher.patcher import apply

from ._assets import ISO_PATH

MUSIC_TABLE_OFFSET = 0x37880
SLOT = 41


@pytest.mark.skipif(not ISO_PATH.exists(), reason=f"ISO not found at {ISO_PATH}")
def test_relocate_patches_table_entry(tmp_path: Path) -> None:
    smd_path = tmp_path / "payload.smd"
    smd_path.write_bytes(b"smds" + bytes(4096))  # 4 KB payload, forces 3-sector relocation

    out_iso = tmp_path / "out.bin"
    manifest_path = tmp_path / "out.manifest.json"

    recipe_text = textwrap.dedent(
        f"""
        schema_version = 1

        [input]
        iso = "{ISO_PATH}"

        [output]
        iso = "{out_iso}"
        manifest = "{manifest_path}"

        [free_space]
        ranges = [[224050, 230000]]
        reserved_for_shishi = [219250, 224050]

        [[patches.music]]
        slot = {SLOT}
        file = "{smd_path}"
        allow_relocate = true
        """
    )
    recipe_path = tmp_path / "recipe.toml"
    recipe_path.write_text(recipe_text)

    apply(recipe_path)

    manifest = json.loads(manifest_path.read_text())
    placement = next(p for p in manifest["placements"] if p["slot"] == SLOT)
    assert placement["relocated"] is True
    assert placement["lba"] == 224050  # first available LBA in the [224050, 230000) range
    assert placement["original_lba"] == 85373

    # Now read the patched table entry from the output ISO and assert it
    # was rewritten to (placement.lba, placement.size_padded).
    disc = PsxDisc(out_iso)
    scus = find_file(disc, "/SCUS_942.21;1")
    sec_idx, off = divmod(MUSIC_TABLE_OFFSET, USER_DATA_SIZE)
    raw = disc.read_user_data(scus.lba + sec_idx, 1)
    lba, size = struct.unpack_from("<II", raw, off + SLOT * 8)

    assert lba == placement["lba"], f"table entry LBA: expected {placement['lba']}, got {lba}"
    assert size == placement["size_padded"], (
        f"table entry size: expected {placement['size_padded']}, got {size}"
    )

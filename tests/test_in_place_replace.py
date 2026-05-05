"""In-place replacement: a payload that fits the slot's existing sectors
must NOT relocate, and the table LBA must stay unchanged."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from fft_iso_patcher.patcher import apply

from ._assets import ISO_PATH

SLOT = 41  # MUSIC_41 has a 2048-byte (1-sector) slot in vanilla, easy to fit.


@pytest.mark.skipif(not ISO_PATH.exists(), reason=f"ISO not found at {ISO_PATH}")
def test_in_place_payload_does_not_relocate(tmp_path: Path) -> None:
    smd_path = tmp_path / "tiny.smd"
    # 1-sector payload (≤ 2048 bytes) fits MUSIC_41's existing allocation.
    smd_path.write_bytes(b"smds" + bytes(2044))

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

        [[patches.music]]
        slot = {SLOT}
        file = "{smd_path}"
        """
    )
    recipe_path = tmp_path / "recipe.toml"
    recipe_path.write_text(recipe_text)

    apply(recipe_path)

    manifest = json.loads(manifest_path.read_text())
    placement = next(p for p in manifest["placements"] if p["slot"] == SLOT)
    assert placement["relocated"] is False
    assert placement["lba"] == placement["original_lba"], (
        "in-place replacement must keep the original LBA"
    )
    assert placement["n_sectors"] == 1


@pytest.mark.skipif(not ISO_PATH.exists(), reason=f"ISO not found at {ISO_PATH}")
def test_oversize_without_allow_relocate_raises(tmp_path: Path) -> None:
    smd_path = tmp_path / "big.smd"
    smd_path.write_bytes(b"smds" + bytes(4096))  # 3 sectors > MUSIC_41's 1-sector slot

    out_iso = tmp_path / "out.bin"
    recipe_text = textwrap.dedent(
        f"""
        schema_version = 1

        [input]
        iso = "{ISO_PATH}"

        [output]
        iso = "{out_iso}"

        [[patches.music]]
        slot = {SLOT}
        file = "{smd_path}"
        """
    )
    recipe_path = tmp_path / "recipe.toml"
    recipe_path.write_text(recipe_text)

    with pytest.raises(ValueError, match="allow_relocate"):
        apply(recipe_path)

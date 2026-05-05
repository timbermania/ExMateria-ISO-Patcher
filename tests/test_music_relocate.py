"""Phase 2 relocation: applying twice produces a byte-identical ISO."""

from __future__ import annotations

import filecmp
import textwrap
from pathlib import Path

import pytest

from fft_iso_patcher.patcher import apply

from ._assets import ISO_PATH


@pytest.mark.skipif(not ISO_PATH.exists(), reason=f"ISO not found at {ISO_PATH}")
def test_relocate_apply_is_deterministic(tmp_path: Path) -> None:
    smd_path = tmp_path / "payload.smd"
    # 3-sector payload — must exceed MUSIC_41's 2048-byte slot to force relocation.
    smd_path.write_bytes(b"smds" + bytes(4096))

    out_a = tmp_path / "a.bin"
    out_b = tmp_path / "b.bin"
    manifest_a = tmp_path / "a.manifest.json"
    manifest_b = tmp_path / "b.manifest.json"

    def write_recipe(out_iso: Path, manifest: Path) -> Path:
        text = textwrap.dedent(
            f"""
            schema_version = 1

            [input]
            iso = "{ISO_PATH}"

            [output]
            iso = "{out_iso}"
            manifest = "{manifest}"

            [free_space]
            ranges = [[224050, 230000]]
            reserved_for_shishi = [219250, 224050]

            [[patches.music]]
            slot = 41
            file = "{smd_path}"
            allow_relocate = true
            """
        )
        recipe_path = tmp_path / f"{out_iso.stem}.recipe.toml"
        recipe_path.write_text(text)
        return recipe_path

    apply(write_recipe(out_a, manifest_a))
    apply(write_recipe(out_b, manifest_b))

    assert filecmp.cmp(out_a, out_b, shallow=False), (
        "two runs of the same relocate recipe produced different ISOs"
    )

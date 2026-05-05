"""Empty recipe → output ISO must be byte-identical to input ISO."""

from __future__ import annotations

import filecmp
import json
from pathlib import Path

import pytest

from fft_iso_patcher.patcher import apply

from ._assets import ISO_PATH

RECIPE = Path(__file__).parent / "recipes" / "empty.toml"


@pytest.mark.skipif(not ISO_PATH.exists(), reason=f"ISO not found at {ISO_PATH}")
def test_noop_apply_preserves_iso(tmp_path: Path) -> None:
    out_iso = tmp_path / "noop.bin"
    out_manifest = tmp_path / "noop.manifest.json"

    recipe_text = (
        "schema_version = 1\n\n"
        "[input]\n"
        f'iso = "{ISO_PATH}"\n\n'
        "[output]\n"
        f'iso = "{out_iso}"\n'
        f'manifest = "{out_manifest}"\n'
    )
    recipe_path = tmp_path / "recipe.toml"
    recipe_path.write_text(recipe_text)

    manifest = apply(recipe_path)
    assert out_iso.exists()
    assert filecmp.cmp(ISO_PATH, out_iso, shallow=False), (
        "noop apply produced a non-identical ISO copy"
    )
    assert manifest.placements == []
    doc = json.loads(out_manifest.read_text())
    assert doc["placements"] == []

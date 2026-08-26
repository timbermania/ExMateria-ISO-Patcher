"""Map (GNS) leg: in-place, in-place grow/shrink, relocation, and refusals.

Fixtures come from the real disc (skipped when the ISO is absent):

- ``MAP001 a0``: 21 real records, 21 distinct files, no shared LBAs. The
  last real record of MAP001.GNS belongs to arrangement 1, so patching
  a0 exercises the "terminators untouched" branch of the terminator rule.
- ``MAP001 a1``: its last real record (MAP001.93, LBA 11301) is followed
  by 35 type-49 terminators — patching a1 and moving MAP001.93 must
  rewrite all 35 of them.
- ``MAP000 a2``: arrangement with no real records — the "nothing to
  patch" refusal.

All positive tests run through the full ``apply`` pipeline (real ISO
copy, EDC/ECC regen); refusal tests call ``resolve_map`` directly.
"""

from __future__ import annotations

import filecmp
import json
import struct
import textwrap
from pathlib import Path

import pytest

from fft_iso_patcher.assets.map import (
    _parse_gns,
    _read_gns_table_entry,
    resolve_map,
    summary_line,
)
from fft_iso_patcher.free_space import FreeSpaceAllocator
from fft_iso_patcher.iso9660 import find_file, list_dir
from fft_iso_patcher.iso_sectors import PsxDisc
from fft_iso_patcher.iso_utils import bytes_to_sectors
from fft_iso_patcher.manifest import ManifestBuilder
from fft_iso_patcher.patcher import apply

from ._assets import ISO_PATH

pytestmark = pytest.mark.skipif(
    not ISO_PATH.exists(), reason=f"ISO not found at {ISO_PATH}"
)


@pytest.fixture(autouse=True)
def _clean_iso_copies(tmp_path):
    """Each `apply` copies the ~666MB ISO; drop the copies right after the
    test so the suite's /tmp footprint stays one copy at a time."""
    yield
    for p in tmp_path.glob("*.bin"):
        p.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _table_entry(map_id: int) -> int:
    disc = PsxDisc(ISO_PATH)
    return _read_gns_table_entry(disc, map_id)


def _map_dir_index() -> dict[int, object]:
    disc = PsxDisc(ISO_PATH)
    m = find_file(disc, "/MAP")
    return {
        r.lba: r for r in list_dir(disc, m.lba, m.size_bytes)
        if not r.is_dir
    }


def _disc_gns(map_id: int) -> tuple[int, int, bytes]:
    """(gns_lba, dir_size, raw_gns_bytes) for a map's GNS on the test ISO."""
    disc = PsxDisc(ISO_PATH)
    lba = _table_entry(map_id)
    assert lba != 0
    dir_rec = find_file(disc, f"/MAP/MAP{map_id:03d}.GNS;1")
    assert dir_rec.lba == lba
    size = dir_rec.size_bytes
    raw = disc.read_user_data(lba, bytes_to_sectors(size))[:size]
    return lba, size, raw


def _build_bundle(
    tmp_path: Path,
    map_id: int,
    arrangement: int,
    *,
    name: str,
    blob_overrides: dict[str, bytes] | None = None,
    gns_overrides: bytes | None = None,
) -> Path:
    """Write a bundle directory (GNS + one blob per arrangement record).

    ``blob_overrides`` replaces whole blobs by resource name; ``None``
    means "vanilla" (the original bytes from the disc).
    """
    disc = PsxDisc(ISO_PATH)
    gns_lba, gns_size, gns_raw = _disc_gns(map_id)
    records, _ = _parse_gns(gns_raw, "test GNS")
    dir_index = _map_dir_index()

    bundle = tmp_path / name
    bundle.mkdir()
    (bundle / f"MAP{map_id:03d}.GNS").write_bytes(
        gns_overrides if gns_overrides is not None else gns_raw
    )
    for rec in records:
        if not rec.is_real or rec.arrangement != arrangement:
            continue
        dir_rec = dir_index[rec.lba]
        resource = dir_rec.name[:-2]  # strip ";1"
        blob = disc.read_user_data(
            rec.lba, bytes_to_sectors(dir_rec.size_bytes)
        )[: dir_rec.size_bytes]
        (bundle / resource).write_bytes(
            blob_overrides[resource]
            if blob_overrides and resource in blob_overrides
            else blob
        )
    return bundle


def _write_recipe(
    tmp_path: Path,
    out_iso: Path,
    manifest: Path,
    bundle: Path,
    map_id: int,
    arrangement: int,
    *,
    allow_relocate: bool,
    extra_map_entries: list[tuple[Path, int, int]] | None = None,
) -> Path:
    entries = [(bundle, map_id, arrangement)]
    if extra_map_entries:
        entries.extend(extra_map_entries)
    map_blocks = "\n".join(
        textwrap.dedent(
            f"""
            [[patches.map]]
            map = {mid}
            arrangement = {arr}
            file = "{b}"
            allow_relocate = {"true" if allow_relocate else "false"}
            """
        )
        for b, mid, arr in entries
    )
    recipe_path = tmp_path / f"{out_iso.stem}.recipe.toml"
    recipe_path.write_text(
        textwrap.dedent(
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

            {map_blocks}
            """
        )
    )
    return recipe_path


def _manifest_rows(manifest_path: Path) -> list[dict]:
    return json.loads(manifest_path.read_text())["placements"]


def _user_data(iso: Path, lba: int, n_sectors: int = 1) -> bytes:
    return PsxDisc(iso).read_user_data(lba, n_sectors)


def _dir_words(iso: Path, map_id: int, resource: str) -> dict:
    """The both-endian LBA/size words of a /MAP directory record."""
    disc = PsxDisc(iso)
    m = find_file(disc, "/MAP")
    rec = next(
        r for r in list_dir(disc, m.lba, m.size_bytes)
        if r.name == f"{resource};1" and not r.is_dir
    )
    raw = disc.read_user_data(rec.containing_lba, 1)
    o = rec.offset_in_containing
    return {
        "lba_le": struct.unpack_from("<I", raw, o + 2)[0],
        "lba_be": struct.unpack_from(">I", raw, o + 6)[0],
        "size_le": struct.unpack_from("<I", raw, o + 10)[0],
        "size_be": struct.unpack_from(">I", raw, o + 14)[0],
        "lba": rec.lba,
        "size": rec.size_bytes,
    }


def _direct_resolve(
    tmp_path: Path,
    entry_config: dict,
) -> None:
    manifest = ManifestBuilder(
        recipe_path=tmp_path / "noop.recipe.toml",
        iso_in=ISO_PATH,
        iso_out=tmp_path / "out.bin",
    )
    free = FreeSpaceAllocator.from_recipe(
        type("FS", (), {"ranges": [(224050, 230000)],
                        "reserved_for_shishi": (219250, 224050)})()
    )
    resolve_map(entry_config, PsxDisc(ISO_PATH), free, manifest)


# --------------------------------------------------------------------------
# Positive: vanilla bundle is a byte-identical no-op
# --------------------------------------------------------------------------

def test_vanilla_bundle_is_noop(tmp_path: Path) -> None:
    gns_lba, gns_size, gns_raw = _disc_gns(1)
    bundle = _build_bundle(tmp_path, 1, 0, name="MAP001.a0")
    out = tmp_path / "vanilla.bin"
    manifest = tmp_path / "vanilla.manifest.json"
    apply(_write_recipe(tmp_path, out, manifest, bundle, 1, 0,
                        allow_relocate=False))

    rows = _manifest_rows(manifest)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "map"
    assert row["map"] == 1
    assert row["arrangement"] == 0
    assert row["gns"] == {"lba": gns_lba, "size_bytes": gns_size}
    assert len(row["resources"]) == 21
    for r in row["resources"]:
        assert r["relocated"] is False
        assert r["lba"] == r["original_lba"]
        assert r["size_padded"] == r["original_size_padded"]
        assert r["n_sectors"] == bytes_to_sectors(r["size_bytes"])

    # Every touched sector's user data is unchanged: the vanilla bundle
    # writes back exactly what the disc already holds.
    patched = PsxDisc(out)
    original = PsxDisc(ISO_PATH)
    assert patched.read_user_data(gns_lba, 2) == original.read_user_data(gns_lba, 2)
    for r in row["resources"]:
        n = bytes_to_sectors(r["size_padded"])
        assert patched.read_user_data(r["lba"], n) == \
            original.read_user_data(r["lba"], n), r["resource"]


def test_vanilla_apply_is_deterministic(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, 1, 0, name="MAP001.a0")
    out_a, out_b = tmp_path / "a.bin", tmp_path / "b.bin"
    manifest_a, manifest_b = tmp_path / "a.json", tmp_path / "b.json"
    apply(_write_recipe(tmp_path, out_a, manifest_a, bundle, 1, 0,
                        allow_relocate=False))
    apply(_write_recipe(tmp_path, out_b, manifest_b, bundle, 1, 0,
                        allow_relocate=False))
    assert filecmp.cmp(out_a, out_b, shallow=False)


# --------------------------------------------------------------------------
# Positive: in-place shrink (blob fits the existing allocation)
# --------------------------------------------------------------------------

def test_in_place_shrink(tmp_path: Path) -> None:
    # MAP001.15 is 753 bytes in a 2048-byte allocation (GNS length 2048).
    gns_lba, _, gns_raw = _disc_gns(1)
    original_lba = _dir_words(ISO_PATH, 1, "MAP001.15")["lba"]

    disc = PsxDisc(ISO_PATH)
    rec = find_file(disc, "/MAP/MAP001.15;1")
    old_bytes = disc.read_user_data(rec.lba, 1)[: rec.size_bytes]
    new_bytes = old_bytes[:700]

    bundle = _build_bundle(
        tmp_path, 1, 0, name="MAP001.a0",
        blob_overrides={"MAP001.15": new_bytes},
    )
    out = tmp_path / "shrink.bin"
    manifest = tmp_path / "shrink.json"
    apply(_write_recipe(tmp_path, out, manifest, bundle, 1, 0,
                        allow_relocate=False))

    row = _manifest_rows(manifest)[0]
    entry = next(r for r in row["resources"] if r["resource"] == "MAP001.15")
    assert entry["relocated"] is False
    assert entry["lba"] == original_lba
    assert entry["size_bytes"] == 700
    assert entry["size_padded"] == 2048  # allocation unchanged

    # Payload: the new blob, zero-padded to the sector.
    patched = PsxDisc(out)
    sector = patched.read_user_data(original_lba, 1)
    assert sector[:700] == new_bytes
    assert sector[700:] == bytes(2048 - 700)

    # GNS byte-identical: in-place keeps (lba, length); terminators
    # untouched (the last real record belongs to arrangement 1).
    assert patched.read_user_data(gns_lba, bytes_to_sectors(len(gns_raw)))[: len(gns_raw)] == gns_raw

    # Directory record: size poked both-endian, LBA untouched.
    words = _dir_words(out, 1, "MAP001.15")
    assert words["size_le"] == 700 and words["size_be"] == 700
    assert words["lba_le"] == original_lba and words["lba_be"] == original_lba


# --------------------------------------------------------------------------
# Positive: relocation (blob outgrows its allocation)
# --------------------------------------------------------------------------

def _relocate_fixture(tmp_path: Path, *, map_id: int = 1, arrangement: int = 0,
                      resource: str = "MAP001.15", new_size: int = 3000
                      ) -> tuple[Path, int, int, int]:
    """Apply a growing-blob recipe; return (out, manifest, new_lba, rec_index)."""
    disc = PsxDisc(ISO_PATH)
    gns_lba, _, gns_raw = _disc_gns(map_id)
    gns_recs, _ = _parse_gns(gns_raw, "fixture GNS")
    rec = next(
        r for r in gns_recs
        if r.is_real and r.arrangement == arrangement
        and r.lba == _dir_words(ISO_PATH, map_id, resource)["lba"]
    )
    original_lba = rec.lba
    old_bytes = disc.read_user_data(
        original_lba, bytes_to_sectors(_dir_words(ISO_PATH, map_id, resource)["size"])
    )
    new_bytes = (old_bytes + b"\xa5" * 65536)[:new_size]

    bundle = _build_bundle(
        tmp_path, map_id, arrangement,
        name=f"MAP{map_id:03d}.a{arrangement}",
        blob_overrides={resource: new_bytes},
    )
    out = tmp_path / f"rel_{map_id}_{arrangement}.bin"
    manifest = tmp_path / f"rel_{map_id}_{arrangement}.json"
    apply(_write_recipe(tmp_path, out, manifest, bundle, map_id, arrangement,
                        allow_relocate=True))
    return out, manifest, original_lba, rec.index


def test_relocate_grow(tmp_path: Path) -> None:
    out, manifest, original_lba, rec_index = _relocate_fixture(
        tmp_path, map_id=1, arrangement=0, resource="MAP001.15", new_size=3000
    )
    row = _manifest_rows(manifest)[0]
    entry = next(r for r in row["resources"] if r["resource"] == "MAP001.15")
    new_lba = entry["lba"]
    assert entry["relocated"] is True
    assert entry["original_lba"] == original_lba
    assert entry["size_bytes"] == 3000
    assert entry["size_padded"] == 4096
    assert entry["n_sectors"] == 2
    assert new_lba >= 224050 and new_lba < 230000
    assert new_lba != original_lba
    # The other 20 resources stay in place.
    assert sum(1 for r in row["resources"] if r["relocated"]) == 1
    assert all(
        r["lba"] == r["original_lba"] for r in row["resources"]
        if r["resource"] != "MAP001.15"
    )

    gns_lba, _, gns_raw = _disc_gns(1)
    patched = PsxDisc(out)
    fixed_gns = patched.read_user_data(gns_lba, 2)[:len(gns_raw)]
    fixed_recs, _ = _parse_gns(fixed_gns, "patched GNS")
    moved = fixed_recs[rec_index]
    assert (moved.lba, moved.length) == (new_lba, 4096)
    # Terminators (records 40–74) are untouched: the last real record of
    # MAP001.GNS belongs to arrangement 1.
    for term in fixed_recs[40:]:
        assert term.is_padded
        assert (term.lba, term.length) == \
            tuple(struct.unpack_from("<II", gns_raw, 40 * 20 + 8))

    # New payload lives at the new LBA; the old sector is untouched.
    old_bytes = PsxDisc(ISO_PATH).read_user_data(original_lba, 1)
    assert patched.read_user_data(original_lba, 1) == old_bytes

    # Directory record: LBA and size poked both-endian to the new values.
    words = _dir_words(out, 1, "MAP001.15")
    assert words["lba_le"] == new_lba and words["lba_be"] == new_lba
    assert words["size_le"] == 3000 and words["size_be"] == 3000


def test_relocate_apply_is_deterministic(tmp_path: Path) -> None:
    (out_a, manifest_a, _, _) = _relocate_fixture(tmp_path, map_id=1,
                                                  arrangement=0)
    # Second run from a fresh copy of the original ISO.
    bundle = tmp_path / "MAP001.a0"
    out_b = tmp_path / "b.bin"
    manifest_b = tmp_path / "b.json"
    apply(_write_recipe(tmp_path, out_b, manifest_b, bundle, 1, 0,
                        allow_relocate=True))
    assert filecmp.cmp(out_a, out_b, shallow=False)


# --------------------------------------------------------------------------
# Positive: the terminator rule (MAP001 a1, last real record moves)
# --------------------------------------------------------------------------

def test_terminator_fixup(tmp_path: Path) -> None:
    # MAP001.93 is the last real record of MAP001.GNS (record 39) and is
    # followed by 35 type-49 terminators. 4854 -> 7000 bytes (4 sectors >
    # the 3-sector allocation) forces a relocation.
    out, manifest, original_lba, rec_index = _relocate_fixture(
        tmp_path, map_id=1, arrangement=1,
        resource="MAP001.93", new_size=7000,
    )
    assert rec_index == 39
    row = _manifest_rows(manifest)[0]
    entry = next(r for r in row["resources"] if r["resource"] == "MAP001.93")
    new_lba = entry["lba"]
    assert entry["relocated"] is True
    assert entry["size_padded"] == 8192

    gns_lba, _, gns_raw = _disc_gns(1)
    patched = PsxDisc(out)
    fixed_gns = patched.read_user_data(gns_lba, 2)[:len(gns_raw)]
    fixed_recs, _ = _parse_gns(fixed_gns, "patched GNS")
    assert (fixed_recs[39].lba, fixed_recs[39].length) == (new_lba, 8192)
    # Every terminator now echoes the moved record.
    terminators = [r for r in fixed_recs if r.is_padded]
    assert len(terminators) == 35
    for term in terminators:
        assert (term.lba, term.length) == (new_lba, 8192)
    # No arrangement-1 record outside the group changed.
    touched = {39, *[t.index for t in terminators]}
    for rec in fixed_recs:
        if rec.index in touched:
            continue
        assert rec.raw == gns_raw[rec.index * 20:(rec.index + 1) * 20]


# --------------------------------------------------------------------------
# Refusals: every named refusal from spec §1
# --------------------------------------------------------------------------

def test_refuse_map_id_out_of_range(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, 1, 0, name="MAP001.a0")
    with pytest.raises(ValueError, match="out of range"):
        _direct_resolve(tmp_path, {
            "map": 126, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_map_without_gns(tmp_path: Path) -> None:
    # Maps 120–124 hold 0 in the BATTLE.BIN table (the game's bail-out).
    bundle = _build_bundle(tmp_path, 1, 0, name="MAP001.a0")
    with pytest.raises(ValueError, match="has no GNS"):
        _direct_resolve(tmp_path, {
            "map": 121, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_arrangement_without_records(tmp_path: Path) -> None:
    # MAP000's GNS has real records only for arrangements 0 and 1.
    bundle = _build_bundle(tmp_path, 0, 0, name="MAP000.a0")
    with pytest.raises(ValueError, match="nothing\nto patch|no real"):
        _direct_resolve(tmp_path, {
            "map": 0, "arrangement": 2, "file": str(bundle),
        })


def test_refuse_orphan_blob(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, 1, 0, name="MAP001.a0")
    (bundle / "MAP001.99").write_bytes(b"orphan")
    with pytest.raises(ValueError, match="orphan"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_missing_blob(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, 1, 0, name="MAP001.a0")
    (bundle / "MAP001.15").unlink()
    with pytest.raises(FileNotFoundError, match="no MAP001\\.15 blob"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_gns_size_mismatch(tmp_path: Path) -> None:
    # Same record region, opaque tail extended by 8 non-zero bytes: the
    # disc-size check must refuse.
    bundle = _build_bundle(
        tmp_path, 1, 0, name="MAP001.a0",
        gns_overrides=_disc_gns(1)[2] + b"\xbb" * 8,
    )
    with pytest.raises(ValueError, match="written back in place"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_record_count_mismatch(tmp_path: Path) -> None:
    # Same total size (2388), one extra valid record, correspondingly
    # shorter non-zero opaque tail: the record-count invariant refuses.
    _, _, gns_raw = _disc_gns(1)
    recs, _ = _parse_gns(gns_raw, "disc")
    n_new = len(recs) + 1
    new_gns = b"".join(r.raw for r in recs) + recs[39].raw + b"\xaa" * (len(gns_raw) - n_new * 20)
    assert len(new_gns) == len(gns_raw)
    bundle = _build_bundle(
        tmp_path, 1, 0, name="MAP001.a0", gns_overrides=new_gns
    )
    with pytest.raises(ValueError, match="record count is invariant"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_wrong_placement_authority(tmp_path: Path) -> None:
    _, _, gns_raw = _disc_gns(1)
    broken = bytearray(gns_raw)
    # Record 0 (arrangement 0) carries an LBA the disc GNS does not say.
    lba, _ = struct.unpack_from("<II", broken, 0 * 20 + 8)
    struct.pack_into("<I", broken, 0 * 20 + 8, lba + 1)
    bundle = _build_bundle(
        tmp_path, 1, 0, name="MAP001.a0", gns_overrides=bytes(broken)
    )
    with pytest.raises(ValueError, match="the disc is the placement authority"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_non_verbatim_foreign_record(tmp_path: Path) -> None:
    _, _, gns_raw = _disc_gns(1)
    broken = bytearray(gns_raw)
    # Record 50 is an arrangement-1 real record (or a terminator); either
    # way it is "every other record" for an a0 entry and must be verbatim.
    broken[50 * 20 + 3] ^= 0xFF
    bundle = _build_bundle(
        tmp_path, 1, 0, name="MAP001.a0", gns_overrides=bytes(broken)
    )
    with pytest.raises(ValueError, match="carried verbatim|record 50"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_tail_tamper(tmp_path: Path) -> None:
    _, _, gns_raw = _disc_gns(1)
    broken = bytearray(gns_raw)
    broken[2000] ^= 0xFF  # inside the opaque tail (records end at 1500)
    bundle = _build_bundle(
        tmp_path, 1, 0, name="MAP001.a0", gns_overrides=bytes(broken)
    )
    with pytest.raises(ValueError, match="tail"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_grow_without_allow_relocate(tmp_path: Path) -> None:
    disc = PsxDisc(ISO_PATH)
    rec = find_file(disc, "/MAP/MAP001.15;1")
    old = disc.read_user_data(rec.lba, 1)[: rec.size_bytes]
    bundle = _build_bundle(
        tmp_path, 1, 0, name="MAP001.a0",
        blob_overrides={"MAP001.15": old + b"\xa5" * 2000},
    )
    with pytest.raises(ValueError, match="allow_relocate=true"):
        _direct_resolve(tmp_path, {
            "map": 1, "arrangement": 0, "file": str(bundle),
        })


def test_refuse_two_entries_one_gns(tmp_path: Path) -> None:
    # Spec §6: one [[patches.map]] per GNS per recipe. Two entries for the
    # same map both write the GNS sector and must conflict loudly.
    a0 = _build_bundle(tmp_path, 1, 0, name="MAP001.a0")
    a1 = _build_bundle(tmp_path, 1, 1, name="MAP001.a1")
    out = tmp_path / "both.bin"
    manifest = tmp_path / "both.json"
    recipe = _write_recipe(
        tmp_path, out, manifest, a0, 1, 0, allow_relocate=False,
        extra_map_entries=[(a1, 1, 1)],
    )
    with pytest.raises(ValueError, match="conflict at LBA"):
        apply(recipe)


# --------------------------------------------------------------------------
# §4 summary line
# --------------------------------------------------------------------------

def test_summary_line() -> None:
    row = {
        "map": 42,
        "arrangement": 0,
        "gns": {"lba": 99137, "size_bytes": 668},
        "resources": [
            {"resource": "MAP042.11", "lba": 224103, "relocated": True},
            {"resource": "MAP042.15", "lba": 224108, "relocated": True},
            {"resource": "MAP042.13", "lba": 88211, "relocated": False},
        ],
    }
    assert summary_line(row) == (
        "MAP042 a0: gns@99137, 3 resources, 2 relocated "
        "(MAP042.11 -> 224103, MAP042.15 -> 224108)"
    )
    assert summary_line({**row, "resources": [row["resources"][2]]}) == (
        "MAP042 a0: gns@99137, 1 resources"
    )

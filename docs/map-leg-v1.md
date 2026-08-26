# Patcher map leg — surface spec, v1

Design record for the map leg of `fft-iso-patcher`, resolved by
[The patcher map leg's surface](https://github.com/timbermania/fft-monorepo/issues/522) on
[Executing ADR-0004: dump, build, the Blender addon, and the patcher map leg](https://github.com/timbermania/fft-monorepo/issues/517).
What it pins: the bundle input layout, the placement mechanism (in-place vs relocate,
GNS fixup, ISO9660 directory-record pokes), the manifest schema, the `allow_relocate`
surface, and the CLI-only interaction surface.

The build side of this seam is the
[#372](https://github.com/timbermania/fft-monorepo/issues/372) patcher contract: `build`
emits opaque resource blobs + a GNS with the original LBAs verbatim and never sees a
disc; the patcher owns placement and the GNS `(lba, length)` fixup. The interchange
document family (`exmateria-map/docs/interchange-*-v1.md`) covers the addon ⇄ build
document format; this document covers build ⇄ patcher. Disc-level facts come from
[`research/working_documents/MAP_RESOURCE_TO_DISC_DELIVERY.md`](../../research/working_documents/MAP_RESOURCE_TO_DISC_DELIVERY.md)
(#361, all [V]-verified). The music leg is the implementation precedent:
`fft_iso_patcher/assets/music.py`, `manifest.py`, `free_space.py`, `patcher.py`.

## 1. Input layout

### 1.1 Recipe entry

One `[[patches.map]]` entry per (map, arrangement). Paths resolve relative to the
recipe file:

```toml
[[patches.map]]
map = 42                 # map id 0–125 (BATTLE.BIN table index)
arrangement = 0          # GNS record byte 2
file = "maps/MAP042.a0"  # directory bundle (§1.2)
allow_relocate = false   # default; §4
```

`[patches.<kind>]` loading is generic (`recipe.py`), so the loader is unchanged.
`[free_space].ranges` + `reserved_for_shishi` are reused as-is from the music leg.

### 1.2 Bundle directory

`build`'s output for one (map, arrangement) — a directory `MAP<nnn>.a<arr>/` holding:

- `MAP<nnn>.GNS` — the full GNS content: this arrangement's records rebuilt, every
  other record carried verbatim (byte-identical to the disc).
- One blob per resource this arrangement references, named by disc filename without the
  `;1` version suffix (`MAP042.11`). Blob bytes = the new resource bytes.

### 1.3 Ingest and verification

The patcher pairs records to blobs through the record's own `(lba, length)` — not by
filename or row order: the record's LBA identifies the resource's ISO9660 directory
record under `/MAP`, and that record's name (minus `;1`) names the blob. One pass over
the `/MAP` directory listing gives the LBA → (name, byte size) index.

Every entry is verified before any patch is emitted; every failure is a named refusal:

1. **Map id in range and the map has a GNS.** The BATTLE.BIN table entry for the id is
   non-zero (maps 120–124 hold `0` on the vanilla disc — the game's own bail-out).
2. **Table and directory agree.** The BATTLE.BIN table LBA equals the ISO9660
   directory-record LBA of `MAP<nnn>.GNS;1` (121/121 verified on the vanilla disc).
   Divergence refuses — the game reads the table, the pokes target the directory tree.
3. **GNS record count is invariant.** Bundle record count == disc record count. The GNS
   is written back in place at its original size (§2.5), so structural edits
   (adding/dropping resources) are out of scope for this leg.
4. **Verbatim cross-check.** For every record of the bundle GNS:
   - this arrangement's records: `(lba, length)` must equal the disc GNS's value (the
     disc is the placement authority; the bundle carries the originals verbatim);
   - all other records: all 20 bytes must equal the disc GNS's record.

   Mismatch refuses. The common cause is applying a second arrangement's bundle after
   the first already patched this GNS (§6: re-dump from the patched ISO, rebuild).
5. **Record ↔ blob pairing is bijective.** Every real record of this arrangement
   (byte 2 == the entry's arrangement, type ≠ 49) has a blob named by its record's
   directory-record name, and its LBA resolves to a `/MAP` directory record whose size
   agrees with the GNS length's 2048-padding (2,987/2,987 verified); no orphan blobs.
   Records sharing an LBA (a resource file referenced by several records) form one
   group: one blob, one placement, every record in the group fixed up identically.
   (The vanilla corpus is a 1,454-record ↔ 1,454-file bijection — this is a
   robustness rule, not a corpus fact.) An entry whose arrangement has no real
   records refuses: there is nothing to patch.
6. **GNS shape sanity.** Header tag ∈ {`0x22`, `0x30`, `0x70`} and sentinel
   `55 66 77 88` on every record; every type-49 (PADDED terminator) record echoes the
   last real record's `(lba, length)` verbatim (1,533/1,533 verified) — the
   terminator rule in §2.3 depends on it.

## 2. Placement mechanism

### 2.1 Authority split (per GNS record field)

| field | this arrangement | all other records |
|---|---|---|
| `(lba, length)` (offsets 8–15) | **disc** (placement authority), rewritten with the placement decision | disc, carried verbatim |
| everything else (tag, arrangement, time/weather, type, `0x3333`, sentinel) | **bundle** (build is the authority on art-facing fields) | disc, byte-identical (verified, check 4) |

### 2.2 Per-resource placement

For each distinct original LBA of this arrangement, in GNS row order, the new blob is
placed by the music leg's rule:

- `new_n = ceil(blob_bytes / 2048)`, `have_n = original_gns_length // 2048` — the GNS
  length field is a 2048 multiple, the same unit as the SCUS music table and the
  allocator's `USER_DATA_SIZE`.
- **In-place** when `new_n <= have_n`: payload written at the original LBA, GNS length
  unchanged (a resource may grow to the end of its last sector with no GNS edit).
- **Relocate** when `new_n > have_n` and `allow_relocate`: allocated from
  `[free_space].ranges` (Shishi's `[219250, 224050)` subtracted), first-fit from the
  lowest range (deterministic re-runs), reservation key
  `map_{map:03d}a{arrangement}_{resource}`.
- **Refuse** when `new_n > have_n` and not `allow_relocate`:
  `MAP042 a0 MAP042.11 has a 3-sector (6144-byte) allocation; new blob is 7530 bytes
  (4 sectors). Set allow_relocate=true and add a [free_space].ranges entry.`

Surveyed free space (#361): 12,688 sectors on the vanilla disc; Shishi reserves
`[219250, 224050)`; largest contiguous run is 5,950 sectors at `[224050, 230000)`,
plus 558 at `[56442, 57000)`. `_verify_free_space_unoccupied` still guards declared
ranges against live extents.

### 2.3 GNS fixup and the terminator rule

Take the bundle GNS bytes; rewrite this arrangement's record `(lba, length)` fields to
the placement decisions; handle type-49 terminators:

- Let `L` be the last real (non-49) record in GNS row order.
- If `L` belongs to this arrangement: rewrite `L` **and every terminator record** to
  `L`'s new `(lba, length)` — terminators echo `L` verbatim, so moving or resizing the
  map's last resource otherwise leaves every terminator stale (`MAP001.GNS` alone
  carries 35 of them).
- Otherwise terminators are untouched: they echo a record this entry did not change.

### 2.4 ISO9660 directory-record pokes

For each resource whose placement changed its LBA **or** its byte size, poke its
directory record — only the changed words, both-endian. The game never reads these;
`fft-iso-patcher extract`, CDMage, and any future dump-from-patched-ISO do:

- LBA little-endian at record `+2`, big-endian at `+6`;
- size little-endian at `+10`, big-endian at `+14`;
- 4 bytes per poke, into the sector containing the record (records do not cross sector
  boundaries; refuse if a poke would, as the music table-entry case does).

`iso9660.py` currently reads only the little-endian halves — the pokes write both. The
GNS's own directory record is never poked (same LBA, same size).

### 2.5 What never changes

- **BATTLE.BIN** — the GNS never moves (record-count invariant ⇒ size invariant ⇒
  always in-place), so the GNS LBA table is untouched.
- **The GNS's on-disc position and size** — the fixed-up bundle GNS (original size,
  ≤ 4,096 bytes: the game's read window is the hard-coded immediate `4096` at
  `0x800F369C`) is written back to the original LBA, one sector patch per 2,048-byte
  sector (at most 2).

## 3. Manifest schema

One placement row per `[[patches.map]]` entry — nested, not one row per resource:
1:1 with the recipe entry, and the GNS + its resources stay one atomic patch. A
per-resource view is a one-line flatten.

```json
{
  "kind": "map",
  "map": 42,
  "arrangement": 0,
  "source": "/abs/.../MAP042.a0",
  "gns": {"lba": 99137, "size_bytes": 2388},
  "resources": [
    {"resource": "MAP042.11", "lba": 88211, "n_sectors": 5,
     "size_bytes": 9843, "size_padded": 10240, "relocated": false,
     "original_lba": 88211, "original_size_padded": 10240}
  ]
}
```

- `source` = resolved bundle directory (music records the resolved input file).
- `gns` carries no relocation fields: the GNS cannot move (§2.5). `lba` is recorded for
  audit; `size_bytes` is the directory-record size.
- `resources[]` mirrors the music row's field names exactly; `original_lba` /
  `original_size_padded` are always set — what the GNS record pointed at before
  (music's convention).
- `n_sectors` / `size_padded` are in 2,048-byte units.
- The manifest envelope is unchanged (`schema_version` stays 1).

## 4. `allow_relocate` and the note surface

- **Recipe surface:** a key on `[[patches.map]]`, default `false` (mirrors music).
  Relocation additionally requires `[free_space].ranges`; without them, an oversized
  blob is the hard error of §2.2.
- **Patcher-side surface — both:**
  - *manifest:* `relocated` + `original_lba` / `original_size_padded` per resource;
  - *apply log:* the summary line names relocated resources —
    `MAP042 a0: gns@99137, 20 resources, 2 relocated (MAP042.11 -> 224103, MAP042.15 -> 224108)`.
- **Build-side surface:** event-only note when a blob's byte size differs from the
  original (`MAP042.11 grew 9843 -> 12000 bytes; the patcher will need
  allow_relocate=true plus free-space ranges`), per
  [#368](https://github.com/timbermania/fft-monorepo/issues/368). The build never blocks
  on it; placement authority stays with the patcher.

## 5. Interaction surface: CLI-only

`[[patches.map]]` in a recipe TOML + a registered `resolve_map` handler is the whole
surface: no new subcommand, no new flags — `apply` already dispatches on `kind`,
mirroring `@register(PatchKind.MUSIC.value)`. The natural loop is already CLI:
`dump → edit in Blender → exmateria-map build → fft-iso-patcher apply --recipe`.

- The apply log prints the §4 summary line for map rows instead of the raw dict (a
  resource list would be a wall of text).
- Verification stays CLI-shaped: `inspect`, `extract` from the patched ISO,
  round-trip `cmp`.
- The TUI's slots/review screens are shaped for music's "pick a file per slot"
  (per-slot pickers, `fits_in_place`); a build-generated bundle directory gives the
  picker little to offer. A TUI map screen, if ever wanted, is a follow-up ticket,
  not part of this leg.

## 6. Multiple arrangements of one map

One `[[patches.map]]` entry per GNS per recipe: two entries for the same map both write
the GNS, so `patcher._detect_conflicts` refuses (overlapping GNS sector patches, the
labels naming the colliding entries).

The verbatim cross-check has a consequence: after arrangement A is patched, a bundle
for arrangement B of the same map built from the old GNS fails check 4 (arrangement A's
records no longer match the disc). The loop is **per (map, arrangement)** —
`dump → build → apply`, with the re-dump taken from the patched ISO when a second
arrangement is patched. This is why the bundle is per (map, arrangement) at all.

## 7. Implementation notes (delta against existing code)

| file | change |
|---|---|
| `assets/kinds.py` | `MAP = "map"` |
| `assets/map.py` (new) | `resolve_map` — the §1–§4 mechanism. The module name shadows the built-in `map`; follow the music import-alias convention |
| `patcher.py` | one-line import to register the handler (the `_music` pattern) |
| `iso9660.py` | (1) expose the record position (containing directory LBA + in-sector offset) — the walker already computes it; needed for the §2.4 pokes; (2) a `/MAP` LBA → record index (one listing pass) |
| `cli.py` | kind-aware apply-log printing (§5) |
| `README.md` | `patches.map` row, out of *Planned* |

No change to `recipe.py` (generic `[patches.<kind>]`), `manifest.py` (rows are opaque
dicts), `free_space.py` (keys are opaque), or `byte_patch.py`.

## References

- [#372](https://github.com/timbermania/fft-monorepo/issues/372) — the patcher contract
  (build never sees a disc; placement + fixup is the patcher's; `allow_relocate`
  defaults to `False`; in-place survives as a requestable guarantee — fail rather than
  relocate).
- [#368](https://github.com/timbermania/fft-monorepo/issues/368) — the
  outgrows-allocation note is event-only, build-side, and stays out of the interchange
  document.
- [#525](https://github.com/timbermania/fft-monorepo/issues/525) — disposition of GNS
  pad rows (type 49) under ADR-0004; the interchange-side view. This document's §2.3
  is the disc-side view of the same records.
- `exmateria-map/docs/interchange-{schema,import,export}-v1.md` — the addon ⇄ build
  document format this leg consumes.
- `research/working_documents/MAP_RESOURCE_TO_DISC_DELIVERY.md` — #361: the BATTLE.BIN
  GNS LBA table (file offset `0x8EC74`, LBA 1285 + byte 1140, 126 × u32 LE, the game's
  single-instruction read at `FUN_800F3638`), the 20-byte GNS record layout, the
  2,987-record / 1,454-file bijection, the terminator echo, the 2,048 length padding
  (2,987/2,987), the both-endian directory-record layout, and the free-space survey.
- Music leg — `fft_iso_patcher/assets/music.py` (in-place vs relocate, table-entry
  pokes, manifest row), `manifest.py`, `free_space.py`, `patcher.py` (conflict
  detection, free-space guard), `docs/iso_patching.md` (music-era findings).

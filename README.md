# fft-iso-patcher

Patch a PSX *Final Fantasy Tactics* ISO. Replace music slots, in either a
guided TUI or with a hand-written TOML recipe; deterministic re-runs
produce byte-identical output ISOs. Sprite, effect, byte, and ASM patch
kinds are planned.

This is also the **gateway tool** for the rest of the ExMateria family
([DAW Plugin](https://github.com/timbermania/ExMateria-DAW-Plugin),
[SPU Core](https://github.com/timbermania/ExMateria-SPU-Core)) — its
`fft-iso-patcher extract` command produces the disc dump those tools auto-discover.

## Quick install (Windows, end-to-end)

If you want the whole ExMateria stack on a Windows machine — patcher,
extractor, **and** the DAW plugin installed into your VST3 folder — run
this from a regular PowerShell window (no admin needed):

```powershell
iwr -useb https://raw.githubusercontent.com/timbermania/ExMateria-ISO-Patcher/main/scripts/install_exmateria.ps1 -OutFile install_exmateria.ps1
powershell -ExecutionPolicy Bypass -File .\install_exmateria.ps1 -IsoPath "C:\path\to\Final Fantasy Tactics.bin"
```

That installs uv, uv-installs the patcher wheel, extracts your disc, and
downloads the latest prebuilt `.vst3` from
[ExMateria-DAW-Plugin Releases](https://github.com/timbermania/ExMateria-DAW-Plugin/releases)
into your per-user VST3 folder. **No build tools required** — uses
prebuilt artifacts from GitHub Releases. Re-runnable. Pass `-SkipPlugin`
if you only want the patcher and not the plugin.

If you'd rather build everything from source (slower, requires CMake +
Visual Studio Build Tools), use the parallel script
`install_exmateria_from_source.ps1`.

For everything else (Linux, macOS, manual install), follow the steps below.

## Install

[uv](https://docs.astral.sh/uv/) is the recommended way to install:

```bash
# Install once, get a `fft-iso-patcher` script on PATH:
uv tool install .

# Or run from the source tree without installing globally:
uv run python -m fft_iso_patcher tui
```

`uv tool install` puts everything in an isolated venv; `uv run` creates
`.venv/` in the source tree and uses it. Either way, the `textual`
runtime dep gets pulled in for you.

If you don't have uv:
[uv install instructions](https://docs.astral.sh/uv/#installation).

### No-Python single .exe (Windows)

If you don't want Python on your machine at all, the
[Releases page](https://github.com/timbermania/ExMateria-ISO-Patcher/releases)
ships a standalone `fft-iso-patcher.exe`
built with PyInstaller. Download, drop it somewhere on PATH, and run.
No uv, no pip, no Python install needed.

## Extract the disc once (for other ExMateria tools)

Before you can use the
[ExMateria DAW Plugin](https://github.com/timbermania/ExMateria-DAW-Plugin)
(or any future ExMateria audio tool), extract the FFT disc tree to the
standard location:

```bash
fft-iso-patcher extract path/to/Final\ Fantasy\ Tactics.bin
```

That writes a complete dump of the disc's filesystem (`SOUND/`,
`EFFECT/`, `BATTLE.BIN`, etc.) into:

| OS | Path |
|----|------|
| Linux / BSD | `~/.local/share/exmateria/assets/` |
| macOS | `~/Library/Application Support/exmateria/assets/` |
| Windows | `%APPDATA%\exmateria\assets\` |

Run it once. Other ExMateria tools auto-discover this location — no env
vars or config required. To override, set `EXMATERIA_ASSETS_DIR=...` or
pass `--out` to `fft-iso-patcher extract`.

## TUI

```bash
fft-iso-patcher tui      # if installed via `uv tool install`
# or
uv run python -m fft_iso_patcher tui
```

A four-screen guided flow: pick your vanilla (or already-patched) ISO →
browse the 100 music slots and assign replacement `.smd` files →
review/confirm output paths → apply. The TUI runs the surveyor for you,
auto-relocates oversized replacements into existing free space on the
disc, and writes a recipe TOML alongside the patched ISO so the run is
reproducible.

Crash dumps land in `~/.cache/fft_iso_patcher/tui_crash.log` (override
with `FFT_TUI_CRASH_LOG=/path/to/file`).

## CLI

```bash
fft-iso-patcher apply --recipe recipe.toml
fft-iso-patcher inspect --iso path/to/iso.bin
```

`apply` runs a recipe; `inspect` prints the music LBA table. Both are
also reachable as `python -m fft_iso_patcher <subcommand>`.

## Recipe TOML

The recipe is the source of truth — a plain TOML file you can author by
hand or have the TUI emit. Re-running the same recipe against the same
input produces a byte-identical output ISO.

```toml
schema_version = 1

[input]
iso = "Final Fantasy Tactics.bin"

[output]
iso = "Final Fantasy Tactics-patched.bin"
manifest = "Final Fantasy Tactics-patched.manifest.json"   # optional

# Sectors the patcher may use for relocation. Get these from the
# bundled surveyor: `python scripts/survey_free_space.py path/to/iso.bin`.
[free_space]
ranges = [[224050, 230000]]
reserved_for_shishi = [219250, 224050]

[[patches.music]]
slot = 41
file = "aerith.smd"
allow_relocate = true   # required if the new SMD is bigger than the slot
```

The accompanying manifest JSON records *what actually happened* —
resolved LBAs, sector counts, whether each slot landed in-place or got
relocated.

## Asset kinds

| Kind | Status | Description |
|------|--------|-------------|
| `patches.music`   | Implemented (in-place + relocation) | Replace `MUSIC_##.SMD`. Engine cap 20480 bytes per file. |
| `patches.byte`    | Planned | Raw `(sector, offset, bytes)` write. |
| `patches.sprite`  | Planned | Replace battle character sprite. |
| `patches.effect`  | Planned | Replace `E###.BIN` effect file. |
| `patches.asm`     | Planned | RAM-address ASM patch (mapped to ISO offset). |

Free-space relocation already works for music; future kinds will plug
into the same allocator.

## Architecture

```
fft_iso_patcher/
├── __init__.py            # Public API (apply, Recipe, PatchKind, ...)
├── cli.py                 # argparse entry point
├── constants.py           # FFT magic numbers (MUSIC_TABLE_OFFSET, ...)
├── iso_sectors.py         # Mode 2 Form 1 sector R/W + EDC/ECC
├── iso9660.py             # Directory walker (find_file)
├── iso_utils.py           # Sector arithmetic helpers
├── recipe.py              # TOML loader
├── recipe_build.py        # Programmatic Recipe builder + TOML writer
├── manifest.py            # Derived JSON output
├── free_space.py          # Sector range allocator
├── free_space_survey.py   # Read-only disc surveyor
├── patcher.py             # Pipeline orchestration
├── assets/
│   ├── kinds.py           # PatchKind enum
│   ├── byte_patch.py      # (lba, offset, bytes) write primitive
│   └── music.py           # SCUS_942.21:0x37880 music-table handler
└── tui/                   # Textual TUI
    ├── app.py
    ├── paths.py           # WSL/Windows path normalization
    ├── state.py
    └── screens/           # load, slots, review, apply
```

## Tests

```bash
uv run pytest -q
```

20 tests; about half need a real Final Fantasy Tactics BIN at
`./Final Fantasy Tactics.bin` (override with `FFT_ISO=/path/to/iso.bin`).
Without a real ISO they skip cleanly.

## License

GPL-3.0-or-later. EDC/ECC implementation is ported from FFTPatcher's
`IsoPatch.cs` (GPL v3+); the canonical algorithm reference is
pcsx-redux's `iec-60908b/edcecc.c` (MIT).

#!/usr/bin/env python3
"""Survey an FFT PSX BIN for free LBA ranges suitable for music relocation.

Read-only — never writes to the disc. Thin CLI wrapper around
`fft_iso_patcher.free_space_survey.survey()`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from fft_iso_patcher.free_space_survey import survey  # noqa: E402
from fft_iso_patcher.iso_sectors import PsxDisc, SECTOR_SIZE, USER_DATA_SIZE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path, help="path to the FFT PSX BIN")
    parser.add_argument(
        "--min-gap",
        type=int,
        default=64,
        help="hide gaps smaller than this many sectors (default 64)",
    )
    args = parser.parse_args()

    iso_path: Path = args.iso
    if not iso_path.exists():
        print(f"ERROR: {iso_path} not found", file=sys.stderr)
        return 1

    disc = PsxDisc(iso_path)
    report = survey(disc, min_gap=args.min_gap)

    print(f"Disc: {report.iso_path}")
    print(
        f"  total sectors: {report.total_sectors}  "
        f"(= {report.total_sectors * SECTOR_SIZE} bytes)\n"
    )

    print("Music table extents (top 5 by LBA):")
    sorted_music = sorted(report.music_extents, key=lambda e: e.lba)
    music_last = (
        max(report.music_extents, key=lambda e: e.end) if report.music_extents else None
    )
    for e in sorted_music[:5]:
        print(f"  {e.label:>10}: lba={e.lba:>6}  n_sectors={e.n_sectors:>2}")
    print(f"  ... ({len(report.music_extents)} total)")
    if music_last:
        print(f"  highest music end: LBA {music_last.end} ({music_last.label})\n")

    shishi_start, shishi_end = report.shishi_reservation
    print(
        f"Filesystem extents in window "
        f"[{music_last.end if music_last else 0}, {shishi_start}):"
    )
    for e in sorted(report.fs_extents, key=lambda e: e.lba):
        if music_last and e.lba < music_last.end:
            continue
        if e.lba >= shishi_start:
            continue
        print(f"  {e.label:<40} lba={e.lba:>6}  n_sectors={e.n_sectors:>5}")

    print(
        f"\nFree ranges (after carving Shishi reservation "
        f"[{shishi_start}, {shishi_end}), min size {args.min_gap}):"
    )
    candidates = report.candidates
    for s, e in candidates:
        print(
            f"  [{s:>6}, {e:>6})  length={e - s:>6} sectors  "
            f"({(e - s) * USER_DATA_SIZE} payload bytes)"
        )
    if not candidates:
        print("  (none)")
        return 2

    biggest = report.largest
    assert biggest is not None
    print(
        f"\nLargest free range: [{biggest[0]}, {biggest[1]})  "
        f"= {biggest[1] - biggest[0]} sectors  "
        f"({(biggest[1] - biggest[0]) * USER_DATA_SIZE} payload bytes)"
    )
    print("Recommended TOML:")
    print(f"  [free_space]")
    print(f"  ranges = [[{biggest[0]}, {biggest[1]}]]")
    print(f"  reserved_for_shishi = [{shishi_start}, {shishi_end}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Single home for FFT-specific magic numbers.

The patcher core (`patcher.py`, `iso9660.py`, `iso_sectors.py`) is generic
ISO9660 / Mode-2-Form-1 plumbing. FFT-specific layout — where the music
LBA table lives in SCUS_942.21, how many slots there are, the engine's
SMD load-size cap — belongs here so future asset handlers can import the
same values instead of re-deriving them.
"""

from __future__ import annotations

# Byte offset of the music slot table inside SCUS_942.21. Each entry is
# 8 bytes: <u32 lba, u32 size_bytes_padded_to_2048>. There are 100 slots.
MUSIC_TABLE_OFFSET = 0x37880

# Number of music slots in the FFT engine.
N_MUSIC_SLOTS = 100

# Hard cap on SMD load size enforced by the FFT engine. Binary-searched
# 2026-05-03 via the patcher: a 10-sector / 20480-byte custom SMD plays
# (matches MUSIC_99's vanilla padded allocation), a 13-sector / 26624-byte
# custom SMD silences the data screen. Mirrors the C++ side
# (FFTSmdGameCompileBudget::engine_max_bytes). Hand-built or third-party
# SMDs above this fail to play, so reject them at the patcher boundary
# rather than emit silent ISOs.
ENGINE_MAX_SMD_BYTES = 20480

# Path inside the FFT ISO to the SCUS that holds the music table.
SCUS_PATH = "/SCUS_942.21;1"

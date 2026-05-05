"""Locate test assets without baking in any user-specific path.

Resolution order:
  1. ``EXMATERIA_ASSETS_DIR`` env var (points at an extracted disc tree).
  2. ``FFT_ISO`` env var (an explicit ISO path).
  3. Standard exmateria assets dir (populated by ``exmateria-extract``).
  4. Walk up from this file looking for ``project-assets/`` — works inside
     the monorepo, fails cleanly anywhere else.

Tests skip when nothing resolves; this file is published to the public
repo unchanged because it contains no machine-specific paths.
"""

from __future__ import annotations

import os
from pathlib import Path

from fft_iso_patcher.asset_dirs import standard_assets_dir


def _walk_up_to_project_assets() -> Path | None:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "project-assets"
        if candidate.is_dir():
            return candidate
    return None


def assets_root() -> Path | None:
    """Return a directory containing the extracted disc tree, or ``None``."""
    env_dir = os.environ.get("EXMATERIA_ASSETS_DIR")
    if env_dir:
        return Path(env_dir)
    standard = standard_assets_dir()
    if standard.is_dir() and (standard / "SOUND").is_dir():
        return standard
    monorepo = _walk_up_to_project_assets()
    if monorepo is not None:
        # Inside the monorepo, the dump lives at project-assets/fft-extract.
        if (monorepo / "fft-extract").is_dir():
            return monorepo / "fft-extract"
        return monorepo
    return None


_ISO_SENTINEL = Path("/__exmateria_iso_not_found__")


def iso_path() -> Path:
    """Return the test ISO. ``_ISO_SENTINEL`` (a guaranteed-nonexistent
    absolute path) if not discoverable — caller's ``.exists()`` skipif
    guard then fires."""
    explicit = os.environ.get("FFT_ISO")
    if explicit:
        return Path(explicit)
    monorepo = _walk_up_to_project_assets()
    if monorepo is None:
        return _ISO_SENTINEL
    return monorepo / "Final Fantasy Tactics.bin"


ISO_PATH = iso_path()

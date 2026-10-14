"""Deterministic per-cell scatter for view-only decoration (sparse glyphs, sea sparkle, clutter).

A uniform pseudo-random value in [0, 1) keyed on the absolute world tile (and, at the detail scales, the cell
inside that tile) plus a salt, so decoration is stable while the camera pans and never touches the world's own
random streams. The salt comes from ``rng.derive_int(seed, "render", ...)``, never from builtin ``hash()``.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def scatter01(
    salt: int,
    tile_x: np.ndarray,
    tile_y: np.ndarray,
    sub_x: Optional[np.ndarray] = None,
    sub_y: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Return a uniform value in [0, 1) per ``(tile_x, tile_y)`` and optional sub-cell, via a SplitMix64-style mix.

    ``sub_x`` / ``sub_y`` are the index of the cell inside its tile's block; all zeros (or omitted) reproduces the
    tile-only value, so the map scale is unchanged by the detail scales' extra key.
    """
    with np.errstate(over="ignore"):
        h = tile_x.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
        h ^= tile_y.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
        if sub_x is not None:
            h ^= sub_x.astype(np.uint64) * np.uint64(0x165667B19E3779F9)
        if sub_y is not None:
            h ^= sub_y.astype(np.uint64) * np.uint64(0x27D4EB2F165667C5)
        h ^= np.uint64(int(salt) & 0xFFFFFFFFFFFFFFFF)
        h ^= h >> np.uint64(30)
        h *= np.uint64(0xBF58476D1CE4E5B9)
        h ^= h >> np.uint64(27)
        h *= np.uint64(0x94D049BB133111EB)
        h ^= h >> np.uint64(31)
    return (h >> np.uint64(11)).astype(np.float64) * (1.0 / float(1 << 53))

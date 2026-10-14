"""Deterministic per-cell scatter for view-only decoration (sparse glyphs, sea sparkle).

A uniform pseudo-random value in [0, 1) keyed on the absolute world tile plus a salt, so decoration is
stable while the camera pans and never touches the world's own random streams. The salt comes from
``rng.derive_int(seed, "render", ...)``, never from builtin ``hash()``.
"""

from __future__ import annotations

import numpy as np


def scatter01(salt: int, tile_x: np.ndarray, tile_y: np.ndarray) -> np.ndarray:
    """Return a uniform value in [0, 1) per ``(tile_x, tile_y)``, using a SplitMix64-style integer mix."""
    with np.errstate(over="ignore"):
        h = tile_x.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
        h ^= tile_y.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
        h ^= np.uint64(int(salt) & 0xFFFFFFFFFFFFFFFF)
        h ^= h >> np.uint64(30)
        h *= np.uint64(0xBF58476D1CE4E5B9)
        h ^= h >> np.uint64(27)
        h *= np.uint64(0x94D049BB133111EB)
        h ^= h >> np.uint64(31)
    return (h >> np.uint64(11)).astype(np.float64) * (1.0 / float(1 << 53))

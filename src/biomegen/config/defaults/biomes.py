"""Defaults for the ``biomes`` section (biomes)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "classifier": "whittaker",
    # Elevation/water override thresholds (normalised elevation).
    "beach_max": 0.45,  # land at/below this AND next to ocean becomes beach
    "beach_dist": 2.0,  # max distance-to-ocean (tiles) for a tile to be eligible for beach
    "mountain_min": 0.76,  # bare rock above this
    "snow_min": 0.88,  # permanent snow above this
    "snow_temp": 0.18,  # ...or below this temperature at high-ish elevation
    "smooth_passes": 1,  # majority-vote de-speckle passes (0 disables)
    # Band edges that split the normalised temperature/moisture axes into rows/cols of the matrix.
    "temp_bands": [0.20, 0.40, 0.60, 0.80],  # -> 5 temperature bands (cold..hot)
    "moisture_bands": [0.22, 0.38, 0.52, 0.67, 0.83],  # -> 6 moisture bands (dry..wet)
    # Whittaker lookup: matrix[temp_band][moisture_band] -> biome name.
    # Rows are temperature cold->hot; columns are moisture dry->wet.
    "matrix": [
        ["tundra", "tundra", "taiga", "taiga", "taiga", "taiga"],  # coldest
        ["shrubland", "grassland", "taiga", "forest", "forest", "forest"],  # cool
        ["grassland", "grassland", "forest", "forest", "forest", "swamp"],  # temperate
        ["desert", "savanna", "grassland", "forest", "jungle", "jungle"],  # warm
        ["desert", "savanna", "savanna", "jungle", "jungle", "jungle"],  # hottest
    ],
}

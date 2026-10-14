"""Defaults for the ``poi`` section (POIs (placement + per-type rules))."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "sampler": "bluenoise",  # "bluenoise" (default), "random", or "grid"
    # Falloff scales (km) mapping distance fields to [0,1] suitability weights, and the random
    # tie-break jitter strength. Smaller scale => the bonus decays faster with distance.
    "freshwater_scale_km": 150.0,
    "coastal_scale_km": 225.0,
    "remoteness_scale_km": 550.0,
    "jitter": 0.15,
    # Minimum fraction of a land structure's (max) footprint that must be dry land for an anchor to
    # be eligible. Keeps a coastal structure substantial (most of it on land) while still allowing
    # shoreline sites - the terrain-aware interior builder forms the structure around whatever water
    # the footprint clips. 1.0 forbids any footprint water (the old behaviour); 0 disables the check.
    "min_footprint_land": 0.5,
    # Per-kind rules. ``count`` is a target; ``min_spacing`` enforces blue-noise separation;
    # ``biomes`` whitelists land cover; ``civilized`` affects road connection probability.
    "types": {
        "tower": {
            "count": 4,
            "min_spacing": 16,
            "civilized": False,
            "biomes": ["snow", "grass", "forest", "tundra"],
            "elevation_min_m": 300.0,
            "remoteness": 0.5,
            "floors": [2, 4],
        },
        "dungeon": {
            "count": 4,
            "min_spacing": 18,
            "civilized": False,
            "biomes": ["snow", "forest", "tundra", "desert", "swamp"],
            "elevation_min_m": 100.0,
            "remoteness": 0.7,
            "floors": [2, 5],
        },
        "ruin": {
            "count": 5,
            "min_spacing": 14,
            "civilized": False,
            "biomes": ["grass", "forest", "desert", "savanna", "tundra", "jungle"],
            "remoteness": 0.6,
            "floors": 1,
        },
        "camp": {
            "count": 6,
            "min_spacing": 10,
            "civilized": False,
            "biomes": ["grass", "forest", "tundra", "savanna", "taiga"],
            "remoteness": 0.3,
            "floors": 1,
        },
        "boat": {
            "count": 5,
            "min_spacing": 14,
            "civilized": False,
            "biomes": ["shallow", "deep", "lake"],
            "on_water": True,
            "floors": 1,
        },
    },
}

"""Defaults for the ``poi`` section (wild points of interest: placement and per-kind rules).

Settlements are placed by the settlements stage (``settlements`` section, ``data/tiers.toml``); these rows cover
the wild kinds until phase 8 makes POI kinds data-driven.
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "density": 1.0,  # multiplies every kind's count (1.0 = one per km2_per_poi)
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
    # Per-kind rules. ``priority`` orders the passes (low first); one POI per ``km2_per_poi`` of land (of sea
    # for ``on_water`` kinds); ``min_spacing_km`` separates a POI from every other POI; ``biomes`` whitelists
    # land cover; the weights favour freshwater, coast and distance from settlements; ``floors`` is a count or
    # a [min, max] range.
    "types": {
        "tower": {
            "priority": 10,
            "km2_per_poi": 1750000.0,
            "min_spacing_km": 400.0,
            "biomes": ["snow", "grass", "forest", "tundra"],
            "elevation_min_m": 300.0,
            "remoteness": 0.5,
            "floors": [2, 4],
        },
        "dungeon": {
            "priority": 20,
            "km2_per_poi": 1750000.0,
            "min_spacing_km": 450.0,
            "biomes": ["snow", "forest", "tundra", "desert", "swamp"],
            "elevation_min_m": 100.0,
            "remoteness": 0.7,
            "floors": [2, 5],
        },
        "ruin": {
            "priority": 30,
            "km2_per_poi": 1400000.0,
            "min_spacing_km": 350.0,
            "biomes": ["grass", "forest", "desert", "savanna", "tundra", "jungle"],
            "remoteness": 0.6,
            "floors": 1,
        },
        "camp": {
            "priority": 40,
            "km2_per_poi": 1200000.0,
            "min_spacing_km": 250.0,
            "biomes": ["grass", "forest", "tundra", "savanna", "taiga"],
            "remoteness": 0.3,
            "floors": 1,
        },
        "boat": {
            "priority": 50,
            "km2_per_poi": 2200000.0,
            "min_spacing_km": 350.0,
            "biomes": ["shallow", "deep", "lake"],
            "on_water": True,
            "floors": 1,
        },
    },
}

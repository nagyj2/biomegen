"""Defaults for the ``regions`` section (regions)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Tiles are grouped into a region with neighbours of a "similar" biome. Each entry lists the
    # biomes considered interchangeable for grouping (so e.g. forest+jungle+taiga form woodland
    # regions). Any biome not listed groups only with its own kind.
    "similarity_groups": [
        ["forest", "jungle", "taiga", "swamp"],
        ["grass", "savanna"],
        ["desert"],
        ["tundra", "snow"],
        ["beach"],
        ["lake"],
        ["deep", "shallow", "seaice"],
    ],
    "min_region_size": 22,  # regions smaller than this are merged into their best neighbour
    "max_region_size": 100,  # regions larger than this are split into equal sub-regions
    # ocean tiles within this many steps of land get a region name; deeper tiles stay anonymous
    "coastal_ocean_depth": 3,
    "color_jitter": 28,  # +/- RGB jitter applied per region to its biome base colour
}

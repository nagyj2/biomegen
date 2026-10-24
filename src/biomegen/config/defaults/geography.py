"""Defaults for the ``geography`` section (``pipeline/physical/geography.py``).

Values follow the reference generator's ``_regions`` (``docs/reference/worldgen.py``), its cell counts
converted at its default grid (about 30 x 30 km cells, 6000 km wide).
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "min_landmass_km2": 140000.0,  # smaller land components get a landmass_id but no landmass feature
    "min_range_km2": 10000.0,  # connected mountain / peak / volcano areas at least this big are ranges
    "min_named_lake_km2": 5000.0,  # lakes at least this big become lake features
    # Seas: the sea cells farthest from land, at least sea_min_offshore_km out, spaced sea_spacing_km
    # apart; each reports the greatest depth within sea_depth_radius_km of its centre.
    "max_seas": 3,
    "sea_min_offshore_km": 90.0,
    "sea_edge_margin": 0.15,  # fraction of the map's width / height kept clear of sea centres (the ocean frame)
    "sea_spacing_km": 2100.0,
    "sea_depth_radius_km": 1000.0,
    # Rivers: the max_named_rivers with the largest catchment at the mouth, if at least min_river_km long.
    "max_named_rivers": 5,
    "min_river_km": 150.0,
}

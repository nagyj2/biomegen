"""Defaults for the ``hydrology`` section (hydrology)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Flow accumulation is a wetness-weighted drainage area: each land cell adds its area (km²) times
    # (runoff_base + moisture), so wet catchments grow rivers sooner (as in the reference generator).
    "runoff_base": 0.2,
    # A land cell becomes river channel when its weighted drainage area is in the top river_land_share of
    # land cells AND at least river_min_drainage_km2 (the floor keeps tiny worlds from sprouting rivers).
    "river_land_share": 0.035,
    "river_min_drainage_km2": 5000.0,
    "max_rivers": 24,  # cap on traced rivers (largest-catchment sources first)
    # A depression becomes a lake where its filled surface stands at least lake_min_depth_m above the
    # ground, over at least min_lake_area_km2. The lake surface is flattened to its spill level.
    "lake_min_depth_m": 15.0,  # tuned at 240x60: low land is flat, so basins are shallow
    "min_lake_area_km2": 3000.0,
    # River width grows with drainage area: a channel carrying ``ratio`` x the channel threshold widens by
    # ``(ratio-1) * river_width_scale`` tiles, capped at ``river_max_width`` tiles. A display effect for the
    # detail views (a real river is far narrower than a ~30 km cell), so it stays in tiles until phase 4.
    "river_width_scale": 0.5,
    "river_max_width": 5,
    "moisture_radius_km": 150.0,  # e-folding distance of the fresh-water moisture bonus
    "moisture_strength": 0.28,  # magnitude of the fresh-water moisture bonus (rain_mm is recomputed)
}

"""Defaults for the ``world`` section (world dimensions)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Width fits a ~209-column terminal at 1:1. Height is taller than a 58-line terminal leaves
    # room for (58 - status_height), so the "fit" view downsamples vertically.
    "width": 192,
    "height": 75,
    # "fixed" keeps the dimensions above (reproducible across terminals). "auto" fits the world to
    # the current terminal at launch (nicer fit, but the same seed yields different worlds on
    # differently sized terminals - documented trade-off).
    "size_mode": "fixed",
    # Physical extent of the whole map, [east-west, north-south] in km. Cells are
    # size_km / (width, height) km, so they are anisotropic whenever the ratios differ.
    "size_km": [6000.0, 3000.0],
    # Map centre in degrees (north and east positive). The latitude is clamped so both map edges stay
    # within +-89 degrees; it places the map on the globe for climate and the graticule.
    # "seed" picks a hemisphere and a latitude in center_lat_range_deg per seed; a number pins it.
    "center_lat": "seed",
    "center_lat_range_deg": [18.0, 48.0],  # [min, max] absolute latitude for "seed", 0..89
    "center_lon": 0.0,
    # The island-mask sanity gate regenerates with a perturbed seed up to this many times if a
    # seed produces less than ``min_land_fraction`` land (prevents empty-world cascades).
    "regen_attempts": 8,
    "min_land_fraction": 0.12,
}

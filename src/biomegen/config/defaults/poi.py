"""Defaults for the ``poi`` section (wild points of interest: placement and per-kind rules).

Settlements are placed by the settlements stage (``settlements`` section, ``data/tiers.toml``); the per-kind rows of
the wild and dynamic kinds are the ``tables.pois`` table (``data/pois.toml``).
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
    # The forest term of a style's score: the share of land within this radius that wears one of these biomes.
    "forest_biomes": ["forest", "taiga", "jungle"],
    "forest_radius_km": 90.0,
    # How long before the present a generated homestead or hamlet was founded: [min, max] years, drawn per POI.
    "style_founded_years": {"homestead": [5, 200], "hamlet": [20, 400]},
    # The people of a generated homestead (one household): [min, max], drawn per POI.
    "homestead_people": [3, 12],
    # Minimum fraction of a land structure's (max) footprint that must be dry land for an anchor to
    # be eligible. Keeps a coastal structure substantial (most of it on land) while still allowing
    # shoreline sites - the terrain-aware interior builder forms the structure around whatever water
    # the footprint clips. 1.0 forbids any footprint water (the old behaviour); 0 disables the check.
    "min_footprint_land": 0.5,
}

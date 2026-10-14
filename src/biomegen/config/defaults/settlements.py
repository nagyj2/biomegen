"""Defaults for the ``settlements`` section (habitability and settlement placement).

Per-tier rows (spacing, population, one settlement per so much land) live in ``data/tiers.toml``.
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "density": 1.0,  # multiplies every tier's settlement count (1.0 = one per land_per_settlement_km2)
    "min_habitability": 0.05,  # cells at or below this never hold a settlement
    "jitter": 0.3,  # habitability is scaled by 1 +/- jitter (seeded per cell), so equal sites are not tied
    # A cell gets a bonus when water lies within the reach (km). Bonuses apply only where the relief allows
    # settling at all (relief habitability_mul > 0), so no town sits on a peak because a river is near.
    "river_bonus": 0.7,
    "river_reach_km": 60.0,
    "coast_bonus": 0.45,
    "coast_reach_km": 60.0,
    "lake_bonus": 0.3,
    "lake_reach_km": 60.0,
    # Capitals need a landmass of at least this area (or the biggest landmass, whichever is smaller); cities
    # and towns need a landmass big enough to be a named feature (geography.min_landmass_km2).
    "capital_min_landmass_km2": 400000.0,
    "max_capitals": 16,
}

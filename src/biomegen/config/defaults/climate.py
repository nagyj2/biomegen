"""Defaults for the ``climate`` section (climate)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # "equator-center": warm band across the vertical middle, cooler toward top & bottom.
    # "north-pole-top": cold at the top, warm at the bottom.
    "orientation": "equator-center",
    "equator_temp": 1.0,  # normalised temperature at the warm latitude
    "pole_temp": 0.05,  # normalised temperature at the cold latitude
    "lapse_rate": 0.55,  # temperature drop with elevation (higher = colder mountains)
    "moisture_scale": 95.0,
    "moisture_octaves": 4,
    "moisture_persistence": 0.5,
    # Exponent applied to normalised moisture: >1 biases the map drier (more desert/savanna/
    # grassland and less forest/jungle), giving more biome variety. 1.0 = neutral.
    "moisture_redistribution": 1.5,
    "coastal_bias": 0.10,  # extra moisture near the coast (0 disables; lower => drier interiors)
    "coastal_range": 7.0,  # tiles over which the coastal moisture bonus decays
}

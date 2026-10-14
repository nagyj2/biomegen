"""Defaults for the ``biomes`` section (``pipeline/physical/biomes.py``).

Values follow the reference generator's ``_biomes`` (``docs/reference/worldgen.py``). Relief thresholds
are the ``min_elevation_m`` column of the relief rows in ``data/biomes.toml``.
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Land classifier: the first band whose max_temp_c is above the cell's temperature applies. In that
    # band the first [biome, max_rain_mm] rule with rain below max_rain_mm wins, else the band's biome.
    # Bands with swamp = true turn very wet lowland into swamp first (see swamp_* below).
    "bands": [
        {"max_temp_c": -9.0, "rain": [], "biome": "snow", "swamp": False},
        {"max_temp_c": -3.0, "rain": [["tundra", 600.0]], "biome": "taiga", "swamp": False},
        {"max_temp_c": 3.0, "rain": [["tundra", 250.0]], "biome": "taiga", "swamp": False},
        {"max_temp_c": 18.0, "rain": [["desert", 150.0], ["grass", 800.0]], "biome": "forest", "swamp": True},
        {
            "max_temp_c": 100.0,
            "rain": [["desert", 400.0], ["savanna", 950.0], ["grass", 1400.0]],
            "biome": "jungle",
            "swamp": True,
        },
    ],
    "swamp_min_rain_mm": 3000.0,  # swamp needs more rain than this (reference 2600; tuned at 240x60)...
    "swamp_max_elevation_m": 300.0,  # ...on land lower than this
    # Beach: land touching the sea, below this height, warmer than this, not swamp and not a river.
    "beach_max_elevation_m": 150.0,
    "beach_min_temp_c": 5.0,
    "peak_biome": "snow",  # cover of every cell with peak relief
    # Sea: ice where temperature + ice_noise_c * noise is below sea_ice_c; shallows within shallow_km of
    # land; deep elsewhere. Lakes colder than lake_ice_c freeze over.
    "sea_ice_c": -1.8,
    "ice_noise_c": 3.0,
    "ice_feature_km": 430.0,
    "ice_octaves": 3,
    "shallow_km": 75.0,
    "lake_ice_c": -5.0,
    # Volcanoes: this many (one value drawn per seed) of the mountain and peak cells within
    # volcano_coast_km of the sea (any mountain cell if none is that close) become volcanoes.
    "volcano_counts": [0, 1, 1, 2, 2, 3],
    "volcano_coast_km": 150.0,
}

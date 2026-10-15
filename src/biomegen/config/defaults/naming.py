"""Defaults for the ``naming`` section (naming / lore)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "markov_order": 2,
    "max_name_len": 12,
    "min_name_len": 4,
    # Per-category generator: "syllable" (default; clean culture-distinct roots + affixes) or
    # "markov" (order-2 chain over a per-culture corpus; organic but rougher with affixes).
    "generators": {
        "island": "syllable",
        "region": "syllable",
        "realm": "syllable",
        "ruler": "syllable",
        "poi": "syllable",
        "river": "syllable",
        "lake": "syllable",
        "landmass": "syllable",
        "range": "syllable",
        "peak": "syllable",
        "sea": "syllable",
    },
    "lore_min": 1,
    "lore_max": 4,
}

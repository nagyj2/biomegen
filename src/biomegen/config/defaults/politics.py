"""Defaults for the ``politics`` section (realms and diplomacy). Distances are km, areas km²."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Realm seeds. Every capital founds a major realm. A city is a city-state candidate: with
    # ``city_state_far_chance`` when it lies more than ``city_state_far_km`` from every capital, otherwise with
    # ``city_state_chance``. Up to ``tribe_max`` tribes then claim the largest unclaimed solid areas of at least
    # ``tribe_min_area_km2``, seated at the most populous settlement there (or the most inland cell).
    "city_state_far_km": 540.0,
    "city_state_far_chance": 0.7,
    "city_state_chance": 0.25,
    "tribe_max": 6,
    "tribe_min_area_km2": 40000.0,
    # Claiming land: a Dijkstra over the move-cost surface from every seed, a step costing its km length times
    # the cell's move cost (+ ``river_cost`` on a river) divided by the realm's strength. A realm claims a cell
    # while its cost stays within ``claim_budget_km``. A realm may hop across water up to ``coastal_hop_km`` from
    # land at ``coastal_hop_cost`` (a move cost, flat land is 1) so a coast reaches its islets.
    "claim_budget_km": 1500.0,
    "river_cost": 3.0,
    "coastal_hop_km": 60.0,
    "coastal_hop_cost": 6.0,
    # Habitats: a realm whose dominant biome is listed here favours the forms of that habitat (data/polity.toml).
    # A realm whose land is mostly relief has the habitat "high".
    "habitats": {
        "dry": ["desert", "savanna"],
        "cold": ["tundra", "taiga", "snow"],
        "wood": ["forest", "jungle", "swamp", "taiga"],
    },
    # Diplomacy. A major swears fealty only to a major at least ``vassal_area_ratio`` times its area. A war's
    # claimed town is the enemy settlement nearest to ``claim_samples`` border cells. ``hue_step`` spaces realm
    # colours round the hue circle (the golden ratio). Two far-apart independent majors may still hold a pact
    # across the sea, of a kind from ``sea_pact_kinds``.
    "vassal_area_ratio": 2.0,
    "claim_samples": 40,
    "hue_step": 0.618034,
    "sea_pact_kinds": ["alliance", "trade"],
    # Trade goods when a realm's biome (or relief) names none: the first for the first realm, the second for the
    # other, the third when the two would otherwise trade the same good.
    "fallback_goods": ["wool", "wine", "copper"],
    # A reason may name a river, range or sea only when one lies within ``reason_near_km`` of the two powers' border
    # (their seats when they share none); ``reason_points`` caps how many border cells the distance is measured from.
    "reason_near_km": 250.0,
    "reason_points": 12,
    # The kinds of settlement a reason such as "the border town of {town}" may name when no town is claimed.
    "reason_town_kinds": ["town", "village"],
}

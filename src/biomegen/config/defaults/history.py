"""Defaults for the ``history`` section: the derived chronicle (see ``pipeline/story/history.py``).

Years are whole numbers counting up to the present (``span_years``). Distances are km, areas km². The event wording is
in ``data/chronicle.toml``, not here.
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # "present" generates a finished world with a chronicle; "dawn" stops after the physical stages (year 0, nothing
    # settled, no chronicle) so a later simulation can start from a young world.
    "start": "present",
    "span_years": 1200,  # the present year of a "present" world
    # The event kinds to derive (any of world.entities.EVENT_KINDS); leave one out to switch it off.
    "kinds": ["founding", "settling", "conquest", "war", "rivalry", "treaty", "battle", "fall"],
    # Founding: a realm's age is a share of span_years drawn from its kind's range, pulled toward the oldest end by
    # larger area by ``age_area_weight`` (0 = pure draw, 1 = rank only).
    "age_range": {"major": [0.5, 0.95], "city_state": [0.2, 0.7], "tribal": [0.6, 1.0]},
    "age_area_weight": 0.5,
    "settle_kinds": ["city"],  # settlement kinds that get a settling event (others are only dated)
    "min_gap_years": 20,  # least time between a realm existing and its next event (conquest, war, treaty)
    # Relations: a relation lasts a number of years between the two ends of its range, longer for a longer shared
    # border (``border_km_for_full_span`` km or more gives the top end). A war is ongoing at the present.
    "war_years": [10, 300],
    "other_years": [20, 600],
    "border_km_for_full_span": 1500.0,
    "battles_per_100km_front": 0.5,  # battles fought along a war's border, per 100 km of it
    # Fallen realms: wild land (no realm) habitable enough to have held a realm, away from each other and from
    # settlements. They lasted ``fallen_life_years`` and fell at least ``fallen_min_years_ago`` before the present.
    "fallen_realms_per_million_km2": 1.0,
    "fall_min_habitability": 0.3,
    "fall_spacing_km": 200.0,
    "fallen_life_years": [100, 500],
    "fallen_min_years_ago": 50,
    # A place named in an event ({near}) must be a settlement on the same landmass within this distance.
    "near_km": 250.0,
}

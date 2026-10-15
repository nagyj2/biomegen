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
    "kinds": ["founding", "settling", "conquest", "succession", "war", "rivalry", "treaty", "battle", "peace", "fall"],
    # Founding: a realm's age is a share of span_years drawn from its kind's range, pulled toward the oldest end by
    # larger area by ``age_area_weight`` (0 = pure draw, 1 = rank only).
    "age_range": {"major": [0.6, 1.0], "city_state": [0.3, 0.8], "tribal": [0.7, 1.0]},
    "age_area_weight": 0.5,
    "settle_kinds": ["city", "town"],  # settlement kinds that get a settling event (others are only dated)
    # A free settlement (no realm holds it) within ``remnant_km`` of a fallen realm's site, on the same landmass, is a
    # remnant of that realm: it is founded during the realm's life and its settling event names the realm.
    "remnant_km": 250.0,
    # Ruling styles (data/rulers.toml): a realm's style may change at a succession, one of which falls every
    # ``succession_years`` years; only a change is an event. Rulers' real lifetimes are abstracted away.
    "succession_years": [300, 700],
    "succession_change_chance": 0.5,
    "min_gap_years": 20,  # least time between a realm existing and its next event (conquest, war, treaty)
    "first_founding_year": 10,  # the oldest realm is founded this year; every founding is shifted to match
    # Relations. A pair sharing a border may have had an older war first (``past_war_chance``, lasting
    # ``past_war_years``) that ended in peace; the relation itself then begins at any later year. A war's front sees
    # ``battles_per_100km_front`` battles per 100 km of border (at least one for an older war).
    "past_war_chance": 0.15,
    "past_war_years": [5, 60],
    "battles_per_100km_front": 0.1,
    # Strength of a faction (the odds of a battle): a realm starts at its area over the mean realm area, within
    # ``start_strength_range``; a fallen realm draws from ``fallen_strength``. A victory multiplies it by
    # ``1 + victory_gain``, a defeat by ``1 - defeat_loss``, never below ``min_strength``.
    "start_strength_range": [0.25, 4.0],
    "fallen_strength": [0.3, 1.0],
    "victory_gain": 0.15,
    "defeat_loss": 0.2,
    "min_strength": 0.05,
    # Fallen realms: wild land (no realm) habitable enough to have held a realm, away from each other and from
    # settlements. They lasted ``fallen_life_years`` and fell at least ``fallen_min_years_ago`` before the present.
    "fallen_realms_per_million_km2": 1.0,
    "fall_min_habitability": 0.3,
    "fall_spacing_km": 200.0,
    "fallen_life_years": [100, 500],
    "fallen_min_years_ago": 50,
    # Each fallen realm fights ``fallen_wars`` wars (a [min, max] count) against its ``fallen_neighbours`` nearest
    # living realms; after a lost battle that leaves its strength under ``fall_strength`` it is conquered
    # ``fall_delay_years`` on.
    "fallen_wars": [0, 2],
    "fallen_neighbours": 3,
    "fall_strength": 0.3,
    "fall_delay_years": [2, 25],
    # Colours of the coloured text output: the year column, each event kind, and two neutral colours for names that
    # belong to no faction: ``settlement`` (a settlement's first mention, and any wild one) and ``place`` (mountains,
    # seas, rivers and other named land). A faction's name, ruler and settlements are in its own map colour.
    # [r, g, b] or "#rrggbb".
    "colors": {
        "year": [150, 150, 160],
        "founding": [120, 210, 130],
        "settling": [150, 200, 160],
        "conquest": [230, 150, 90],
        "succession": [200, 180, 120],
        "war": [235, 90, 90],
        "rivalry": [220, 120, 160],
        "treaty": [110, 180, 235],
        "battle": [240, 190, 80],
        "peace": [140, 220, 220],
        "fall": [170, 140, 210],
        "settlement": [232, 222, 190],
        "place": [150, 185, 205],
    },
    # A place named in an event ({near}) must be a settlement on the same landmass within this distance.
    "near_km": 250.0,
}

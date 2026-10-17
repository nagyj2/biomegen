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
    "months_per_year": 12,  # events of one year are placed in months 1 to this (a simulation may use the same range)
    # The event kinds to derive (any of world.entities.EVENT_KINDS); leave one out to switch it off.
    "kinds": [
        "founding",
        "secession",
        "settling",
        "expansion",
        "conquest",
        "succession",
        "war",
        "rivalry",
        "treaty",
        "battle",
        "peace",
        "fall",
    ],
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
    # Every ruler (the founder and one per succession) has the five traits of ``world.entities.TRAITS``: its ruling
    # style's base values (data/rulers.toml) plus a seeded draw within +- this spread, kept in [0, 1].
    "ruler_trait_spread": 0.15,
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
        "secession": [210, 170, 90],
        "settling": [150, 200, 160],
        "expansion": [170, 215, 120],
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
        "match": [90, 80, 20],  # background of a search match in the chronicle pager
        "type_realm": [196, 176, 128],  # neutral tags of the name kinds in the chronicle pager's name suggestions
        "type_fallen": [160, 140, 150],
        "type_predecessor": [140, 150, 165],
        "type_ruler": [190, 150, 140],
        "type_poi": [140, 175, 150],
        "match_current": [170, 120, 30],  # ... of the match the pager is on
    },
    # A place named in an event ({near}) must be a settlement on the same landmass within this distance.
    "near_km": 250.0,
    # Secession (pipeline/story/secession.py; the weights and wording are data/secession.toml and chronicle.toml). A
    # secession is an offshoot (a realm leaves an older one), a clean split (an old realm ends in two) or a defection (a
    # settlement changes sides). Each realm's founding year, and each settlement a defection may touch, is checked
    # once: it happens with chance ``chance`` (that of the likeliest form; the others scale by their weight in
    # ``tables.secession_forms``) times the plausibility score (0..1), at most ``max_per_world`` times in a world.
    "secession": {
        "chance": 0.1,
        "max_per_world": 4,
        "defect_km": 250.0,  # a settlement may leave a realm whose land lies within this distance of it
        "proximity_km": 600.0,  # two seats this far apart score nothing for proximity
        "size_share": [0.2, 0.7],  # the breakaway's area, as a share of its parent's, over which the size term is full
        "age_years": 600,  # a parent's age at which the age term is full
        "prosperity_ratio": 2.0,  # the breakaway's people per km2 over its parent's: the prosperity term is full
        "weak_strength": 0.5,  # a parent's strength (against the mean) at or below which the strength term is full
    },
    # Territory (pipeline/story/territory.py): who held which land is recorded as changes of ownership, found by walking
    # back from today's partition, so the present map never moves. A realm grew by a few large annexations of wild land
    # (``expansion`` events): ``expansions`` per realm kind is the [fewest, most], each taking ``expansion_share``
    # [least, most] of the realm's present area, the cells farthest from its seat first. A realm keeps at least
    # ``core_share`` of its present area when it is founded, and one smaller than ``min_cells`` never expands or loses
    # a band under ``min_band_cells`` cells.
    "territory": {
        "expansions": {"major": [1, 2], "city_state": [0, 1], "tribal": [0, 1], "fallen": [0, 1]},
        "fallen_area_km2": [50000.0, 300000.0],  # the land a fallen realm held when it fell (a draw per realm)
        "fallen_reach": 2.5,  # it lies within this many radii (of a disc of that area) of its ruins
        "victor_bias": 0.5,  # a conquering realm's cells count as this much nearer the ruins when the land is chosen
        "expansion_share": [0.15, 0.3],
        "core_share": 0.3,
        "min_cells": 12,
        "min_band_cells": 3,
        # A battle or peace may move a strip of the winner's land along the front to the loser (undone in the walk): a
        # decisive battle always, others with ``strip_chance``, a peace of an older war with ``cession_chance``. A strip
        # takes a share (a [least, most] draw) of the winner's land: the cells within ``depth_km`` of the loser's,
        # nearest the battle first.
        "strips": {
            "strip_chance": 0.7,
            "strip_share": [0.01, 0.04],
            "decisive_share": [0.05, 0.12],
            "cession_chance": 0.5,
            "cession_share": [0.03, 0.08],
            "depth_km": 200.0,
        },
    },
    # The history viewer (``--history``, explorer/history_viewer.py): the political map at a moment with the powers and
    # the chronicle beside it. The map takes ``map_share`` of the width (at least ``min_map_cols`` columns, leaving
    # ``min_event_cols`` for the events); events at the current moment are drawn on ``current_bg``, later ones dimmed.
    "viewer": {
        "map_share": 0.6,
        "min_map_cols": 40,
        "min_event_cols": 34,
        "current_bg": [60, 56, 30],
    },
}

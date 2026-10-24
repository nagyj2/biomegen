"""Hydrate: turn a finished present world into the simulation's starting state.

:func:`hydrate` copies and derives only; it invents no numbers. The owner grid, each realm's faction (its present ruler
and that ruler's traits, liege, seat and people), each populated place, each settlement's manifest and today's relations
become a :class:`~biomegen.world.sim_state.SimState`, and each faction gets the first check of every cadence
(:mod:`.cadence`). Stocks, opening buildings and opinions start empty: the economy and diplomacy write their own rules.
The world is read and never written, and a dawn world (no realms, no settlements) hydrates to a state with none.
"""

from __future__ import annotations

import copy

import numpy as np

from ..config.model import Config
from ..sites.manifest import site_manifest
from ..world.entities import POI, Realm
from ..world.sim_state import Faction, PlaceState, Schedule, SimState, present_tick
from ..world.world import World
from . import cadence


def _faction(world: World, config: Config, seed: int, realm: Realm, start: int) -> Faction:
    """The faction of ``realm``: its present ruler's id and traits (none when it has no rulers) and its first checks."""
    ruler = world.ruler_at(realm.id, world.year)
    return Faction(
        realm_id=realm.id,
        ruler_id=ruler.id if ruler is not None else -1,
        traits=dict(ruler.traits) if ruler is not None else {},
        liege=realm.liege,
        seat_poi=realm.seat_poi,
        pop=realm.pop,
        schedule={
            name: Schedule(next_tick=cadence.first_check(seed, config, realm.id, name, start), count=0, last_tick=start)
            for name in cadence.cadence_names(config)
        },
    )


def _is_place(poi: POI) -> bool:
    """Whether ``poi`` holds people the simulation tracks: a settlement (free ones too) or a homestead."""
    return poi.civilized or poi.kind == "homestead"


def hydrate(world: World, config: Config, seed: int) -> SimState:
    """Return the simulation state of ``world`` at the present moment.

    Pure and deterministic: the same world, config and seed give an equal state on any machine, and ``world`` is not
    changed. ``seed`` keys the cadence phases (:func:`~biomegen.sim.cadence.phase_ticks`).
    """
    ticks_per_month = int(config.get("sim.ticks_per_month"))
    start = present_tick(world.year, int(config.get("history.months_per_year")), ticks_per_month)
    state = SimState(
        tick=start,
        ticks_per_month=ticks_per_month,
        owners=np.array(world.realm_id, dtype=np.int16, order="C", copy=True),
    )
    for realm in world.realms:
        state.factions[realm.id] = _faction(world, config, seed, realm, start)
    for index, poi in enumerate(world.pois):
        if _is_place(poi):
            state.places[index] = PlaceState(owner=poi.realm_id, pop=poi.pop)
        manifest = site_manifest(config, poi) if poi.civilized else None
        if manifest is not None:
            state.manifests[index] = manifest
    for relation in world.relations:
        state.relations[(relation.a, relation.b)] = copy.deepcopy(relation)
    return state

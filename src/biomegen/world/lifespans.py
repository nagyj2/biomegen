"""When each point of interest appears on the map of the past.

A settlement stands from the event that founded or settled it (else the year it was founded), a ruin from the fall that
left it, a battlefield from its battle, a watchtower from the war it guards and so on, each kind's event being the
``history.appears`` row; a point with no such date (a camp before its creation, an ancient ruin) is always there. A
watchtower dismantled at the peace (``World.vanished``) stands only until then, and one that bandits took stands as a
watchtower until they did. Moments are ``(year, month)`` (the end of the month) or ``(year, month, event id)`` (just
after that event), so two events of one month are told apart. Nothing here changes the world.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..config.model import Config
from .entities import POI
from .territory import Key, at_end
from .world import World

Stop = tuple[int, int]  # (year, month)
_SETTLED = ("founding", "settling", "secession")  # the events that found or settle a settlement


def place_key(world: World, config: Config, poi: POI) -> Optional[Key]:
    """Return the place in time (see :data:`Key`) ``poi`` first stands, or ``None`` when it has always stood."""
    linked = [world.chronicle[i] for i in poi.event_ids if 0 <= i < len(world.chronicle)]
    rule = config.get("history.appears").get(poi.kind)
    if rule is not None:  # a kind dated by one kind of event; with none linked it is ancient
        made = [e for e in linked if e.kind == rule]
        return (made[0].year, made[0].month, made[0].id) if made else None
    founding = [e for e in linked if e.kind in _SETTLED]
    if founding:
        return founding[0].year, founding[0].month, founding[0].id
    return (poi.founded, 1, -1) if poi.founded > 0 else None


def place_appears(world: World, config: Config, poi: POI) -> Optional[Stop]:
    """Return the ``(year, month)`` ``poi`` first stands, or ``None`` when it has always stood."""
    key = place_key(world, config, poi)
    return None if key is None else (key[0], key[1])


def poi_appears(world: World, config: Config, index: int) -> Optional[Stop]:
    """Return the ``(year, month)`` POI ``index`` (see :meth:`World.place`) first stands, or ``None`` if always."""
    return place_appears(world, config, world.place(index))


def place_gone(world: World, poi: POI) -> Optional[Key]:
    """Return the place in time a vanished ``poi`` was dismantled (the closing event it links), else ``None``."""
    if (
        poi.extra.get("fate") != "dismantled"
        or len(poi.event_ids) < 2
        or not 0 <= poi.event_ids[1] < len(world.chronicle)
    ):
        return None
    closing = world.chronicle[poi.event_ids[1]]
    return closing.year, closing.month, closing.id


def poi_kind_at(world: World, poi: POI, moment: tuple[int, ...]) -> str:
    """Return the kind ``poi`` was at ``moment``: a tower bandits took was a watchtower until they did."""
    if poi.extra.get("fate") == "occupied":
        linked = [world.chronicle[i] for i in poi.event_ids if 0 <= i < len(world.chronicle)]
        taken = next((e for e in linked if e.kind == "occupation"), None)
        if taken is not None and at_end(moment) < (taken.year, taken.month, taken.id):
            return "watchtower"
    return poi.kind


def visible_pois(world: World, config: Config, moment: tuple[int, ...]) -> np.ndarray:
    """Return a bool per POI, then per vanished POI (the indices of :meth:`World.place`): whether it stands then."""
    now = at_end(moment)
    every = [*world.pois, *world.vanished]
    visible = np.ones(len(every), dtype=bool)
    for index, poi in enumerate(every):
        appears = place_key(world, config, poi)
        gone = place_gone(world, poi)
        visible[index] = (appears is None or appears <= now) and (gone is None or now < gone)
    return visible


def visible_roads(world: World, config: Config, moment: tuple[int, ...]) -> np.ndarray:
    """Return a ``[y, x]`` bool grid of the road laid at ``moment``: the links built by then whose ends stand."""
    now = at_end(moment)
    standing = visible_pois(world, config, moment)
    road = np.zeros(world.road.shape, dtype=bool)
    for link in world.road_links:
        laid = world.chronicle[link.event_id] if 0 <= link.event_id < len(world.chronicle) else None
        built = laid is None or (laid.year, laid.month, laid.id) <= now
        if built and standing[link.a] and (link.b < 0 or standing[link.b]):
            road.reshape(-1)[link.cells] = True
    return road

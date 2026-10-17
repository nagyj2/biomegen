"""When each point of interest appears on the map of the past.

A settlement stands from the event that founded or settled it (else the year it was founded), a ruin from the fall that
left it, a battlefield from its battle, a watchtower from the war it guards and so on, each kind's event being the
``history.appears`` row; a point with no such date (a camp, a boat, an ancient ruin) is always there. Nothing here
changes the world: the history viewer asks which points exist at a moment.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..config.model import Config
from .world import World

Stop = tuple[int, int]  # (year, month)
_SETTLED = ("founding", "settling", "secession")  # the events that found or settle a settlement


def poi_appears(world: World, config: Config, index: int) -> Optional[Stop]:
    """Return the ``(year, month)`` POI ``index`` first stands, or ``None`` when it has always stood."""
    poi = world.pois[index]
    linked = [world.chronicle[i] for i in poi.event_ids if 0 <= i < len(world.chronicle)]
    rule = config.get("history.appears").get(poi.kind)
    if rule is not None:  # a kind dated by one kind of event; with none linked it is ancient
        made = [e for e in linked if e.kind == rule]
        return (made[0].year, made[0].month) if made else None
    founding = [e for e in linked if e.kind in _SETTLED]
    if founding:
        return founding[0].year, founding[0].month
    return (poi.founded, 1) if poi.founded > 0 else None


def visible_pois(world: World, config: Config, moment: Stop) -> np.ndarray:
    """Return a bool per POI: whether it stands at ``moment``."""
    visible = np.ones(len(world.pois), dtype=bool)
    for index in range(len(world.pois)):
        appears = poi_appears(world, config, index)
        visible[index] = appears is None or appears <= moment
    return visible

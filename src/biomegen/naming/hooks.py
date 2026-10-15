"""Hooks: the story text of a POI, stored on it (``POI.hook`` and ``POI.hook_refs``).

A POI an event made or marks takes its first event's text and name spans. Any other POI takes a template from its
kind's row in ``tables.pois`` (``hooks``, plus ``hooks_near`` when a settlement is near), with ``{name}`` the POI's own
name and ``{near}`` the settlement's. A kind with neither (a village no event dates) has an empty hook. Runs after the
chronicle's text is rendered and the POIs are named; every draw is keyed on the POI's cell, so a hook never depends
on processing order. A later simulation calls :func:`describe_hook` for a POI it mints.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config.model import Config
from ..util import rng
from ..world.entities import POI, REF_POI
from ..world.world import World
from .render import render_template


def describe_hook(world: World, config: Config, seed: int, index: int, near_index: int) -> None:
    """Fill ``hook`` and ``hook_refs`` of ``world.pois[index]``; ``near_index`` is its qualifying settlement or -1."""
    poi: POI = world.pois[index]
    poi.hook, poi.hook_refs = "", []
    if poi.event_ids:
        event = world.chronicle[poi.event_ids[0]]
        poi.hook, poi.hook_refs = event.text, list(event.refs)
        return
    row = config.get(f"tables.pois.{poi.kind}", None)
    pool = list(row.get("hooks", [])) if row else []
    if row and near_index >= 0:
        pool += list(row.get("hooks_near", []))
    if not pool:
        return
    stream = rng.derive(seed, "naming", "hook", poi.x, poi.y)
    tokens: dict[str, object] = {"name": poi.name, "near": world.pois[near_index].name if near_index >= 0 else ""}
    where = {"name": (REF_POI, index)}
    if near_index >= 0:
        where["near"] = (REF_POI, near_index)
    text, refs = render_template(str(stream.choice(pool)), tokens, where)
    poi.hook, poi.hook_refs = text, refs


def describe_hooks(world: World, config: Config, seed: int, near_of: Callable[[int], int]) -> None:
    """Fill the hook of every POI; ``near_of(index)`` gives the settlement a POI's text may name (-1 for none)."""
    for index in range(len(world.pois)):
        describe_hook(world, config, seed, index, near_of(index))

"""Hooks: the story text of a POI, stored on it (``POI.hook`` and ``POI.hook_refs``).

A POI an event made or marks takes its first event's text and name spans. Any other POI takes a template from its
kind's row in ``tables.pois`` (``hooks``, plus ``hooks_near`` when a settlement is near), or, when it has a style (a
homestead or a generated hamlet), from its style's row in ``tables.poi_styles`` (``hooks_<kind>``, plus
``hooks_<kind>_near``), with ``{name}`` the POI's own name and ``{near}`` the settlement's. A kind with neither (a
village no event dates) has an empty hook. Runs after the chronicle's text is rendered and the POIs are named; every
draw is keyed on the POI's cell, so a hook never depends on processing order. A later simulation calls
:func:`describe_hook` for a POI it mints.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config.model import Config
from ..util import rng
from ..world.entities import POI, REF_FALLEN, REF_POI
from ..world.world import World
from .render import render_template


def _remnant_of(world: World, poi: POI) -> int:
    """The id of the fallen realm a free settlement outlived (named by an event that marks it), or -1."""
    return next((fid for e in (world.chronicle[i] for i in poi.event_ids) for fid in e.fallen_ids), -1)


def _describe_free(world: World, config: Config, seed: int, index: int) -> bool:
    """Write the hook of a free settlement from its tier's ``hooks_free`` (``hooks_remnant`` for a remnant).

    Returns False when the tier has no such text, so the ordinary hook is written instead.
    """
    poi = world.pois[index]
    tier = config.get(f"tables.tiers.{poi.kind}", None) or {}
    fallen_id = _remnant_of(world, poi)
    pool = list(tier.get("hooks_remnant", [])) if fallen_id >= 0 else []
    pool = pool or list(tier.get("hooks_free", []))
    if not pool:
        return False
    fallen = world.fallen_realms[fallen_id].name if fallen_id >= 0 else ""
    tokens: dict[str, object] = {
        "name": poi.name,
        "fallen": "the " + fallen[4:] if fallen.startswith("The ") else fallen,
    }
    where = {"name": (REF_POI, index)}
    if fallen_id >= 0:
        where["fallen"] = (REF_FALLEN, fallen_id)
    stream = rng.derive(seed, "naming", "hook", poi.x, poi.y)
    poi.hook, poi.hook_refs = render_template(str(stream.choice(pool)), tokens, where)
    return True


def _pool(config: Config, poi: POI, near_index: int) -> list[str]:
    """The hook templates of a POI: its style's per-kind texts (``hooks_<kind>``, plus ``_near``) or its kind's row."""
    style = config.get(f"tables.poi_styles.{poi.style}", None) if poi.style else None
    if style is not None:
        pool = list(style.get(f"hooks_{poi.kind}", []))
        return pool + list(style.get(f"hooks_{poi.kind}_near", [])) if near_index >= 0 else pool
    row = config.get(f"tables.pois.{poi.kind}", None)
    pool = list(row.get("hooks", [])) if row else []
    return pool + list(row.get("hooks_near", [])) if row and near_index >= 0 else pool


def describe_hook(world: World, config: Config, seed: int, index: int, near_index: int) -> None:
    """Fill ``hook`` and ``hook_refs`` of ``world.pois[index]``; ``near_index`` is its qualifying settlement or -1."""
    poi: POI = world.pois[index]
    poi.hook, poi.hook_refs = "", []
    if poi.free and _describe_free(world, config, seed, index):
        return
    if poi.event_ids:
        event = world.chronicle[poi.event_ids[0]]
        poi.hook, poi.hook_refs = event.text, list(event.refs)
        return
    pool = _pool(config, poi, near_index)
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

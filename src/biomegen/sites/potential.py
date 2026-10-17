"""The largest a site could grow into: a settlement's *potential* (``POI.potential``).

A settlement's plan is drawn for its potential, never for its tier or population, so growth never redraws it (see
:mod:`biomegen.sites.manifest`). The potential is the best settlement tier whose two needs the site meets:

- **land**: the mean habitability of the dry land within ``sites.potential.radius_km`` (the biome's and the relief's
  habitability, as the settlements stage scores a cell) reaches the tier's ``potential_land``;
- **room**: the nearest other settlement of note is at least the tier's ``spacing_km`` times
  ``sites.potential.room_share`` away (a tier with ``near_target = false``, the hamlet, is not of note).

It is never less than what the POI already is (:func:`potential_floor`): the settlements stage hands out tiers by rank,
not by threshold, so a city placed on middling land keeps a city's plan. Pure, reads only small windows of the world,
and stored on the POI by :func:`assign_potentials` once every POI exists (so room sees the full set), or by whoever
mints a POI later (a simulation).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from ..config.model import Config
from ..world.entities import POI
from ..world.tile import BIOME_NAME, RELIEF_NAME, WaterType
from ..world.world import World


def _rank(config: Config, tier: str) -> int:
    return int(config.get(f"tables.tiers.{tier}.rank"))


def settlement_tier(config: Config, poi: POI) -> str:
    """Return the settlement tier ``poi`` is (a ruin: the tier it was), or an empty string when it is no settlement.

    A homestead is no settlement yet, whatever it may grow into.
    """
    tier = poi.ruin_of if poi.kind == "ruin" else poi.kind
    return tier if tier and config.get(f"tables.tiers.{tier}", None) is not None else ""


def potential_floor(config: Config, poi: POI) -> str:
    """Return the tier ``poi`` is at least, or an empty string for a POI that has no settlement plan.

    A settlement is its own tier, a ruin the tier it was (``ruin_of``) and a homestead whose style grows the tier it
    grows into; every other POI (towers, camps, a homestead that never grows) has none.
    """
    if poi.kind == "homestead":
        tier = str(config.get(f"tables.poi_styles.{poi.style}.grows_into", "")) if poi.style else ""
        return tier if tier and config.get(f"tables.tiers.{tier}", None) is not None else ""
    return settlement_tier(config, poi)


def plan_tier(config: Config, poi: POI) -> str:
    """Return the tier a settlement's plan is drawn for: its stored potential, else (a POI made by hand, with no pass
    run over it) the least it can be, :func:`potential_floor`. Empty for a POI with no settlement plan."""
    return poi.potential or potential_floor(config, poi)


def land_capacity(world: World, config: Config, poi: POI) -> float:
    """Return the mean habitability of the dry land within ``sites.potential.radius_km`` of ``poi`` (0 with none)."""
    radius = float(config.get("sites.potential.radius_km"))
    scale = world.scale
    rx, ry = max(1, math.ceil(radius / scale.km_per_col)), max(1, math.ceil(radius / scale.km_per_row))
    x0, x1 = max(0, poi.x - rx), min(world.width, poi.x + rx + 1)
    y0, y1 = max(0, poi.y - ry), min(world.height, poi.y + ry + 1)
    window = (slice(y0, y1), slice(x0, x1))
    yy, xx = np.ogrid[y0:y1, x0:x1]
    near = ((xx - poi.x) * scale.km_per_col) ** 2 + ((yy - poi.y) * scale.km_per_row) ** 2 <= radius**2
    land = near & (world.water_type[window] == int(WaterType.NONE))
    if not land.any():
        return 0.0
    base = config.table_array("biomes", "habitability", BIOME_NAME)[world.biome[window]]
    mul = config.table_array("relief", "habitability_mul", RELIEF_NAME)[world.relief[window]]
    return float((base * mul)[land].mean())


def _notable(world: World, config: Config) -> list[tuple[int, int, int]]:
    """Return ``(index, x, y)`` of every settlement of note (civilized, of a tier that counts), in POI order."""
    tiers = config.get("tables.tiers")
    return [
        (index, poi.x, poi.y)
        for index, poi in enumerate(world.pois)
        if poi.civilized and poi.kind in tiers and tiers[poi.kind].get("near_target", True)
    ]


def _room_km(world: World, index: int, poi: POI, notable: Sequence[tuple[int, int, int]]) -> float:
    """Return the km from ``poi`` (POI ``index``) to the nearest other settlement of note (infinity with none)."""
    others = [(x, y) for i, x, y in notable if i != index]
    if not others:
        return math.inf
    scale = world.scale
    points = np.array(others, dtype=np.float64)
    return float(np.hypot((points[:, 0] - poi.x) * scale.km_per_col, (points[:, 1] - poi.y) * scale.km_per_row).min())


def _choose(
    world: World, config: Config, index: int, poi: POI, notable: Sequence[tuple[int, int, int]], floor: str
) -> str:
    capacity = land_capacity(world, config, poi)
    room = _room_km(world, index, poi, notable)
    share = float(config.get("sites.potential.room_share"))
    tiers = config.get("tables.tiers")
    best = floor
    for tier in sorted(tiers, key=lambda name: _rank(config, name)):
        row = tiers[tier]
        if "potential_land" not in row or _rank(config, tier) >= _rank(config, best):
            continue
        if capacity >= float(row["potential_land"]) and room >= float(row["spacing_km"]) * share:
            return tier
    return best


def potential_tier(world: World, config: Config, poi: POI) -> str:
    """Return the potential of ``poi`` (see the module docstring), or an empty string when it has no settlement plan.

    ``poi`` may be one of ``world.pois`` or a POI not stored there yet (a simulation's mint); room is judged against the
    settlements of note that stand in ``world.pois``.
    """
    floor = potential_floor(config, poi)
    if not floor:
        return ""
    index = next((i for i, other in enumerate(world.pois) if other is poi), -1)
    return _choose(world, config, index, poi, _notable(world, config), floor)


def assign_potentials(world: World, config: Config) -> None:
    """Set ``POI.potential`` of every POI of ``world`` (call once every POI exists, so room sees them all)."""
    notable = _notable(world, config)
    for index, poi in enumerate(world.pois):
        floor = potential_floor(config, poi)
        poi.potential = _choose(world, config, index, poi, notable, floor) if floor else ""

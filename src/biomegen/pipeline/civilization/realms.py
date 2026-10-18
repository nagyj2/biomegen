"""Stage: realms - the political partition of solid land.

1. **Seeds.** Every capital founds a major realm. A city may found a city-state: with `politics.city_state_far_chance`
   when it is more than ``city_state_far_km`` from every capital, else with ``city_state_chance``. Each seed draws a
   claim strength from its kind's ``tables.realm_kinds.<kind>.strength`` span.
2. **Claiming.** A multi-source Dijkstra grows every realm over the move-cost surface (biome plus relief move cost, plus
   ``politics.river_cost`` on a river). A step costs its km length times the cell's move cost over the realm's strength,
   and a realm stops at ``claim_budget_km``. A realm may hop over salt water within ``coastal_hop_km`` of land at
   ``coastal_hop_cost``, so a coast reaches its islets; the hops are stepping stones and are never claimed.
3. **Tribes.** The largest unclaimed solid areas (at least ``tribe_min_area_km2``, at most ``tribe_max`` of them) each
   found a tribe, seated at the area's most populous settlement or else its most inland cell. Claiming then runs again
   with every seed, so tribes compete with the realms for the edge of their area.
4. **Record.** ``realm_id`` holds each solid cell's realm (-1 wild). A :class:`~biomegen.world.entities.Realm` records
   its seat, area, population, dominant biome and whether it is mostly highland; every POI takes the realm under its
   anchor.

Names, rulers and culture come from the naming stage, vassals and colours from diplomacy. Candidates tie-break in
row-major order (the heap orders by cost, then cell, then realm) and every draw is a ``realms`` sub-stream, so the
result does not depend on dict or set order.
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass

import numpy as np

from ...config.model import Config
from ...config.population import pop_scale
from ...util import geometry as geo
from ...util import rng
from ...world.entities import POI, Realm
from ...world.tile import BIOME_NAME, RELIEF_NAME, WATER_BIOMES, Relief, WaterType
from ...world.world import World

_NEIGHBOURS = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0))


@dataclass(frozen=True)
class _Seed:
    """A realm waiting to grow: its kind, claim strength, anchor cell and the POI that seats it (-1 for none)."""

    kind: str
    strength: float
    x: int
    y: int
    seat_poi: int


def solid_mask(world: World) -> np.ndarray:
    """Bool grid of the land a realm may hold: every cell whose cover is not water (a river keeps its land biome)."""
    return ~np.isin(world.biome, list(WATER_BIOMES))


def _enter_cost(world: World, config: Config, solid: np.ndarray) -> np.ndarray:
    """Cost of stepping into each cell: biome plus relief move cost (+ river cost), a hop cost on near sea, else inf."""
    land_cost = (
        config.table_array("biomes", "move_cost", BIOME_NAME)[world.biome]
        + config.table_array("relief", "move_cost", RELIEF_NAME)[world.relief]
        + float(config.get("politics.river_cost")) * (world.water_type == int(WaterType.FRESH))
    )
    near_land = geo.distance_to(
        solid, backend=config.get("compute.backend"), metric="euclidean", sampling=world.scale.sampling
    ) <= float(config.get("politics.coastal_hop_km"))
    hop = (world.water_type == int(WaterType.SALT)) & near_land
    return np.where(solid, land_cost, np.where(hop, float(config.get("politics.coastal_hop_cost")), np.inf))


def _claim(world: World, config: Config, enter: np.ndarray, solid: np.ndarray, seeds: list[_Seed]) -> np.ndarray:
    """Grow every seed over ``enter`` and return the owning seed index per cell (-1 unclaimed, water cells reset)."""
    width, height = world.width, world.height
    budget = float(config.get("politics.claim_budget_km"))
    km_col, km_row = world.scale.km_per_col, world.scale.km_per_row
    step_km = {(dx, dy): math.hypot(dx * km_col, dy * km_row) for dx, dy in _NEIGHBOURS}
    cost = enter.ravel().tolist()
    best = [math.inf] * (width * height)
    owner = [-1] * (width * height)
    heap: list[tuple[float, int, int]] = []
    for k, seed in enumerate(seeds):
        cell = seed.y * width + seed.x
        best[cell], owner[cell] = 0.0, k
        heap.append((0.0, cell, k))
    heapq.heapify(heap)
    while heap:
        spent, cell, k = heapq.heappop(heap)
        if spent > best[cell] or owner[cell] != k:
            continue
        strength = seeds[k].strength
        y, x = divmod(cell, width)
        for dx, dy in _NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            neighbour = ny * width + nx
            enter_cost = cost[neighbour]
            if enter_cost == math.inf:
                continue
            reach = spent + enter_cost * step_km[(dx, dy)] / strength
            if reach < best[neighbour] and reach <= budget:
                best[neighbour], owner[neighbour] = reach, k
                heapq.heappush(heap, (reach, neighbour, k))
    claimed = np.array(owner, dtype=np.int32).reshape(height, width)
    return np.where(solid, claimed, -1)


def _km_to_nearest(world: World, x: int, y: int, others: list[POI]) -> float:
    """Km from ``(x, y)`` to the nearest of ``others`` (``inf`` when there are none)."""
    return min((world.scale.distance_km(x, y, poi.x, poi.y) for poi in others), default=math.inf)


def _draw_strength(config: Config, kind: str, stream: random.Random) -> float:
    """Draw a claim strength from the kind's ``strength`` span."""
    lo, hi = (float(v) for v in config.get(f"tables.realm_kinds.{kind}.strength"))
    return stream.uniform(lo, hi)


def _settlement_seeds(world: World, config: Config, seed: int) -> list[_Seed]:
    """Major seeds from the capitals, then city-state seeds from the cities that qualify, in POI order."""
    capitals = [(i, p) for i, p in enumerate(world.pois) if p.kind == "capital"]
    strength = rng.derive(seed, "realms", "strength")
    seeds = [_Seed("major", _draw_strength(config, "major", strength), p.x, p.y, i) for i, p in capitals]
    far_km = float(config.get("politics.city_state_far_km"))
    far_chance = float(config.get("politics.city_state_far_chance"))
    chance = float(config.get("politics.city_state_chance"))
    stream = rng.derive(seed, "realms", "city_state")
    for i, poi in enumerate(world.pois):
        if poi.kind != "city":
            continue
        far_roll, any_roll = stream.random(), stream.random()  # both always drawn, so the stream stays aligned
        far = _km_to_nearest(world, poi.x, poi.y, [p for _, p in capitals]) > far_km
        if (far and far_roll < far_chance) or any_roll < chance:
            seeds.append(_Seed("city_state", _draw_strength(config, "city_state", strength), poi.x, poi.y, i))
    return seeds


def _tribe_seeds(world: World, config: Config, seed: int, solid: np.ndarray, owner: np.ndarray) -> list[_Seed]:
    """One tribe per large unclaimed solid area, largest first, seated at its top settlement or most inland cell."""
    free = solid & (owner < 0)
    if not free.any():
        return []
    labels, _ = geo.label_by_value(free.astype(np.uint8), connectivity=8, backend=config.get("compute.backend"))
    ids, counts = np.unique(labels[free], return_counts=True)
    first_cell = {int(i): int(np.argmax((labels == i).ravel())) for i in ids}  # row-major first cell, for ties
    order = sorted(zip(ids.tolist(), counts.tolist(), strict=True), key=lambda c: (-c[1], first_cell[c[0]]))
    min_cells = float(config.get("politics.tribe_min_area_km2")) / world.scale.cell_area_km2
    strength = rng.derive(seed, "realms", "tribe")
    seeds: list[_Seed] = []
    for label, count in order[: int(config.get("politics.tribe_max"))]:
        if count < min_cells:
            break
        area = labels == label
        members = [(p.pop, -i, i) for i, p in enumerate(world.pois) if p.civilized and area[p.y, p.x]]
        if members:
            seat = max(members)[2]
            x, y = world.pois[seat].x, world.pois[seat].y
        else:
            seat = -1
            y, x = divmod(int(np.argmax(np.where(area, world.dist_to_ocean, -np.inf))), world.width)
        seeds.append(_Seed("tribal", _draw_strength(config, "tribal", strength), x, y, seat))
    return seeds


def population(
    world: World, config: Config, stream: random.Random, kind: str, mine: np.ndarray, area_km2: float
) -> int:
    """Return a realm's people: those in its settlements and homesteads, a share of them again living outside them
    (``outside_share``) and some living off the land (``rural_per_km2`` over the realm's area). Both terms are drawn
    per realm, so each has its own jitter, and a realm's total follows its places instead of its area."""
    row = config.get(f"tables.realm_kinds.{kind}")
    settled = sum(p.pop for p in world.pois if (p.civilized or p.kind == "homestead") and mine[p.y, p.x])
    share = stream.uniform(*(float(v) for v in row["outside_share"]))
    rural = stream.uniform(*(float(v) for v in row["rural_per_km2"])) * pop_scale(config)  # drawn first, then scaled
    return settled + int(settled * share) + int(area_km2 * rural)


def recount_population(world: World, config: Config, seed: int) -> None:
    """Set every realm's people again from its settlements, hamlets and homesteads (placed after the realms)."""
    stream = rng.derive(seed, "realms", "population", "recount")
    for realm in world.realms:
        mine = world.realm_id == realm.id
        realm.pop = population(world, config, stream, realm.kind, mine, realm.area_km2)


def _describe(
    world: World, config: Config, stream: random.Random, seed_index: int, seed: _Seed, owner: np.ndarray
) -> Realm:
    """Build the :class:`Realm` of ``seed``: area, dominant biome, highland flag and population."""
    mine = owner == seed_index
    cells = int(mine.sum())
    biomes = np.bincount(world.biome[mine].astype(np.int64), minlength=1)
    relief_cells = int((world.relief[mine] != int(Relief.NONE)).sum())
    area_km2 = cells * world.scale.cell_area_km2
    people = population(world, config, stream, seed.kind, mine, area_km2)
    return Realm(
        id=seed_index,
        kind=seed.kind,
        seat_poi=seed.seat_poi,
        area_km2=area_km2,
        pop=people,
        dominant_biome=int(np.argmax(biomes)),
        highland=relief_cells > cells // 2 if cells else False,
    )


def run(world: World, config: Config, seed: int) -> None:
    """Claim land for every realm, fill ``realm_id``, ``world.realms`` and each POI's ``realm_id``."""
    solid = solid_mask(world)
    enter = _enter_cost(world, config, solid)
    seeds = _settlement_seeds(world, config, seed)
    owner = _claim(world, config, enter, solid, seeds)
    seeds += _tribe_seeds(world, config, seed, solid, owner)
    owner = _claim(world, config, enter, solid, seeds)

    world.realm_id = owner.astype(np.int16)
    stream = rng.derive(seed, "realms", "population")
    world.realms = [_describe(world, config, stream, k, s, owner) for k, s in enumerate(seeds)]
    for poi in world.pois:
        poi.realm_id = int(world.realm_id[poi.y, poi.x])

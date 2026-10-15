"""Stage: diplomacy - vassalage, colours, relations and war fronts between the realms.

1. **Borders.** The shared border of every realm pair, in km, counted along the edges between 4-adjacent solid cells.
2. **Vassalage.** Majors take their turn smallest first: one with no vassals may swear fealty, with the kind's
   ``vassal_chance``, to the neighbouring independent major sharing the longest border if that major is at least
   ``politics.vassal_area_ratio`` times its area. A city-state or tribe may swear fealty to any neighbouring major.
   Only leaves swear to a larger realm, so the tree of lieges has no cycles.
3. **Colours.** Majors take golden-ratio hues; a vassal takes a paler shade of its overlord's hue; city-states are
   vivid and tribes muted (``tables.realm_colors``).
4. **Relations.** Between the independent powers (the tops of the vassal trees) that share a border: war, rivalry,
   alliance, trade or nothing, by ``tables.relation_weights``; at least one war when any border exists. Two far-apart
   independent majors may add one pact across the sea. A relation's ``why`` is a raw reason template; the naming stage
   fills in the places.
5. **Fronts.** A war marks the border cells between its two powers in ``World.front``, picks an attacker by a coin
   toss and claims the defender's settlement nearest the border (a capital is never claimed).

Every draw comes from a ``diplomacy`` sub-stream in a fixed order (realms by id, border pairs by length then id), so
the result does not depend on dict or set order.
"""

from __future__ import annotations

import colorsys
import random
import string
from dataclasses import dataclass

import numpy as np

from ...config.model import Config
from ...util import rng
from ...world.entities import Realm, Relation
from ...world.world import World
from ..story.places import nearest_feature

Pair = tuple[int, int]


@dataclass(frozen=True)
class _Edges:
    """The edges between 4-adjacent solid cells of different realms, in row-major order.

    ``low`` and ``high`` are the realm ids (``low < high``), ``cell_a`` and ``cell_b`` the flat indices of the two
    cells and ``length_km`` the length of the edge between them.
    """

    low: np.ndarray
    high: np.ndarray
    cell_a: np.ndarray
    cell_b: np.ndarray
    length_km: np.ndarray


def _edges(world: World) -> _Edges:
    """Collect every realm-to-realm edge: horizontal neighbours share a border as tall as a row, vertical as wide."""
    ids = world.realm_id.astype(np.int32)
    flat = np.arange(world.width * world.height).reshape(world.height, world.width)
    pairs = (
        (ids[:, :-1], ids[:, 1:], flat[:, :-1], flat[:, 1:], world.scale.km_per_row),
        (ids[:-1, :], ids[1:, :], flat[:-1, :], flat[1:, :], world.scale.km_per_col),
    )
    parts: list[tuple[np.ndarray, ...]] = []
    for a, b, cell_a, cell_b, length in pairs:
        mask = (a >= 0) & (b >= 0) & (a != b)
        parts.append(
            (
                np.minimum(a, b)[mask],
                np.maximum(a, b)[mask],
                cell_a[mask],
                cell_b[mask],
                np.full(int(mask.sum()), length),
            )
        )
    return _Edges(*(np.concatenate([part[k] for part in parts]) for k in range(5)))


def _border_km(edges: _Edges) -> dict[Pair, float]:
    """Total border length per ``(low, high)`` pair, with the pairs in ascending order."""
    totals: dict[Pair, float] = {}
    for low, high, length in zip(edges.low.tolist(), edges.high.tolist(), edges.length_km.tolist(), strict=True):
        totals[(low, high)] = totals.get((low, high), 0.0) + length
    return dict(sorted(totals.items()))


def _neighbours(borders: dict[Pair, float]) -> dict[int, dict[int, float]]:
    """Shared border km per realm, keyed by the neighbour."""
    nbrs: dict[int, dict[int, float]] = {}
    for (a, b), km in borders.items():
        nbrs.setdefault(a, {})[b] = km
        nbrs.setdefault(b, {})[a] = km
    return nbrs


def _swear(realms: list[Realm], vassal: int, liege: int) -> None:
    realms[vassal].liege = liege
    realms[liege].vassals.append(vassal)


def _vassalage(world: World, config: Config, seed: int, nbrs: dict[int, dict[int, float]]) -> None:
    """Let smaller majors, then city-states and tribes, swear fealty to neighbouring majors."""
    realms = world.realms
    stream = rng.derive(seed, "diplomacy", "vassals")
    ratio = float(config.get("politics.vassal_area_ratio"))

    def chance(realm: Realm) -> float:
        return float(config.get(f"tables.realm_kinds.{realm.kind}.vassal_chance"))

    def strongest_border(realm: Realm, options: list[int]) -> int:
        return max(options, key=lambda other: (nbrs[realm.id][other], -other))

    for realm in sorted((r for r in realms if r.kind == "major"), key=lambda r: (r.area_km2, r.id)):
        roll = stream.random()  # always drawn, so the stream stays aligned whatever the neighbours are
        options = [
            o
            for o in sorted(nbrs.get(realm.id, {}))
            if realms[o].kind == "major" and realms[o].liege < 0 and realms[o].area_km2 >= ratio * realm.area_km2
        ]
        if options and not realm.vassals and roll < chance(realm):
            _swear(realms, realm.id, strongest_border(realm, options))
    for realm in realms:
        if realm.kind == "major":
            continue
        roll = stream.random()
        options = [o for o in sorted(nbrs.get(realm.id, {})) if realms[o].kind == "major"]
        if options and roll < chance(realm):
            _swear(realms, realm.id, strongest_border(realm, options))
    for realm in realms:
        realm.vassals.sort()


def _colour(role: dict[str, float], hue: float) -> tuple[int, int, int]:
    red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, float(role["saturation"]), float(role["value"]))
    return int(red * 255), int(green * 255), int(blue * 255)


def _colours(world: World, config: Config, seed: int) -> None:
    """Give every realm its colour: majors by golden-ratio hue, vassals a paler shade of their top's hue."""
    realms = world.realms
    stream = rng.derive(seed, "diplomacy", "colours")
    step = float(config.get("politics.hue_step"))
    rows = config.get("tables.realm_colors")
    golden = stream.random()
    hue_of = {r.id: golden + n * step for n, r in enumerate(r for r in realms if r.kind == "major")}
    for n, realm in enumerate(realms):
        if realm.liege >= 0:
            role = rows["vassal"]
            jitter = float(role["hue_jitter"])
            hue = hue_of[world.top_realm(realm.id)] + stream.uniform(-jitter, jitter)
        elif realm.kind == "major":
            role, hue = rows["major"], hue_of[realm.id]
        else:
            role = rows[realm.kind]
            hue = golden + float(role["hue_offset"]) + n * step
        realm.color = _colour(role, hue)


def _draw_kind(stream: random.Random, weights: dict[str, float]) -> str | None:
    """Draw a relation kind (``None`` for no relation) by ``weights``, keys in the fixed war..none order."""
    names = ("war", "rivalry", "alliance", "trade", "none")
    pick = stream.choices(names, [float(weights[name]) for name in names])[0]
    return None if pick == "none" else pick


def _relations(world: World, config: Config, seed: int, top_borders: dict[Pair, float]) -> list[Relation]:
    """Draw a relation for every pair of independent powers sharing a border, and one pact across the sea."""
    realms = world.realms
    stream = rng.derive(seed, "diplomacy", "relations")
    rows = config.get("tables.relation_weights")
    ranked = sorted(top_borders, key=lambda pair: (-top_borders[pair], pair))
    relations: list[Relation] = []
    for a, b in ranked:
        both_major = realms[a].kind == "major" and realms[b].kind == "major"
        kind = _draw_kind(stream, rows["major_pair" if both_major else "other_pair"])
        if kind is not None:
            relations.append(Relation(a=a, b=b, kind=kind, border_km=top_borders[(a, b)]))
    if ranked and not any(r.kind == "war" for r in relations):
        a, b = ranked[0]
        relations = [r for r in relations if (r.a, r.b) != (a, b)]
        relations.append(Relation(a=a, b=b, kind="war", border_km=top_borders[(a, b)]))
    independent = [r.id for r in realms if r.kind == "major" and r.liege < 0]
    far = [(a, b) for a in independent for b in independent if a < b and (a, b) not in top_borders]
    if far:
        a, b = stream.choice(far)
        kind = stream.choice(sorted(config.get("politics.sea_pact_kinds")))
        relations.append(Relation(a=a, b=b, kind=kind))
    return relations


def _war(
    world: World, config: Config, edges: _Edges, tops: np.ndarray, relation: Relation, stream: random.Random
) -> None:
    """Mark the border cells of a war on ``World.front``, choose the attacker and claim a defending town."""
    low, high = tops[edges.low], tops[edges.high]
    sel = (np.minimum(low, high) == relation.a) & (np.maximum(low, high) == relation.b)
    cells = np.column_stack([edges.cell_a[sel], edges.cell_b[sel]]).ravel()
    world.front.reshape(-1)[cells] = True
    attacker, defender = (relation.a, relation.b) if stream.random() < 0.5 else (relation.b, relation.a)
    relation.attacker = attacker
    targets = [
        i
        for i, poi in enumerate(world.pois)
        if poi.civilized and poi.kind != "capital" and poi.realm_id >= 0 and int(tops[poi.realm_id]) == defender
    ]
    if not targets or cells.size == 0:
        return
    sample = cells[:: max(1, cells.size // int(config.get("politics.claim_samples")))]
    xs, ys = sample % world.width, sample // world.width
    scale = world.scale

    def nearest_km(index: int) -> float:
        poi = world.pois[index]
        return float(np.hypot((xs - poi.x) * scale.km_per_col, (ys - poi.y) * scale.km_per_row).min())

    relation.claim_poi = min(targets, key=lambda i: (nearest_km(i), i))


_PLACE_TOKENS = ("river", "range", "sea")


def _reason_points(world: World, relation: Relation) -> list[tuple[int, int]]:
    """The cells a reason's places are measured from: the border of the two powers, else their seats."""
    if relation.border_km > 0:
        flat = front_cells(world, relation.a, relation.b).tolist()
        return [(index % world.width, index // world.width) for index in flat]
    seats = [world.realms[r].seat_poi for r in (relation.a, relation.b)]
    return [(world.pois[seat].x, world.pois[seat].y) for seat in seats if seat >= 0]


def _word(world: World, config: Config, relation: Relation, stream: random.Random) -> None:
    """Pick the relation's raw reason template, only one whose river, range or sea lies near the border.

    The chosen template's place tokens are recorded in ``relation.places`` (token -> feature id) for naming to word.
    A template whose place is far away is dropped; when none qualifies the whole list stays and naming uses the
    fallback words of ``tables.reason_tokens``.
    """
    templates = list(config.get(f"tables.reasons.{relation.kind}.templates"))
    used = {template: _place_tokens(template) for template in templates}
    wanted = {token for tokens in used.values() for token in tokens}
    points = _reason_points(world, relation) if wanted else []
    near = {token: pick for token in sorted(wanted) if (pick := nearest_feature(world, config, token, points)) >= 0}
    allowed = [t for t in templates if used[t] <= set(near)]
    chosen = stream.choice(allowed or templates)
    relation.why = chosen
    relation.places = {token: near[token] for token in sorted(used[chosen]) if token in near}


def _place_tokens(template: str) -> set[str]:
    """The ``{river}``, ``{range}`` and ``{sea}`` tokens a reason template uses."""
    return {field for _, field, _, _ in string.Formatter().parse(template) if field in _PLACE_TOKENS}


def front_cells(world: World, a: int, b: int) -> np.ndarray:
    """Return the sorted flat indices of the cells along the border of independent powers ``a`` and ``b``.

    A cell counts when it is next to a cell of the other power's realms (both sides of the border), so the result is
    what a war between the two marks on ``World.front``.
    """
    tops = np.array([world.top_realm(r.id) for r in world.realms], dtype=np.int32)
    edges = _edges(world)
    low, high = tops[edges.low], tops[edges.high]
    sel = (np.minimum(low, high) == min(a, b)) & (np.maximum(low, high) == max(a, b))
    return np.unique(np.concatenate([edges.cell_a[sel], edges.cell_b[sel]]))


def run(world: World, config: Config, seed: int) -> None:
    """Fill vassals, colours, relations and ``front``, mutating ``world`` in place."""
    realms = world.realms
    world.front[:] = False
    world.relations = []
    if not realms:
        return
    edges = _edges(world)
    borders = _border_km(edges)
    nbrs = _neighbours(borders)
    _vassalage(world, config, seed, nbrs)
    _colours(world, config, seed)

    tops = np.array([world.top_realm(r.id) for r in realms], dtype=np.int32)
    top_borders: dict[Pair, float] = {}
    for (a, b), km in borders.items():
        pair = (min(int(tops[a]), int(tops[b])), max(int(tops[a]), int(tops[b])))
        if pair[0] != pair[1]:
            top_borders[pair] = top_borders.get(pair, 0.0) + km
    world.relations = _relations(world, config, seed, dict(sorted(top_borders.items())))

    stream = rng.derive(seed, "diplomacy", "reasons")
    for relation in world.relations:
        if relation.kind == "war":
            _war(world, config, edges, tops, relation, stream)
        _word(world, config, relation, stream)

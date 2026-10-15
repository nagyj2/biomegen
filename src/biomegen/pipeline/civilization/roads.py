"""Stage 9: roads.

Connects POIs with meandering least-cost roads. A road tile over water is a bridge: the renderer and the site
plans draw it from the road alone, so no bridge is recorded. A diagonal step between two land tiles that passes
between two water corners records nothing on the water: the diagonal link itself is drawn as the bridge. The
design has three parts:

1. **Landmass grouping.** A "landmass" is everything that is not open saltwater (``water_type != SALT``)
   - i.e. land plus the rivers/lakes embedded in it. Components of that mask are the islands. POIs are
   grouped by the component under their anchor, and a road is only ever routed *within* one component,
   so roads structurally cannot cross the open ocean (and a river slicing an island does not split it).
2. **Connection graph (per component).** k-nearest-neighbour candidate edges (km) → a minimum spanning tree
   over the backbone tiers (``tables.tiers.<tier>.backbone``: capitals, cities, towns; villages are spurs; falls
   back to all POIs if a component has none) →
   probabilistically attach the remaining POIs (civilized more likely than uncivilized) → a few extra
   loop edges. All random draws come from one per-component RNG consumed in a fixed sorted edge order.
3. **Routing.** Each selected edge is routed with A* (eight directions, or four with ``roads.cardinal_only``) over a
   precomputed cost surface (the biome and relief ``move_cost`` rows; slopes and water are dear; existing road is
   discounted; a smooth noise field adds meander). Step lengths are km, so a north-south step costs more than an
   east-west one on a tall cell. The search is confined to the component's mask and a padded bounding box and
   capped, with a straight-line fallback, so it stays fast on the non-monotone cost.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple, cast

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...util import noise, rng
from ...world.entities import POI
from ...world.tile import BIOME_NAME, RELIEF_NAME, WaterType
from ...world.world import World

Coord = Tuple[int, int]
_SETTLEMENT_KINDS = frozenset({"capital", "city", "town", "village"})


# --------------------------------------------------------------------------- union-find (Kruskal MST)
class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[rb] = ra
        return True


def _road_eligible(world: World) -> List[Tuple[int, "POI"]]:
    """Land POIs eligible to be road endpoints (those with ``connect``; water-anchored POIs excluded), by index."""
    out = []
    for i, p in enumerate(world.pois):
        if not p.connect:
            continue
        if world.water_type[p.y, p.x] != int(WaterType.NONE):
            continue
        out.append((i, p))
    return out


def _endpoint(poi: "POI") -> Coord:
    """Road endpoint for a POI: its anchor."""
    return (poi.x, poi.y)


def _candidate_edges(coords: List[Tuple[float, float]], k: int) -> List[Tuple[int, int, float]]:
    """k-nearest-neighbour undirected candidate edges, deduped and sorted by (dist^2, i, j)."""
    m = len(coords)
    pts = np.array(coords, dtype=np.float64)
    seen = set()
    edges: List[Tuple[int, int, float]] = []
    kk = max(1, min(k, m - 1))
    for i in range(m):
        d2 = (pts[:, 0] - pts[i, 0]) ** 2 + (pts[:, 1] - pts[i, 1]) ** 2
        d2[i] = np.inf
        for j in np.argsort(d2, kind="stable")[:kk].tolist():
            a, b = (i, j) if i < j else (j, i)
            if a != b and (a, b) not in seen:
                seen.add((a, b))
                edges.append((a, b, float(d2[j])))
    edges.sort(key=lambda e: (e[2], e[0], e[1]))
    return edges


def _classify_edges(
    km_coords: List[Tuple[float, float]],
    civ_flags: List[bool],
    backbone_flags: List[bool],
    k: int,
    edge_rng: random.Random,
    probs: Tuple[float, float, float],
) -> Tuple[List[Tuple[int, int]], List[int]]:
    """Split connections into trunk edges and spur node indices.

    Trunk edges are a minimum spanning tree over *every pair* of backbone-tier settlements (so no backbone node
    is left out because its nearest neighbours are villages), plus a few extra loop edges drawn from each
    backbone node's ``k`` nearest backbone neighbours. Spur nodes are the other POIs that should branch off the
    road network; they are routed to the nearest existing road tile after the trunk is built rather than to a
    specific POI, which prevents the parallel-road problem caused by many POIs independently targeting the same
    distant destination. ``km_coords`` are positions in km, so distances are aspect-aware.

    Returns ``(trunk_edges, spur_node_indices)``.
    """
    m = len(km_coords)
    civ_prob, unciv_prob, extra_prob = probs
    backbone = sorted({i for i in range(m) if backbone_flags[i]} or set(range(m)))
    backbone_set = set(backbone)

    # 1. Kruskal MST over all backbone pairs, shortest first (ties by index) - this forms the trunk.
    pairs = sorted(
        (
            (km_coords[i][0] - km_coords[j][0]) ** 2 + (km_coords[i][1] - km_coords[j][1]) ** 2,
            i,
            j,
        )
        for n, i in enumerate(backbone)
        for j in backbone[n + 1 :]
    )
    uf = _UnionFind(m)
    trunk_edges: List[Tuple[int, int]] = []
    for _d2, i, j in pairs:
        if uf.union(i, j):
            trunk_edges.append((i, j))

    # 2. Collect non-backbone nodes to attach as spurs (probabilistic, civilized more likely).
    spur_nodes: List[int] = []
    for node in sorted(set(range(m)) - backbone_set):
        prob = civ_prob if civ_flags[node] else unciv_prob
        if edge_rng.random() < prob:
            spur_nodes.append(node)

    # 3. Extra loop edges between near backbone neighbours reinforce the trunk (not spurs).
    chosen = set(trunk_edges)
    if len(backbone) > 1:
        near = _candidate_edges([km_coords[i] for i in backbone], k)
        for a, b, _w in near:
            edge = (backbone[a], backbone[b])
            if edge not in chosen and edge_rng.random() < extra_prob:
                trunk_edges.append(edge)
                chosen.add(edge)

    return trunk_edges, spur_nodes


def _meander_field(world: World, config: Config, seed: int) -> np.ndarray:
    """A smooth low-frequency noise field (scaled by meander_strength) that bends roads naturally."""
    strength = float(config.get("roads.meander_strength"))
    base = float(config.get("roads.base_cost"))
    if strength <= 0:
        return np.zeros((world.height, world.width), dtype=np.float64)
    sampler = noise.get_sampler(config.get("terrain.noise_backend"), rng.derive_int(seed, "roads.meander"))
    cx, cy = noise.coordinate_grid((world.height, world.width), 16.0)
    field = noise.normalize01(noise.fbm(sampler, cx, cy, octaves=3, persistence=0.5, lacunarity=2.0))
    return (field * strength * base).astype(np.float64)


def _bresenham(a: Coord, b: Coord) -> List[Coord]:
    """Integer line from a to b (fallback road when A* is bailed out)."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    cells = []
    while True:
        cells.append((x0, y0))
        if (x0, y0) == (x1, y1):
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return cells


def _l_path(a: Coord, b: Coord) -> List[Coord]:
    """Cardinal fallback line from a to b: along the row to b's column, then along the column."""
    (x0, y0), (x1, y1) = a, b
    step_x = 1 if x1 >= x0 else -1
    step_y = 1 if y1 >= y0 else -1
    return [(x, y0) for x in range(x0, x1, step_x)] + [(x1, y) for y in range(y0, y1 + step_y, step_y)]


def _route(
    world: World,
    comp_mask: np.ndarray,
    enter_base: np.ndarray,
    a: Coord,
    b: Coord,
    costs: Tuple[float, float, float, float],
    turn_cost: float = 0.0,
    settlement: np.ndarray | None = None,
    cardinal_only: bool = False,
) -> List[Coord]:
    """A* route a→b within the component mask + padded bbox; straight-line fallback if it bails.

    With ``cardinal_only`` a step goes north, east, south or west (never diagonally), and the fallback is an L.

    When turn_cost > 0, state is augmented with the incoming direction (x, y, dx, dy) so that
    direction changes incur an extra flat penalty. This reduces zigzagging caused by the meander
    noise field without affecting path topology on smooth terrain.
    """
    h, w = world.height, world.width
    col_km, row_km = world.scale.km_per_col, world.scale.km_per_row  # a step costs its km length over col_km
    adjacent = geo.neighbors4 if cardinal_only else geo.neighbors8
    elev = world.elevation_m / 1000.0  # km, so the slope costs are per km of height change
    road = world.road
    slope_cost, uphill, discount, base_cost = costs

    pad = max(8, int(0.5 * geo.octile_distance(a, b)) + 1)
    x0 = max(0, min(a[0], b[0]) - pad)
    x1 = min(w - 1, max(a[0], b[0]) + pad)
    y0 = max(0, min(a[1], b[1]) - pad)
    y1 = min(h - 1, max(a[1], b[1]) + pad)
    bbox_area = (x1 - x0 + 1) * (y1 - y0 + 1)

    if turn_cost <= 0.0:
        # Fast path: position-only state, existing behaviour.
        def neighbors(node):
            nx0, ny0 = node
            return [
                (nx, ny)
                for (nx, ny) in adjacent(nx0, ny0, w, h)
                if x0 <= nx <= x1 and y0 <= ny <= y1 and comp_mask[ny, nx]
            ]

        def cost(p, q) -> float:
            qx, qy = cast(Coord, q)
            dist = geo.step_length(cast(Coord, p), (qx, qy), col_km, row_km) / col_km
            de = float(elev[qy, qx] - elev[p[1], p[0]])
            c = (enter_base[qy, qx] + slope_cost * abs(de) + (uphill * de if de > 0 else 0.0)) * dist
            if road[qy, qx] or (settlement is not None and settlement[qy, qx]):
                c *= discount
            return float(c)

        cap = min(40000, 8 * bbox_area)
        path = geo.astar(
            a,
            b,
            neighbors,
            cost,
            heuristic_fn=lambda n, g: (
                geo.octile_distance(cast(Coord, n), cast(Coord, g), col_km, row_km) / col_km * base_cost
            ),
            max_expansions=cap,
        )
    else:
        # Direction-aware path: state = (x, y, dx, dy).  Turn changes add turn_cost.
        # State space is ~9× larger, so we raise the expansion cap proportionally.
        start_state = (a[0], a[1], 0, 0)
        gx, gy = b

        def dir_neighbors(state):
            sx, sy, _pdx, _pdy = state
            return [
                (nx, ny, nx - sx, ny - sy)
                for (nx, ny) in adjacent(sx, sy, w, h)
                if x0 <= nx <= x1 and y0 <= ny <= y1 and comp_mask[ny, nx]
            ]

        def dir_cost(p_state, q_state) -> float:
            px, py, pdx, pdy = cast(tuple, p_state)
            qx, qy, qdx, qdy = cast(tuple, q_state)
            dist = math.hypot(qdx * col_km, qdy * row_km) / col_km
            de = float(elev[qy, qx] - elev[py, px])
            c = (enter_base[qy, qx] + slope_cost * abs(de) + (uphill * de if de > 0 else 0.0)) * dist
            if road[qy, qx] or (settlement is not None and settlement[qy, qx]):
                c *= discount
            # First step has no prior direction (pdx, pdy) == (0, 0) — no penalty there.
            if (pdx, pdy) != (0, 0) and (qdx, qdy) != (pdx, pdy):
                c += turn_cost
            return float(c)

        def _dir_heuristic(n, g) -> float:
            nt = cast(tuple, n)
            return geo.octile_distance(cast(Coord, (nt[0], nt[1])), cast(Coord, g), col_km, row_km) / col_km * base_cost

        def _dir_goal(s) -> bool:
            st = cast(tuple, s)
            return (st[0], st[1]) == (gx, gy)

        cap = min(80000, 24 * bbox_area)
        raw = geo.astar(
            start_state,
            b,
            dir_neighbors,
            dir_cost,
            heuristic_fn=_dir_heuristic,
            max_expansions=cap,
            goal_fn=_dir_goal,
        )
        path = [(cast(tuple, s)[0], cast(tuple, s)[1]) for s in raw] if raw is not None else None

    if path is None:
        # Fallback: stamp a straight line so the edge still produces a road.
        # Exclude SALT tiles — they are outside the landmass component and must never carry roads.
        path = [
            (x, y)
            for (x, y) in (_l_path(a, b) if cardinal_only else _bresenham(a, b))
            if world.in_bounds(x, y) and world.water_type[y, x] != int(WaterType.SALT)
        ]
    return _straighten_coastal_detours(world, cast(List[Coord], path))


def _straighten_coastal_detours(world: World, path: List[Coord]) -> List[Coord]:
    """Replace V-shaped fresh-water detours around a single ocean corner with a straight crossing.

    A* excludes SALT tiles from its search space, so when a 1-tile ocean corner sits between two
    land tiles it routes diagonally through a neighbouring river or land tile instead — a visible
    kink.  Whenever the path forms a clean V  (x,y)→(x+dx,y+dy)→(x+2dx,y)  where the skipped
    corner (x+dx, y) is SALT and the detour tile (x+dx, y+dy) is FRESH water, we replace the
    detour tile with the ocean corner.  The bridge step then places a single bridge on the ocean
    tile and the road row stays straight.
    """
    if len(path) < 3:
        return path
    result = list(path)
    i = 0
    while i < len(result) - 2:
        x0, y0 = result[i]
        x1, y1 = result[i + 1]
        x2, y2 = result[i + 2]
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) == 1 and abs(dy) == 1:
            # Horizontal V: returns to same row two steps later
            if y2 == y0 and x2 == x0 + 2 * dx:
                corner = (x1, y0)
                if (
                    world.in_bounds(corner[0], corner[1])
                    and world.water_type[y0, x1] == int(WaterType.SALT)
                    and world.water_type[y1, x1] == int(WaterType.FRESH)
                ):
                    result[i + 1] = corner
                    i += 2
                    continue
            # Vertical V: returns to same column two steps later
            if x2 == x0 and y2 == y0 + 2 * dy:
                corner = (x0, y1)
                if (
                    world.in_bounds(corner[0], corner[1])
                    and world.water_type[y1, x0] == int(WaterType.SALT)
                    and world.water_type[y1, x1] == int(WaterType.FRESH)
                ):
                    result[i + 1] = corner
                    i += 2
                    continue
        i += 1
    return result


_WATER_RANK = {int(WaterType.NONE): 0, int(WaterType.FRESH): 1, int(WaterType.SALT): 2}  # land first, open sea last


def _close_diagonals(world: World) -> None:
    """Join road tiles that touch only at a corner by making one of the two tiles between them road.

    Two roads of a cardinal-only network can pass each other corner to corner; drawn as the map or a bed, that
    reads as a diagonal link the router never made. The corner chosen is the land one, else a river one (row-major
    first), so a pair split by open sea on both sides stays as it is. The new tile takes the higher tier of the pair.
    """
    road = world.road > 0
    height, width = road.shape
    for y in range(height - 1):
        for x in range(width):
            if not road[y, x]:
                continue
            for dx in (1, -1):
                nx = x + dx
                if not (0 <= nx < width) or not road[y + 1, nx] or road[y, nx] or road[y + 1, x]:
                    continue
                corners = sorted(
                    ((x, y + 1), (nx, y)), key=lambda c: (_WATER_RANK[int(world.water_type[c[1], c[0]])], c[1], c[0])
                )
                cx, cy = corners[0]
                if world.water_type[cy, cx] == int(WaterType.SALT):
                    continue
                world.road[cy, cx] = 1
                world.road_tier[cy, cx] = max(int(world.road_tier[y, x]), int(world.road_tier[y + 1, nx]))
                road[cy, cx] = True


@dataclass
class _Network:
    """What both road passes share: the landmass labels, the cost surface and the routing settings."""

    labels: np.ndarray
    groups: Dict[int, List[Tuple[int, "POI"]]]
    enter_base: np.ndarray
    costs: Tuple[float, float, float, float]
    turn_cost: float
    cardinal_only: bool
    settlement: np.ndarray


def _network(world: World, config: Config, seed: int, eligible: List[Tuple[int, "POI"]]) -> _Network:
    """Group ``eligible`` POIs by landmass component and precompute the static entry-cost surface."""
    # 1. Group eligible POIs by landmass component (ocean separates islands; rivers/lakes do not).
    landmass = world.water_type != int(WaterType.SALT)
    labels, _ = geo.label_by_value(landmass.astype(np.uint8), connectivity=8, backend=config.get("compute.backend"))
    groups: Dict[int, List[Tuple[int, "POI"]]] = {}
    for idx, poi in eligible:
        groups.setdefault(int(labels[poi.y, poi.x]), []).append((idx, poi))

    # 2. Precompute the static entry-cost surface (biome and relief move costs, water penalty, meander noise).
    base_cost = float(config.get("roads.base_cost"))
    enter_base = (
        base_cost * config.table_array("biomes", "move_cost", BIOME_NAME)[world.biome]
        + config.table_array("relief", "move_cost", RELIEF_NAME)[world.relief]
        + float(config.get("roads.water_cost")) * (world.water_type != int(WaterType.NONE))
        + _meander_field(world, config, seed)
    ).astype(np.float64)
    costs = (
        float(config.get("roads.slope_cost_per_km")),
        float(config.get("roads.uphill_surcharge_per_km")),
        float(config.get("roads.road_discount")),
        base_cost,
    )
    # Settlement tiles attract roads exactly as existing road tiles do (same discount factor).
    settlement = np.zeros((world.height, world.width), dtype=bool)
    for poi in world.pois:
        if poi.kind in _SETTLEMENT_KINDS:
            settlement[poi.y, poi.x] = True
    return _Network(
        labels,
        groups,
        enter_base,
        costs,
        float(config.get("roads.turn_cost")),
        bool(config.get("roads.cardinal_only")),
        settlement,
    )


def _lay(world: World, network: _Network, comp_mask: np.ndarray, a: Coord, b: Coord, tier: int) -> None:
    """Route ``a`` to ``b`` and write the path into the road arrays (``tier`` 1 trunk, 2 spur)."""
    path = _route(
        world,
        comp_mask,
        network.enter_base,
        a,
        b,
        network.costs,
        network.turn_cost,
        network.settlement,
        network.cardinal_only,
    )
    for x, y in path:
        world.road[y, x] = 1
        if world.road_tier[y, x] == 0:
            world.road_tier[y, x] = tier


def run(world: World, config: Config, seed: int) -> None:
    """Build the road network of the POIs that exist (the settlements), mutating ``world`` in place.

    The wild and history POIs come later, after the history stage: :func:`spurs` branches them off this network.
    """
    eligible = _road_eligible(world)
    if len(eligible) < 2:
        return  # nothing to connect
    network = _network(world, config, seed, eligible)

    col_km, row_km = world.scale.km_per_col, world.scale.km_per_row
    tiers = config.get("tables.tiers")
    backbone_kinds = {name: bool(row["backbone"]) for name, row in tiers.items()}  # tier kind -> joins the trunk
    probs = (
        float(config.get("roads.civilized_connect_prob")),
        float(config.get("roads.uncivilized_connect_prob")),
        float(config.get("roads.extra_edge_prob")),
    )
    k = int(config.get("roads.k_neighbors"))

    for comp in sorted(network.groups):
        group = network.groups[comp]
        if len(group) < 2:
            continue
        coords = [_endpoint(p) for (_i, p) in group]
        civ_flags = [bool(p.civilized) for (_i, p) in group]
        backbone_flags = [backbone_kinds.get(p.kind, False) for (_i, p) in group]
        km_coords = [(x * col_km, y * row_km) for x, y in coords]
        edge_rng = rng.derive(seed, "roads", comp)
        trunk_edges, spur_indices = _classify_edges(km_coords, civ_flags, backbone_flags, k, edge_rng, probs)

        comp_mask = network.labels == comp

        # Trunk phase: route the MST backbone + extra loop edges first.
        for i, j in trunk_edges:
            _lay(world, network, comp_mask, coords[i], coords[j], 1)

        # Spur phase: connect each isolated POI to the nearest existing road tile.
        # Routing after the trunk means spurs branch off the closest point on the network,
        # avoiding the parallel-road problem caused by each spur targeting a distant POI directly.
        road_yx = np.argwhere((world.road > 0) & comp_mask)  # shape (N, 2) as [row, col]
        for node_idx in spur_indices:
            start = coords[node_idx]
            if len(road_yx) > 0:
                target = _nearest_road(road_yx, start, col_km, row_km)
            else:
                # No trunk yet (e.g. single backbone node); fall back to nearest backbone POI.
                backbone = [i for i, f in enumerate(civ_flags) if f] or list(range(len(coords)))
                d2_list = [
                    ((coords[node_idx][0] - coords[t][0]) * col_km) ** 2
                    + ((coords[node_idx][1] - coords[t][1]) * row_km) ** 2
                    for t in backbone
                ]
                target = coords[backbone[int(np.argmin(d2_list))]]
            _lay(world, network, comp_mask, start, target, 2)
    if network.cardinal_only:
        _close_diagonals(world)


def _nearest_road(road_yx: np.ndarray, start: Coord, col_km: float, row_km: float) -> Coord:
    """The road tile (x, y) nearest ``start`` in km, the first of the lowest index on a tie."""
    d2 = ((road_yx[:, 1] - start[0]) * col_km) ** 2 + ((road_yx[:, 0] - start[1]) * row_km) ** 2
    best = road_yx[int(np.argmin(d2))]
    return int(best[1]), int(best[0])


def spurs(world: World, config: Config, seed: int) -> None:
    """Branch the wild and history POIs off the settlement roads, mutating ``world`` in place.

    Runs after the pois stage. Every POI whose kind is not a settlement tier and whose ``connect`` is true is a
    candidate; as for a village, ``roads.uncivilized_connect_prob`` decides (in POI order, one draw each) whether it
    gets a spur, which runs to the nearest road tile of its landmass. A landmass with no road gets none.
    """
    tiers = config.get("tables.tiers")
    eligible = [(i, p) for i, p in _road_eligible(world) if p.kind not in tiers]
    if not eligible:
        return
    network = _network(world, config, seed, eligible)
    col_km, row_km = world.scale.km_per_col, world.scale.km_per_row
    chance = float(config.get("roads.uncivilized_connect_prob"))
    for comp in sorted(network.groups):
        comp_mask = network.labels == comp
        road_yx = np.argwhere((world.road > 0) & comp_mask)
        if len(road_yx) == 0:
            continue
        stream = rng.derive(seed, "roads", "spurs", comp)
        for _index, poi in network.groups[comp]:
            if stream.random() < chance:
                _lay(
                    world, network, comp_mask, _endpoint(poi), _nearest_road(road_yx, _endpoint(poi), col_km, row_km), 2
                )
    if network.cardinal_only:
        _close_diagonals(world)

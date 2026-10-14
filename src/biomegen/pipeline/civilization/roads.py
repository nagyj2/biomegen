"""Stage 9: roads + bridges.

Connects POIs with meandering least-cost roads, then bridges river crossings. The design has four
parts:

1. **Landmass grouping.** A "landmass" is everything that is not open saltwater (``water_type != SALT``)
   - i.e. land plus the rivers/lakes embedded in it. Components of that mask are the islands. POIs are
   grouped by the component under their anchor, and a road is only ever routed *within* one component,
   so roads structurally cannot cross the open ocean (and a river slicing an island does not split it).
2. **Connection graph (per component).** k-nearest-neighbour candidate edges → a minimum spanning tree
   over the civilized POIs (the settlement backbone; falls back to all POIs if a component has none) →
   probabilistically attach the remaining POIs (civilized more likely than uncivilized) → a few extra
   loop edges. All random draws come from one per-component RNG consumed in a fixed sorted edge order.
3. **Routing.** Each selected edge is routed with A* over a precomputed cost surface (flat/downhill is
   cheap; slopes, water and mountains are dear; existing road is discounted; a smooth noise field adds
   meander). The search is confined to the component's mask and a padded bounding box and capped, with
   a straight-line fallback, so it stays fast on the non-monotone cost.
4. **Bridges.** Each maximal run of same-type water tiles a routed road crosses becomes one ``bridge``
   POI, minted the moment the crossing is identified. The bridge joins the two land road pieces flanking
   the run (``p0``/``p1``), and its marker sits on the **centre of that straight span** (not a run end);
   the span endpoints are stored on the POI ``extra`` so the renderer can draw a straight deck at any
   angle. Freshwater runs of any length and saltwater (ocean) runs of at most ``_MAX_OCEAN_BRIDGE`` tiles
   are bridged; longer ocean crossings are silently skipped. Mixed ocean+river runs are split at the
   salt/fresh boundary so each sub-run gets its own correctly positioned bridge.
5. **Entrances.** This stage runs *before* POI interiors, so after routing it records on each POI the
   direction the road network arrives from (``extra['road_entry']``); the interiors stage turns that into
   the footprint perimeter entrance and biases the interior door to face the road. Roads arriving from
   the same side share one entrance.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple, cast

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...util import noise, rng
from ...world.entities import POI
from ...world.tile import Relief, WaterType
from ...world.world import World

Coord = Tuple[int, int]
_MOUNTAINISH = frozenset({int(Relief.MOUNTAIN), int(Relief.PEAK), int(Relief.VOLCANO)})
_SETTLEMENT_KINDS = frozenset({"city", "town", "village"})


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
    """Land POIs eligible to be road endpoints (boats and any water-anchored POI excluded), by index."""
    out = []
    for i, p in enumerate(world.pois):
        if p.kind == "boat":
            continue
        if world.water_type[p.y, p.x] != int(WaterType.NONE):
            continue
        out.append((i, p))
    return out


def _endpoint(poi: "POI") -> Coord:
    """Road endpoint for a POI: its entrance, falling back to the anchor if entrance is unset/sentinel."""
    ex, ey = poi.entrance
    if (ex, ey) == (0, 0):
        return (poi.x, poi.y)
    return (ex, ey)


def _candidate_edges(coords: List[Coord], k: int) -> List[Tuple[int, int, float]]:
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
    coords: List[Coord],
    civ_flags: List[bool],
    cand: List[Tuple[int, int, float]],
    edge_rng: random.Random,
    probs: Tuple[float, float, float],
) -> Tuple[List[Tuple[int, int]], List[int]]:
    """Split connections into trunk edges and spur node indices.

    Trunk edges are MST backbone connections between civilized POIs plus a few extra loop edges.
    Spur nodes are isolated (non-backbone) POIs that should branch off the road network; they are
    routed to the nearest existing road tile after the trunk is built rather than to a specific POI,
    which prevents the parallel-road problem caused by many POIs independently targeting the same
    distant destination.

    Returns ``(trunk_edges, spur_node_indices)``.
    """
    m = len(coords)
    civ_prob, unciv_prob, extra_prob = probs
    backbone_nodes: set = {i for i in range(m) if civ_flags[i]} or set(range(m))

    # 1. MST over backbone nodes — this forms the trunk.
    uf = _UnionFind(m)
    trunk_edges: List[Tuple[int, int]] = []
    for i, j, _w in cand:
        if i in backbone_nodes and j in backbone_nodes and uf.union(i, j):
            trunk_edges.append((i, j))

    # 2. Collect non-backbone nodes to attach as spurs (probabilistic, same odds as before).
    spur_nodes: List[int] = []
    for node in sorted(set(range(m)) - backbone_nodes):
        prob = civ_prob if civ_flags[node] else unciv_prob
        if edge_rng.random() < prob:
            spur_nodes.append(node)

    # 3. Extra loop edges between backbone nodes reinforce the trunk (not spurs).
    chosen = set(trunk_edges)
    for i, j, _w in cand:
        if (i, j) not in chosen and i in backbone_nodes and j in backbone_nodes:
            if edge_rng.random() < extra_prob:
                trunk_edges.append((i, j))
                chosen.add((i, j))

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


def _route(
    world: World,
    comp_mask: np.ndarray,
    enter_base: np.ndarray,
    a: Coord,
    b: Coord,
    costs: Tuple[float, float, float, float],
    turn_cost: float = 0.0,
    settlement: np.ndarray | None = None,
) -> List[Coord]:
    """A* route a→b within the component mask + padded bbox; straight-line fallback if it bails.

    When turn_cost > 0, state is augmented with the incoming direction (x, y, dx, dy) so that
    direction changes incur an extra flat penalty. This reduces zigzagging caused by the meander
    noise field without affecting path topology on smooth terrain.
    """
    h, w = world.height, world.width
    elev = world.elevation
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
                for (nx, ny) in geo.neighbors8(nx0, ny0, w, h)
                if x0 <= nx <= x1 and y0 <= ny <= y1 and comp_mask[ny, nx]
            ]

        def cost(p, q) -> float:
            qx, qy = cast(Coord, q)
            dist = 1.4142135623730951 if p[0] != qx and p[1] != qy else 1.0
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
            heuristic_fn=lambda n, g: geo.octile_distance(cast(Coord, n), cast(Coord, g)) * base_cost,
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
                for (nx, ny) in geo.neighbors8(sx, sy, w, h)
                if x0 <= nx <= x1 and y0 <= ny <= y1 and comp_mask[ny, nx]
            ]

        def dir_cost(p_state, q_state) -> float:
            px, py, pdx, pdy = cast(tuple, p_state)
            qx, qy, qdx, qdy = cast(tuple, q_state)
            dist = 1.4142135623730951 if qdx != 0 and qdy != 0 else 1.0
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
            return geo.octile_distance(cast(Coord, (nt[0], nt[1])), cast(Coord, g)) * base_cost

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
            for (x, y) in _bresenham(a, b)
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


# Maximum number of consecutive ocean (SALT) tiles a road may bridge in one crossing.
# Longer ocean runs are skipped to prevent implausible open-sea bridges.
_MAX_OCEAN_BRIDGE = 2

# How far from a POI anchor to look for the road(s) that reach it, when recording its entrance side.
_ENTRANCE_SCAN_RADIUS = 2


def _sign(v: int) -> int:
    """Return -1, 0 or +1 for the sign of ``v``."""
    return (v > 0) - (v < 0)


def _record_entrances(world: World) -> None:
    """Record, on each non-bridge POI, the direction the road network arrives from.

    Roads route to a POI's anchor, so after routing the anchor's neighbourhood holds the road tiles of
    every approach. Each approaching land-road tile is bucketed into one of the 8 compass directions
    (its sign relative to the anchor); the dominant direction is stored as ``extra['road_entry']`` and
    the full set as ``extra['road_dirs']``. Roads arriving from the same side collapse to one entry, so
    multiple roads share a single entrance. The interiors stage turns ``road_entry`` into the footprint
    perimeter entrance and biases the interior door to that side. POIs with no road keep no entry.
    """
    for poi in world.pois:
        if poi.kind == "bridge":
            continue
        counts: Dict[Coord, int] = {}
        for radius in range(1, _ENTRANCE_SCAN_RADIUS + 1):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue  # only the ring at this radius (inner rings handled already)
                    x, y = poi.x + dx, poi.y + dy
                    if not world.in_bounds(x, y):
                        continue
                    if world.road[y, x] and world.water_type[y, x] == int(WaterType.NONE):
                        d = (_sign(dx), _sign(dy))
                        counts[d] = counts.get(d, 0) + 1
            if counts:
                break  # nearest ring with any road wins; don't dilute it with farther tiles
        if not counts:
            continue
        # Dominant direction (most approaching tiles), tie-broken by a stable sorted order.
        primary = max(sorted(counts), key=lambda d: counts[d])
        poi.extra["road_entry"] = list(primary)
        poi.extra["road_dirs"] = [list(d) for d in sorted(counts)]


def _emit_bridge(
    world: World,
    seed: int,
    p0: Coord,
    p1: Coord,
    marker: Coord,
    run: List[Coord],
    tier: int,
    bridged: set,
) -> None:
    """Mint one ``bridge`` POI for a single water crossing and flag its run as road.

    ``p0``/``p1`` are the land road tiles on either shore - the two road pieces the bridge joins. The
    deck is rendered as a straight span between them (at whatever real angle the line requires), so the
    bridge's geometry is stored on the POI ``extra`` for the renderer. The marker is placed on the
    **centre of that span** (``marker``), the moment the crossing is identified, rather than drifting to
    a run end. ``run`` is the set of water tiles the crossing covers, flagged as road for the overview.

    ``bridged`` tracks the water tiles already spanned by a bridge (the run plus the straight deck line).
    If this crossing's water overlaps one already bridged - two roads fording the same spot - it is
    skipped so the bridges do not stack: the earlier (trunk-phase, usually longer) bridge already covers
    it, and overlapping decks would otherwise pile up. Distinct, non-overlapping crossings still each get
    their own bridge, so a wide ford reads as connected straight segments.
    """
    # Water tiles this crossing spans: the run plus any water under the straight p0->p1 deck line.
    crossing = set(run)
    for cx, cy in _bresenham(p0, p1):
        if world.in_bounds(cx, cy) and world.water_type[cy, cx] != int(WaterType.NONE):
            crossing.add((cx, cy))
    if crossing & bridged:
        return  # this water is already bridged - don't stack a second deck on it
    bridged |= crossing

    mx, my = marker
    region_id = int(world.region_id[my, mx])
    if world.poi_index[my, mx] < 0:
        idx = len(world.pois)
        world.pois.append(
            POI(
                kind="bridge",
                x=mx,
                y=my,
                interior_seed=rng.derive_int(seed, "roads", "bridge", mx, my),
                civilized=False,
                region_id=region_id,
                footprint=(1, 1),
                entrance=(mx, my),
                extra={"p0": [int(p0[0]), int(p0[1])], "p1": [int(p1[0]), int(p1[1])]},
            )
        )
        world.poi_index[my, mx] = idx
        if 0 <= region_id < len(world.regions):
            world.regions[region_id].poi_indices.append(idx)
    # Flag the whole crossing as road so it reads as a continuous bridged span on the overview.
    for cx, cy in run:
        world.road[cy, cx] = 1
        if world.road_tier[cy, cx] == 0:
            world.road_tier[cy, cx] = tier


def _place_bridges(world: World, seed: int, path: List[Coord], tier: int, bridged: set) -> None:
    """Mint one bridge POI per contiguous same-type water run the road crosses; flag the run as road.

    Each run is bounded in the path by a land road tile on either side (``p0``/``p1``); the bridge joins
    those two road pieces with a straight span and its marker sits on the span centre (see
    :func:`_emit_bridge`). Runs are split at salt/fresh boundaries so a river-mouth scenario (an ocean
    tile adjacent to a river tile) yields two separate, correctly positioned bridges. ``bridged`` carries
    the already-spanned water tiles across edges so overlapping crossings don't stack duplicate decks.
    """
    n = len(path)
    i = 0
    while i < n:
        x, y = path[i]
        wt = world.water_type[y, x]
        if wt == int(WaterType.NONE):
            i += 1
            continue
        is_salt = wt == int(WaterType.SALT)
        # Extend the run while the water keeps the same salt-ness (split at salt/fresh boundaries).
        j = i
        while j + 1 < n:
            nx, ny = path[j + 1]
            nwt = world.water_type[ny, nx]
            if nwt == int(WaterType.NONE) or (nwt == int(WaterType.SALT)) != is_salt:
                break
            j += 1
        run = path[i : j + 1]
        length = j - i + 1
        prev_idx = i - 1  # index in path just before the run start
        i = j + 1
        if is_salt and length > _MAX_OCEAN_BRIDGE:
            continue  # refuse implausibly long open-ocean crossings
        # Land road tiles flanking the run = the two road pieces the bridge connects.
        p0 = path[prev_idx] if prev_idx >= 0 else run[0]
        p1 = path[j + 1] if j + 1 < n else run[-1]
        _emit_bridge(world, seed, p0, p1, _span_centre(p0, p1, run), run, tier, bridged)

    # Detect diagonal land-to-land steps that visually cross a waterway without visiting a water tile.
    # A step (x0,y0)→(x1,y1) with dx=±1, dy=±1 passes between corners (x1,y0) and (x0,y1); when both
    # corners are freshwater the path spans a waterway diagonally. The bridge joins the two step tiles
    # (p0, p1); its deck is the straight diagonal between them. Only FRESH triggers this - SALT never.
    for k in range(n - 1):
        x0, y0 = path[k]
        x1, y1 = path[k + 1]
        if abs(x1 - x0) != 1 or abs(y1 - y0) != 1:
            continue
        c1x, c1y = x1, y0
        c2x, c2y = x0, y1
        if not (world.in_bounds(c1x, c1y) and world.in_bounds(c2x, c2y)):
            continue
        if world.water_type[c1y, c1x] == int(WaterType.FRESH) and world.water_type[c2y, c2x] == int(WaterType.FRESH):
            _emit_bridge(world, seed, (x0, y0), (x1, y1), (c1x, c1y), [(c1x, c1y)], tier, bridged)


def _span_centre(p0: Coord, p1: Coord, run: List[Coord]) -> Coord:
    """Return the water-run tile nearest the centre of the straight ``p0``->``p1`` span.

    The bridge marker sits on the centre of the deck, but it must land on an actual water tile of the
    crossing (so it reads as a bridge and is flagged road), so we snap the geometric midpoint of the two
    flanking road pieces to the closest tile of the run.
    """
    cx = (p0[0] + p1[0]) / 2.0
    cy = (p0[1] + p1[1]) / 2.0
    return min(run, key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)


def run(world: World, config: Config, seed: int) -> None:
    """Build the road network and bridges, mutating ``world`` in place."""
    backend = config.get("compute.backend")
    eligible = _road_eligible(world)
    if len(eligible) < 2:
        return  # nothing to connect

    # 1. Group eligible POIs by landmass component (ocean separates islands; rivers/lakes do not).
    landmass = world.water_type != int(WaterType.SALT)
    labels, _ = geo.label_by_value(landmass.astype(np.uint8), connectivity=8, backend=backend)
    groups: Dict[int, List[Tuple[int, "POI"]]] = {}
    for idx, poi in eligible:
        comp = int(labels[poi.y, poi.x])
        groups.setdefault(comp, []).append((idx, poi))

    # 2. Precompute the static entry-cost surface (water/mountain penalties + meander noise).
    base_cost = float(config.get("roads.base_cost"))
    enter_base = (
        base_cost
        + float(config.get("roads.water_cost")) * (world.water_type != int(WaterType.NONE))
        + float(config.get("roads.mountain_cost")) * np.isin(world.relief, list(_MOUNTAINISH))
        + _meander_field(world, config, seed)
    ).astype(np.float64)
    costs = (
        float(config.get("roads.slope_cost")),
        float(config.get("roads.uphill_surcharge")),
        float(config.get("roads.road_discount")),
        base_cost,
    )
    turn_cost = float(config.get("roads.turn_cost"))

    # 3. Build and route connections for each component.
    #    Settlement tiles attract roads exactly as existing road tiles do (same discount factor).
    settlement = np.zeros((world.height, world.width), dtype=bool)
    for poi in world.pois:
        if poi.kind in _SETTLEMENT_KINDS:
            settlement[poi.y, poi.x] = True
    probs = (
        float(config.get("roads.civilized_connect_prob")),
        float(config.get("roads.uncivilized_connect_prob")),
        float(config.get("roads.extra_edge_prob")),
    )
    k = int(config.get("roads.k_neighbors"))
    bridges_on = bool(config.get("roads.bridges"))
    bridged: set = set()  # water tiles already spanned by a bridge, so overlapping fords don't stack

    for comp in sorted(groups):
        group = groups[comp]
        if len(group) < 2:
            continue
        coords = [_endpoint(p) for (_i, p) in group]
        civ_flags = [bool(p.civilized) for (_i, p) in group]
        cand = _candidate_edges(coords, k)
        edge_rng = rng.derive(seed, "roads", comp)
        trunk_edges, spur_indices = _classify_edges(coords, civ_flags, cand, edge_rng, probs)

        comp_mask = labels == comp

        # Trunk phase: route the MST backbone + extra loop edges first.
        for i, j in trunk_edges:
            path = _route(world, comp_mask, enter_base, coords[i], coords[j], costs, turn_cost, settlement)
            for x, y in path:
                world.road[y, x] = 1
                if world.road_tier[y, x] == 0:
                    world.road_tier[y, x] = 1
            if bridges_on:
                _place_bridges(world, seed, path, tier=1, bridged=bridged)

        # Spur phase: connect each isolated POI to the nearest existing road tile.
        # Routing after the trunk means spurs branch off the closest point on the network,
        # avoiding the parallel-road problem caused by each spur targeting a distant POI directly.
        road_yx = np.argwhere((world.road > 0) & comp_mask)  # shape (N, 2) as [row, col]
        for node_idx in spur_indices:
            start = coords[node_idx]
            if len(road_yx) > 0:
                d2 = (road_yx[:, 1] - start[0]) ** 2 + (road_yx[:, 0] - start[1]) ** 2
                best = road_yx[int(np.argmin(d2))]
                target = (int(best[1]), int(best[0]))  # (x, y)
            else:
                # No trunk yet (e.g. single backbone node); fall back to nearest backbone POI.
                backbone = [i for i, f in enumerate(civ_flags) if f] or list(range(len(coords)))
                d2_list = [
                    (coords[node_idx][0] - coords[t][0]) ** 2 + (coords[node_idx][1] - coords[t][1]) ** 2
                    for t in backbone
                ]
                target = coords[backbone[int(np.argmin(d2_list))]]
            path = _route(world, comp_mask, enter_base, start, target, costs, turn_cost, settlement)
            for x, y in path:
                world.road[y, x] = 1
                if world.road_tier[y, x] == 0:
                    world.road_tier[y, x] = 2
            if bridges_on:
                _place_bridges(world, seed, path, tier=2, bridged=bridged)

    # Record where the finished network reaches each POI, so the interiors stage can site the entrance
    # (and the interior door) on the side the road arrives from.
    _record_entrances(world)

"""Stage 4: hydrology - rivers, lakes, salt/fresh classification, freshwater moisture.

This is the standard GIS surface-hydrology pipeline (the family used by RichDEM and GRASS GIS), all
in pure numpy + a binary heap:

1. **Priority-flood** depression filling (Barnes, Lehman & Soille 2014): flood inward from the ocean,
   raising every pit to its spill level. Cells whose filled level exceeds their real elevation are
   under standing water -> lakes. Provably terminating and O(n log n).
2. **D8 flow directions** (O'Callaghan & Mark 1984): each cell drains to its lowest neighbour on the
   filled surface. A tiny tie-break on the priority-flood finalisation order routes flow across flats
   toward the outlet, avoiding stuck water.
3. **Flow accumulation**: process cells from high to low and push their drainage area downstream; the
   result approximates each cell's upstream catchment area.
4. **River extraction**: cells whose accumulation exceeds a channelisation threshold become river
   channels; channels are traced into named :class:`River` paths.
5. **Lakes**: connected standing-water cells of sufficient size become :class:`Lake` objects.
6. **Salt vs fresh**: the ocean is salt (set by the mask stage); lakes and rivers are fresh.
7. **Freshwater-proximity moisture**: land near fresh water gets a moisture bonus feeding the biomes
   stage, so river valleys read greener.
"""

from __future__ import annotations

import heapq

import numpy as np

from ..config.model import Config
from ..util import geometry as geo
from ..world.entities import Lake, River
from ..world.tile import Biome, WaterType
from ..world.world import World

# Direction offsets indexed by the small ints stored in the receiver-direction array.
_OFFSETS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def _priority_flood(elevation: np.ndarray, seeds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Flood-fill inward from ``seeds`` raising pits to spill level.

    Returns ``(filled, order)`` where ``filled`` is the depression-filled surface and ``order`` is the
    rank at which each cell was finalised (low rank = near the outlet). ``order`` is used purely as a
    downhill tie-breaker on flats. ``seeds`` is a boolean mask of outlet cells (the ocean).
    """
    h, w = elevation.shape
    filled = elevation.copy()
    visited = np.zeros((h, w), dtype=bool)
    order = np.zeros((h, w), dtype=np.int64)

    heap: list = []
    counter = 0  # monotonic tiebreaker so equal-elevation pops are deterministic
    sy, sx = np.nonzero(seeds)
    for y, x in zip(sy.tolist(), sx.tolist(), strict=True):
        visited[y, x] = True
        heapq.heappush(heap, (float(elevation[y, x]), counter, x, y))
        counter += 1

    rank = 0
    while heap:
        e, _, x, y = heapq.heappop(heap)
        order[y, x] = rank
        rank += 1
        for dx, dy in _OFFSETS8:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
                visited[ny, nx] = True
                # Raise the neighbour to at least the current spill level.
                nf = elevation[ny, nx] if elevation[ny, nx] > e else e
                filled[ny, nx] = nf
                heapq.heappush(heap, (float(nf), counter, nx, ny))
                counter += 1
    return filled, order


def _compute_receivers(key: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return per-cell flow receiver coordinates: each cell drains to its lowest-``key`` neighbour.

    ``key`` combines filled elevation with a tiny order term so flats drain toward the outlet. Cells
    with no lower neighbour are sinks (receiver = self). Fully vectorised via padded shifts.
    """
    h, w = key.shape
    padded = np.pad(key, 1, mode="constant", constant_values=np.inf)
    best = key.copy()  # best neighbour key found so far (init = self)
    best_dir = np.full((h, w), -1, dtype=np.int8)
    for d, (dx, dy) in enumerate(_OFFSETS8):
        shifted = padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
        better = shifted < best
        best = np.where(better, shifted, best)
        best_dir = np.where(better, d, best_dir)

    ys, xs = np.indices((h, w))
    rx = xs.copy()
    ry = ys.copy()
    for d, (dx, dy) in enumerate(_OFFSETS8):
        sel = best_dir == d
        rx[sel] = xs[sel] + dx
        ry[sel] = ys[sel] + dy
    return rx, ry  # for sinks (best_dir == -1) receiver stays self


def _flow_accumulation(filled: np.ndarray, order: np.ndarray, rx: np.ndarray, ry: np.ndarray) -> np.ndarray:
    """Accumulate unit drainage area downstream. Returns a float accumulation field.

    Processing cells in descending ``key`` order guarantees every cell is handled before its receiver
    (receivers always have a strictly smaller key), so a single linear pass is a valid topological sweep.
    """
    h, w = filled.shape
    accum = np.ones((h, w), dtype=np.float64)
    key = filled + order * 1e-9
    # Indices sorted by key descending (process upstream cells first).
    flat_order = np.argsort(key, axis=None)[::-1]
    rxf = rx.ravel()
    ryf = ry.ravel()
    accf = accum.ravel()
    xs_flat = (np.indices((h, w))[1]).ravel()
    ys_flat = (np.indices((h, w))[0]).ravel()
    for idx in flat_order.tolist():
        rxi = rxf[idx]
        ryi = ryf[idx]
        # Skip sinks (receiver == self).
        if rxi == xs_flat[idx] and ryi == ys_flat[idx]:
            continue
        accf[ryi * w + rxi] += accf[idx]
    return accum


def _extract_rivers(
    channel: np.ndarray, accum: np.ndarray, rx: np.ndarray, ry: np.ndarray, max_rivers: int
) -> list[River]:
    """Trace channel cells into ordered :class:`River` paths from sources downstream.

    A "source" channel cell has no channel cell draining into it. We trace each source downstream
    along the receiver chain until leaving the channel or meeting an already-claimed cell, so each
    river path is recorded once. The largest-catchment sources are kept first.
    """
    h, w = channel.shape
    # Count channel inflow per cell: a channel neighbour whose receiver is this cell.
    inflow = np.zeros((h, w), dtype=np.int32)
    cy, cx = np.nonzero(channel)
    for x, y in zip(cx.tolist(), cy.tolist(), strict=True):
        tx, ty = int(rx[y, x]), int(ry[y, x])
        if (tx != x or ty != y) and channel[ty, tx]:
            inflow[ty, tx] += 1

    # Sources sorted by descending accumulation (the most significant rivers first).
    sources = [(x, y) for x, y in zip(cx.tolist(), cy.tolist(), strict=True) if inflow[y, x] == 0]
    sources.sort(key=lambda c: float(accum[c[1], c[0]]), reverse=True)

    claimed = np.zeros((h, w), dtype=bool)
    rivers: list[River] = []
    for sx, sy in sources:
        if len(rivers) >= max_rivers:
            break
        if claimed[sy, sx]:
            continue
        path: list[tuple[int, int]] = []
        x, y = sx, sy
        # Follow the receiver chain while we remain on unclaimed channel cells.
        while channel[y, x] and not claimed[y, x]:
            claimed[y, x] = True
            path.append((x, y))
            tx, ty = int(rx[y, x]), int(ry[y, x])
            if tx == x and ty == y:
                break  # reached a sink
            x, y = tx, ty
        if len(path) >= 2:
            mouth = (x, y) if not channel[y, x] else None
            rivers.append(River(id=len(rivers), path=path, length=len(path), mouth=mouth))
    return rivers


def _widen_rivers(
    world: World,
    thalweg: np.ndarray,
    accum: np.ndarray,
    threshold: float,
    width_scale: float,
    max_width: int,
    sea_level: float,
) -> None:
    """Dilate the single-tile channel into a multi-tile river based on drainage area.

    Each thalweg cell gets a width = 1 + (accum/threshold - 1) * width_scale (capped at max_width);
    the cell's land neighbours within its half-width radius are converted to freshwater river. Only
    land tiles are flooded - ocean and lakes are left untouched - so widening never erases coastline.
    """
    if max_width <= 1 or width_scale <= 0:
        return
    h, w = thalweg.shape
    ratio = np.maximum(0.0, accum / max(1e-9, threshold) - 1.0)
    width = np.clip(1 + np.floor(ratio * width_scale), 1, max_width).astype(np.int32)
    half = (width - 1) // 2  # 0 for width 1-2, 1 for width 3-4, 2 for width 5, ...

    river = int(Biome.RIVER)
    fresh = int(WaterType.FRESH)
    dry = int(WaterType.NONE)
    ys, xs = np.nonzero(thalweg)
    for x, y in zip(xs.tolist(), ys.tolist(), strict=True):
        hw = int(half[y, x])
        if hw <= 0:
            continue
        for dy in range(-hw, hw + 1):
            for dx in range(-hw, hw + 1):
                if dx * dx + dy * dy > hw * hw:  # circular brush -> rounded banks
                    continue
                nx, ny = x + dx, y + dy
                if (
                    0 <= nx < w
                    and 0 <= ny < h
                    and world.water_type[ny, nx] == dry
                    and world.elevation[ny, nx] >= sea_level
                ):
                    world.biome[ny, nx] = river
                    world.water_type[ny, nx] = fresh


def run(world: World, config: Config, seed: int) -> None:
    """Run the full hydrology pipeline, mutating ``world`` in place."""
    h_cfg = config.section("hydrology")
    backend = config.get("compute.backend")
    sea_level = float(config.get("world.sea_level"))

    elevation = world.elevation
    ocean = world.water_type == int(WaterType.SALT)

    # Without an ocean to drain to, seed the flood from the map border instead (degenerate maps).
    seeds = ocean
    if not seeds.any():
        seeds = np.zeros_like(ocean)
        seeds[0, :] = seeds[-1, :] = seeds[:, 0] = seeds[:, -1] = True

    # 1. Build the depression-filled surface, drainage directions, and flow accumulation.
    filled, order = _priority_flood(elevation, seeds)
    key = filled + order * 1e-9
    rx, ry = _compute_receivers(key)
    accum = _flow_accumulation(filled, order, rx, ry)
    world.flow_accum = accum

    # 2. Lakes: connected standing-water cells whose filled level noticeably exceeds their real surface.
    depth = filled - elevation
    lake_mask = (depth > float(h_cfg.get("lake_min_depth"))) & (~ocean)
    if lake_mask.any():
        labels, n = geo.label_by_value(lake_mask.astype(np.uint8), connectivity=4, backend=backend)
        min_size = int(h_cfg.get("min_lake_size"))
        for lab in range(n):
            comp = (labels == lab) & lake_mask
            size = int(comp.sum())
            if size < min_size:
                continue  # a tiny pit, not a lake; leave it as land
            world.biome[comp] = int(Biome.LAKE)
            world.water_type[comp] = int(WaterType.FRESH)
            ly, lx = np.nonzero(comp)
            world.lakes.append(
                Lake(id=len(world.lakes), tiles=list(zip(lx.tolist(), ly.tolist(), strict=True)), area=size, salt=False)
            )

    # 3. Rivers: channelise high-accumulation land cells and widen them by drainage area.
    threshold = float(h_cfg.get("accumulation_threshold"))
    is_lake = world.biome == int(Biome.LAKE)
    # The single-tile "thalweg" (deepest line) drives flow tracing and entity extraction.
    thalweg = (accum >= threshold) & (elevation >= sea_level) & (~ocean) & (~is_lake)
    world.biome[thalweg] = int(Biome.RIVER)
    world.water_type[thalweg] = int(WaterType.FRESH)
    world.rivers = _extract_rivers(thalweg, accum, rx, ry, int(h_cfg.get("max_rivers")))
    # Widen the channel onto neighbouring land in proportion to its drainage area, so great rivers
    # span several tiles near the sea while headwater streams stay one tile.
    _widen_rivers(
        world,
        thalweg,
        accum,
        threshold,
        float(h_cfg.get("river_width_scale")),
        int(h_cfg.get("river_max_width")),
        sea_level,
    )

    # 4. Freshwater-proximity moisture bonus (feeds the biomes stage).
    fresh = world.water_type == int(WaterType.FRESH)
    if fresh.any():
        dist = geo.distance_to(fresh, backend=backend, metric="euclidean")
        radius = max(1e-6, float(h_cfg.get("moisture_radius")))
        bonus = float(h_cfg.get("moisture_strength")) * np.exp(-dist / radius)
        world.moisture = np.clip(world.moisture + bonus, 0.0, 1.0)

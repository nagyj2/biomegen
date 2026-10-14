"""Stage 8: POI interior metadata (no grids).

Runs after placement **and roads**. Fills the cheap, render-only metadata each POI needs for its
detail-view interior - the **footprint** in world tiles (centred on the anchor) and its clamped
bounding box - WITHOUT generating any interior grids. The grids are built lazily from each POI's
``interior_seed`` (see :mod:`biomegen.interiors`) only when a detail view samples them.

Because roads are already laid by now, this stage also turns each POI's recorded road approach
(``extra['road_entry']``) into a concrete **entrance** on the footprint perimeter and clears the road
tiles inside the footprint, so the road meets the structure at a single road-facing door (the interior
builder biases its door to the same side) rather than running through the building.

A coastal footprint loses interior area to the water it clips (the builder forms the structure *around*
the coast). To stop those structures from reading as runts, this stage **grows the footprint** until its
dry-land tile count is back up to the nominal (size-jittered) area - capped by ``interiors.expand_max_factor``.
Growth is symmetric (the anchor stays centred, as the renderer and roads assume): water does not block it
(the extra coast is just carved again by the builder), but other POIs do - each POI claims its footprint
rectangle and every anchor is off-limits, so a grown structure never overlaps a neighbour. POIs grow in
placement (priority) order, so higher-value settlements claim space first.

This stage writes POI dataclass fields plus a localised, deterministic clear of the ``road``/
``road_tier`` arrays inside each footprint (the road bed already laid through what is now a building).
The base biome/elevation/etc. arrays are untouched; the road clear is a pure function of the placed
POIs, so generation stays fully reproducible.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from ..config.model import Config
from ..interiors import INTERIOR_BUILDERS
from ..util import rng
from ..world.tile import WaterType
from ..world.world import World

_MIN_FOOTPRINT = 3  # tiles per side - keeps the canonical grid big enough for at least a room or two


def run(world: World, config: Config, seed: int) -> None:
    """Assign every POI a footprint + bbox from ``interiors.footprints`` (mutates ``world`` in place)."""
    footprints = config.get("interiors.footprints")
    jitter = float(config.get("interiors.size_jitter"))
    expand_factor = float(config.get("interiors.expand_max_factor"))
    water = world.water_type != int(WaterType.NONE)
    anchors = world.poi_index >= 0  # every POI's anchor tile (off-limits to a growing neighbour)
    occupied = np.zeros((world.height, world.width), dtype=bool)  # footprint rectangles claimed so far
    for poi in world.pois:
        fp = footprints.get(poi.kind)
        if not fp:
            continue  # no configured footprint -> stays a single-tile marker (no interior)
        fw, fh = max(1, int(fp[0])), max(1, int(fp[1]))
        # Vary the size per POI (deterministically) so dungeons & co. spawn a bit larger or smaller.
        # Only kinds with a real interior builder are jittered; pure markers keep their nominal size.
        if jitter > 0 and INTERIOR_BUILDERS.has(poi.kind):
            sr = rng.derive(poi.interior_seed, "interior.footprint")
            fw = max(_MIN_FOOTPRINT, round(fw * sr.uniform(1 - jitter, 1 + jitter)))
            fh = max(_MIN_FOOTPRINT, round(fh * sr.uniform(1 - jitter, 1 + jitter)))
        # Restore land area lost to coast/POI carving by growing the footprint. Boats sit on water by
        # design, so they keep their nominal footprint and stake no claim on the land.
        if poi.kind != "boat" and expand_factor > 1.0:
            fw, fh = _expand_to_restore_area(poi.x, poi.y, fw, fh, water, occupied, anchors, expand_factor)
        poi.footprint = (fw, fh)
        # Footprint is centred on the anchor; the bbox is the clamped on-map extent (for HUD/export).
        tx0, ty0 = poi.x - fw // 2, poi.y - fh // 2
        poi.bbox = (
            max(0, tx0),
            max(0, ty0),
            min(world.width - 1, tx0 + fw - 1),
            min(world.height - 1, ty0 + fh - 1),
        )
        if poi.kind != "boat":
            # Site the entrance the road network reaches (recorded by the roads stage) on the footprint
            # perimeter facing that side, and clear road tiles inside the footprint so the road bed stops
            # at the structure (the interior is stamped over it) instead of running through the building.
            _place_entrance(poi, fw, fh, tx0, ty0, world.width, world.height)
            _clear_interior_roads(world, fw, fh, tx0, ty0)
            # Claim the rectangle so later (lower-priority) POIs can't grow into it.
            occupied[max(0, ty0) : ty0 + fh, max(0, tx0) : tx0 + fw] = True


def _place_entrance(poi, fw: int, fh: int, tx0: int, ty0: int, world_w: int, world_h: int) -> None:
    """Set ``poi.entrance`` on the footprint perimeter facing the road, or leave it at the anchor.

    ``extra['road_entry']`` is the dominant compass direction the road network arrives from (recorded by
    the roads stage). The entrance is placed at the midpoint of the footprint edge on that side, so the
    interior door (biased to the same side) lines up with the approaching road. With no recorded road the
    entrance stays at the anchor - the prior behaviour - so road-less POIs are unaffected.
    """
    entry = poi.extra.get("road_entry")
    if not entry:
        poi.entrance = (poi.x, poi.y)
        return
    dx, dy = int(entry[0]), int(entry[1])
    ex = poi.x + dx * (fw // 2)
    ey = poi.y + dy * (fh // 2)
    # Clamp onto the footprint rectangle (the perimeter) and then onto the map.
    ex = min(max(ex, tx0), tx0 + fw - 1)
    ey = min(max(ey, ty0), ty0 + fh - 1)
    poi.entrance = (min(max(ex, 0), world_w - 1), min(max(ey, 0), world_h - 1))


def _clear_interior_roads(world: World, fw: int, fh: int, tx0: int, ty0: int) -> None:
    """Clear road tiles strictly inside the footprint, keeping the 1-tile perimeter ring intact.

    The perimeter ring is preserved so the road that approached the anchor still meets the structure's
    edge (the entrance) instead of leaving a gap; everything further in is hidden by the interior stamp,
    so flagging it road would only let the road-bed render bleed under the building. A footprint too thin
    to have a strict interior is left untouched.
    """
    x0, y0 = max(0, tx0), max(0, ty0)
    x1, y1 = min(world.width, tx0 + fw), min(world.height, ty0 + fh)
    if x1 - x0 > 2 and y1 - y0 > 2:
        inner = (slice(y0 + 1, y1 - 1), slice(x0 + 1, x1 - 1))
        # Clear only the land road bed under the building; water tiles (a bridge crossing that happens to
        # pass under the footprint) keep their road flag so the bridge still reads as a crossing.
        land = world.water_type[inner] == int(WaterType.NONE)
        world.road[inner] = np.where(land, 0, world.road[inner])
        world.road_tier[inner] = np.where(land, 0, world.road_tier[inner])


def _expand_to_restore_area(
    x: int,
    y: int,
    fw: int,
    fh: int,
    water: np.ndarray,
    occupied: np.ndarray,
    anchors: np.ndarray,
    factor: float,
) -> Tuple[int, int]:
    """Grow ``(fw, fh)`` centred on ``(x, y)`` until its dry, unclaimed land area is back to ``fw*fh``.

    ``water`` tiles count as lost area (they get carved) but never block growth; ``occupied`` rectangles
    and all ``anchors`` except this POI's own are hard blockers a grown footprint may never include. Area
    is capped at ``ceil(fw*fh*factor)`` and to the map. Returns the nominal size unchanged when nothing
    was carved (an inland footprint clear of water and neighbours), so non-coastal POIs are untouched.
    """
    h, w = water.shape
    target = fw * fh
    cap = max(target, int(math.ceil(target * factor)))

    def metrics(cw: int, ch: int) -> Tuple[int, bool, int]:
        """Return (free land tiles, touches a blocker, on-map tile count) for a centred cw x ch rect."""
        tx0, ty0 = x - cw // 2, y - ch // 2
        x0, x1 = max(0, tx0), min(w, tx0 + cw)
        y0, y1 = max(0, ty0), min(h, ty0 + ch)
        if x1 <= x0 or y1 <= y0:
            return 0, False, 0
        block = occupied[y0:y1, x0:x1] | anchors[y0:y1, x0:x1]
        ay, ax = y - y0, x - x0  # the POI's own anchor is never a blocker against itself
        if 0 <= ay < y1 - y0 and 0 <= ax < x1 - x0 and block[ay, ax]:
            block = block.copy()
            block[ay, ax] = False
        wet = water[y0:y1, x0:x1]
        free = int(np.count_nonzero(~wet & ~block))
        return free, bool(block.any()), int((y1 - y0) * (x1 - x0))

    free, _hits, onmap = metrics(fw, fh)
    if free >= onmap:
        return fw, fh  # no water/neighbour carved into the on-map footprint -> leave it at nominal

    while free < target and fw * fh < cap:
        best = None  # pick the single-side growth that recovers the most land without hitting a blocker
        for nw, nh in ((fw + 1, fh), (fw, fh + 1)):
            if nw * nh > cap or nw > w or nh > h:
                continue
            nfree, nhits, _ = metrics(nw, nh)
            if nhits:
                continue  # would overlap another POI's footprint/anchor - not allowed
            key = (nfree, -(nw * nh))  # most land, then the smaller area (avoid needless growth)
            if best is None or key > best[0]:
                best = (key, nw, nh, nfree)
        if best is None:
            break  # boxed in by neighbours on every side
        _key, fw, fh, free = best
    return fw, fh

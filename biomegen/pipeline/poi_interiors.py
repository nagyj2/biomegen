"""Stage 8: POI interior metadata (no grids).

Runs after placement and before roads. Fills the cheap, render-only metadata each POI needs for its
detail-view interior - the **footprint** in world tiles (centred on the anchor) and its clamped
bounding box - WITHOUT generating any interior grids. The grids are built lazily from each POI's
``interior_seed`` (see :mod:`biomegen.world.interiors`) only when a detail view samples them.

A coastal footprint loses interior area to the water it clips (the builder forms the structure *around*
the coast). To stop those structures from reading as runts, this stage **grows the footprint** until its
dry-land tile count is back up to the nominal (size-jittered) area - capped by ``interiors.expand_max_factor``.
Growth is symmetric (the anchor stays centred, as the renderer and roads assume): water does not block it
(the extra coast is just carved again by the builder), but other POIs do - each POI claims its footprint
rectangle and every anchor is off-limits, so a grown structure never overlaps a neighbour. POIs grow in
placement (priority) order, so higher-value settlements claim space first.

This stage writes only :class:`~biomegen.world.entities.POI` dataclass fields, never the per-tile
numpy arrays, so the world fingerprint is unchanged. ``entrance`` is left at the anchor, so the roads
stage (which routes to ``poi.entrance``) is unaffected; per-archetype door refinement is deferred to
the phases that add those archetypes' builders.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from ..config.model import Config
from ..util import rng
from ..world.interiors import INTERIOR_BUILDERS
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
        if poi.kind != "boat":  # claim the rectangle so later (lower-priority) POIs can't grow into it
            occupied[max(0, ty0) : ty0 + fh, max(0, tx0) : tx0 + fw] = True


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

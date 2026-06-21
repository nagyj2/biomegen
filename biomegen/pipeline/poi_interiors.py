"""Stage 8: POI interior metadata (no grids).

Runs after placement and before roads. Fills the cheap, render-only metadata each POI needs for its
detail-view interior - the **footprint** in world tiles (centred on the anchor) and its clamped
bounding box - WITHOUT generating any interior grids. The grids are built lazily from each POI's
``interior_seed`` (see :mod:`biomegen.world.interiors`) only when a detail view samples them.

This stage writes only :class:`~biomegen.world.entities.POI` dataclass fields, never the per-tile
numpy arrays, so the world fingerprint is unchanged. ``entrance`` is left at the anchor, so the roads
stage (which routes to ``poi.entrance``) is unaffected; per-archetype door refinement is deferred to
the phases that add those archetypes' builders.
"""

from __future__ import annotations

from ..config.model import Config
from ..util import rng
from ..world.interiors import INTERIOR_BUILDERS
from ..world.world import World

_MIN_FOOTPRINT = 3  # tiles per side - keeps the canonical grid big enough for at least a room or two


def run(world: World, config: Config, seed: int) -> None:
    """Assign every POI a footprint + bbox from ``interiors.footprints`` (mutates ``world`` in place)."""
    footprints = config.get("interiors.footprints")
    jitter = float(config.get("interiors.size_jitter"))
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
        poi.footprint = (fw, fh)
        # Footprint is centred on the anchor; the bbox is the clamped on-map extent (for HUD/export).
        tx0, ty0 = poi.x - fw // 2, poi.y - fh // 2
        poi.bbox = (
            max(0, tx0),
            max(0, ty0),
            min(world.width - 1, tx0 + fw - 1),
            min(world.height - 1, ty0 + fh - 1),
        )

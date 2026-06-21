"""Lazy, deterministic POI interior builders.

A POI's interior is never stored in the :class:`~biomegen.world.world.World`; it is regenerated on
demand from the POI's ``interior_seed`` by a per-kind builder and memoised (see :mod:`.grid`). This
package holds the shared toolkit (:mod:`.grid`) and one module per archetype. The Phase 5 vertical
slice implements :mod:`.dungeon`; the remaining archetypes (tower, village, town, city, ruins, camp,
boat) plug in the same way - drop a module, decorate the builder with ``@register_interior(kind)``,
and import it here so the registration runs.
"""

from __future__ import annotations

# Importing these modules runs their @register_* decorators (registration side-effect). The dungeon
# builder only looks a shape up at call time, so both registries are populated regardless of order.
from . import (
    dungeon,  # noqa: F401  (imported for its @register_interior side-effect)
    shapes,  # noqa: F401  (imported for its SHAPES registration side-effect)
)
from .grid import (
    INTERIOR_BUILDERS,
    SHAPES,
    STRUCTURAL,
    ZOOM_VISIBLE,
    build_interior,
    clear_cache,
    footprint_cells,
    footprint_origin,
    sample_rect,
)

__all__ = [
    "INTERIOR_BUILDERS",
    "SHAPES",
    "STRUCTURAL",
    "ZOOM_VISIBLE",
    "build_interior",
    "clear_cache",
    "footprint_cells",
    "footprint_origin",
    "sample_rect",
]

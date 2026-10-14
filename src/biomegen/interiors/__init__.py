"""Lazy, deterministic POI interior builders.

A POI's interior is never stored in the :class:`~biomegen.world.world.World`; it is regenerated on
demand from the POI's ``interior_seed`` by a per-kind builder and memoised (see :mod:`.grid`). This
package holds the shared toolkit (:mod:`.grid`) and one module per archetype, all built on that toolkit:

* :mod:`.dungeon` / :mod:`.tower` - stacked solid buildings (a dungeon descends, a tower ascends), with
  aligned stair shafts and an exterior entrance on the ground floor.
* :mod:`.settlement` - city/town/village: a cluster of small walled buildings with open streets.
* :mod:`.ruin` - a single-floor building, eroded into rubble and breached walls.
* :mod:`.camp` / :mod:`.boat` - bespoke non-building layouts (open-air tents; a planked hull on water).

Every kind except ``bridge`` has a builder. Adding another archetype is the same recipe: drop a module,
decorate the builder with ``@register_interior(kind)``, give it a footprint in config, and import it
here so the registration side-effect runs.
"""

from __future__ import annotations

# Importing these modules runs their @register_* decorators (registration side-effect). The builders
# only look a shape/partition up at call time, so the registries are populated regardless of order.
from . import (
    boat,  # noqa: F401  (imported for its @register_interior side-effect)
    camp,  # noqa: F401
    dungeon,  # noqa: F401
    ruin,  # noqa: F401
    settlement,  # noqa: F401
    shapes,  # noqa: F401  (imported for its SHAPES registration side-effect)
    tower,  # noqa: F401
)
from .grid import (
    INTERIOR_BUILDERS,
    SHAPES,
    STRUCTURAL,
    ZOOM_VISIBLE,
    build_interior,
    clear_cache,
    ctx_buildable,
    footprint_cells,
    footprint_origin,
    sample_rect,
    sample_rect_array,
)

__all__ = [
    "INTERIOR_BUILDERS",
    "SHAPES",
    "STRUCTURAL",
    "ZOOM_VISIBLE",
    "build_interior",
    "clear_cache",
    "ctx_buildable",
    "footprint_cells",
    "footprint_origin",
    "sample_rect",
    "sample_rect_array",
]

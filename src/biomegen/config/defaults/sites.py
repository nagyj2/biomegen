"""Defaults for the ``sites`` section (how a POI's site plan is laid out and framed).

Per-kind rows (layout, extent, plan resolution) live in ``data/sites.toml``. Sizes here are in plan cells, which are
terminal cells: a row count is a count of rows, and widths are widened by ``render.cell_aspect``.
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "size_jitter": 0.25,  # each site's extent is scaled by a seeded factor in [1 - jitter, 1 + jitter]
    "pop_scale": [0.8, 1.3],  # a growing settlement's extent factor at the tier's smallest and largest population
    "margin_tiles": 0.5,  # terrain kept around the extent in the site window (drawn in the POI view)
    "max_gates": 3,  # road gates cut into a site's edge, one per distinct side the roads arrive from
    "room_rows": [3, 6],  # room height range in rows; the width is this times render.cell_aspect
    "building_rows": [3, 5],  # settlement building height range in rows (width widened like rooms)
    "clutter_density": 0.10,  # fraction of free floor cells that get furniture
    "shape": "mixed",  # outline of solid structures: "rectangle", "blob", "cellular", "drunkard", "diamond", "cross"
    # or "mixed" to pick one per structure
    "ruin_erosion": 0.45,  # fraction of a ruin's walls that have collapsed
    "coast_margin_rows": 1,  # bare ground kept between a solid structure and any water, in rows
    "street_water_cost": 6.0,  # cost of a street cell over water relative to dry ground (it becomes a bridge)
    "bridge_max_rows": 6,  # the widest water, in rows, a settlement street will bridge
    "cache_size": 256,  # site plans kept in memory
}

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
    "street_gap": [2, 1],  # clear ground [columns, rows] kept round each settlement building, beyond its wall
    "clutter_density": 0.10,  # fraction of free floor cells that get furniture
    "shape": "mixed",  # outline of solid structures: "rectangle", "blob", "cellular", "drunkard", "diamond", "cross"
    # or "mixed" to pick one per structure
    "ruin_erosion": 0.45,  # fraction of a ruin's walls that have collapsed
    "coast_margin_rows": 1,  # bare ground kept between a solid structure and any water, in rows
    "street_water_cost": 6.0,  # cost of a street cell over water relative to dry ground (it becomes a bridge)
    "bridge_max_rows": 6,  # the widest water, in rows, a settlement street will bridge
    "extra_corridors": {"dungeon": 0.34, "tower": 0.15, "ruin": 0.2},  # extra room-to-room links per room, by layout
    "furnish": {
        "depth_density_gain": 0.6,  # dungeon furniture density grows by this share per unit of depth (0 top, 1 bottom)
        "chest_depth_gain": 36.0,  # extra chest weight at the bottom floor of a dungeon
        "corridor_rubble_chance": 0.45,  # a corridor cell picked for furnishing takes rubble this often
        "lookout_density": 0.5,  # a tower's top floor is dressed at this share of the usual density
        "ruin_density": 1.5,  # ruins are strewn with debris: this multiple of clutter_density
        "ruin_crack": 0.5,  # floor cracks into rubble at this share of the wall-collapse rate
        "home_density": 1.6,  # homes are cosier than dungeons: this multiple of clutter_density
        "boat_density": 1.4,  # a deck is laden with cargo: this multiple of clutter_density
        "supply_density": 0.6,  # a camp scatters supplies at this multiple of clutter_density (at least 0.04)
    },
    "camp": {
        "clearing": 0.42,  # clearing radius as a share of the plan height (the width follows the cell aspect)
        "min_tents": 3,
        "tent_area_cells": 90,  # one more tent per this many cleared cells
        "tent_cells": [[4, 2], [6, 2], [4, 3]],  # tent sizes [columns, rows]
    },
    "boat": {"cabin_share": 0.25},  # the deckhouse is this share of the deck's length
    "cache_size": 256,  # site plans kept in memory
}

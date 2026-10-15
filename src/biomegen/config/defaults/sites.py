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
    "building_rows": [5, 8],  # settlement building outer height range in rows, walls included
    "street_gap": [1, 1],  # clear ground [columns, rows] between a settlement building and the street it faces
    "clutter_density": 0.10,  # fraction of free floor cells that get furniture
    "shape": "mixed",  # outline of solid structures: "rectangle", "blob", "cellular", "drunkard", "diamond", "cross"
    # or "mixed" to pick one per structure
    "ruin_erosion": 0.45,  # fraction of a ruin's walls that have collapsed
    "coast_margin_rows": 1,  # bare ground kept between a solid structure and any water, in rows
    "street_water_cost": 6.0,  # cost of a street cell over water relative to dry ground (it becomes a bridge)
    "bridge_max_rows": 6,  # the widest water, in rows, a settlement street will bridge
    "settlement": {
        "fill": 0.6,  # share of the buildable ground that lots try to cover with buildings
        "trees": 0.03,  # share of free ground planted with trees and bushes
        "wall_inset": [3, 2],  # [columns, rows] kept clear between the footprint and the edge of the extent
        "lot_tries": 6,  # sizes tried at each spot along a street before moving on
        "radius": 0.9,  # footprint radius as a share of the extent's half size
        "wobble": [0.16, 0.1, 0.07],  # amplitude of the outline's first three harmonics, as a share of the radius
        "storey_chance": 0.6,  # chance a building has another storey, each, near the plaza (less with distance)
        "road_stretch": 0.3,  # how far the outline bulges towards each road gate, as a share of the radius
        "spokes": [3, 5],  # streets from the plaza to the outline, besides the ones towards road gates
        "rings": [0.4, 0.72],  # ring streets, each at this share of the way from the plaza to the outline
        "ring_gap": 0.3,  # chance a ring street leaves out one of its arcs
        "max_lanes": 80,  # most lanes laid into ground too far from a street
        # A port (a POI tagged ``port``) builds a harbour when open water lies within ``reach_rows`` rows of the
        # plaza: a pier ``pier_rows`` rows long (columns scale with the cell aspect) from the dry shore nearest the
        # plaza, joined to it by a street, with up to ``boats`` boats of ``boat_length`` by ``boat_beam`` rows moored
        # beside it. A river settlement with a river in its extent builds a mill: a house ``width`` times as wide as
        # the shortest building on free ground within ``reach`` rows of the river. A water wheel ``wheel_rows`` rows
        # tall (as wide as the cell aspect makes it round) turns in the river, set a cell into the water, and an axle
        # runs from the middle of the house's wall to its hub.
        "harbour": {"pier_rows": 6, "boats": 2, "boat_length": 5, "boat_beam": 4, "reach_rows": 45},
        "mill": {"reach": 2.0, "width": 1.2, "wheel_rows": 3},
    },
    "extra_corridors": {"dungeon": 0.34, "tower": 0.15, "ruin": 0.2},  # extra room-to-room links per room, by layout
    "furnish": {
        "depth_density_gain": 0.6,  # dungeon furniture density grows by this share per unit of depth (0 top, 1 bottom)
        "chest_depth_gain": 36.0,  # extra chest weight at the bottom floor of a dungeon
        "corridor_rubble_chance": 0.45,  # a corridor cell picked for furnishing takes rubble this often
        "lookout_density": 0.5,  # a tower's top floor is dressed at this share of the usual density
        "ruin_density": 0.8,  # ruins are strewn with debris: this multiple of clutter_density
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

"""Defaults for the ``sites`` section (how a POI's site plan is laid out and framed).

Per-kind rows (layout, extent, plan resolution) live in ``data/sites.toml``. Sizes here are in plan cells, which are
terminal cells: a row count is a count of rows, and widths are widened by ``render.cell_aspect``.
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "size_jitter": 0.25,  # each site's extent is scaled by a seeded factor in [1 - jitter, 1 + jitter]
    "margin_tiles": 0.5,  # terrain kept around the extent in the site window (drawn in the POI view)
    "max_gates": 3,  # road gates cut into a site's edge, one per distinct side the roads arrive from
    "room_rows": [3, 6],  # room height range in rows; the width is this times render.cell_aspect
    "street_gap": [1, 1],  # clear ground [columns, rows] between a settlement building and the street it faces
    "clutter_density": 0.10,  # fraction of free floor cells that get furniture
    "shape": "mixed",  # outline of solid structures: "rectangle", "blob", "cellular", "drunkard", "diamond", "cross"
    # or "mixed" to pick one per structure
    "ruin_erosion": 0.45,  # fraction of a ruin's walls that have collapsed once it is old (and of one with no date)
    "ruin_erosion_young": 0.12,  # the fraction a ruin that has just fallen has lost
    "ruin_erosion_years": 400,  # years until a fallen ruin has lost the full ``ruin_erosion`` (and a ruined settlement
    # its surviving buildings and wall: the tier's ``ruin_standing`` and ``ruin_wall_fall`` in ``data/sites.toml``)
    # A building of a ruined settlement that does not survive is destroyed completely: its wall cells and the rest of
    # its footprint each stay rubble with these shares, and the others are bare ground (the terrain shows through).
    "ruin_rubble": {"wall": 0.8, "floor": 0.45},
    # What a settlement is chosen to have (sites/surroundings.py): the land within each term's ``radius_km`` of it is
    # read for five terms, each a share that saturates (counts as 1) at its ``saturate`` value: mean habitability
    # (fertility), forest cover, the hilly share of the land (roughness: hills are rare near settlements, so a wider
    # radius), and the share of the area that is fresh water (lakes, rivers) and sea (coast).
    "kinds": {
        "radius_km": {"fertility": 60.0, "forest": 60.0, "roughness": 150.0, "fresh_water": 60.0, "coast": 60.0},
        "saturate": {"fertility": 0.6, "forest": 0.5, "roughness": 0.25, "fresh_water": 0.04, "coast": 0.08},
    },
    # The largest tier a site could grow into (sites/potential.py, stored as ``POI.potential``): the tiers whose
    # ``potential_land`` the habitable share of the land within ``radius_km`` reaches, and whose ``spacing_km`` times
    # ``room_share`` is no more than the distance to the nearest other settlement of note. A settlement is never given
    # less than the tier it already is.
    "potential": {"radius_km": 150.0, "room_share": 1.0},
    # A building that survives is damaged by how far the ruin has worn (its erosion over ``ruin_erosion``): at full wear
    # it has ``breaches`` per room, ``crack`` of its floor cracked into rubble, ``strip`` of its furniture gone and
    # ``roof`` of its rooms unroofed.
    "ruin_damage": {"breaches": 6.0, "crack": 0.6, "strip": 0.85, "roof": 0.8},
    # Layouts with a roof level above their top floor, where every building is seen as its roof.
    "roof_layouts": ["settlement", "homestead", "dungeon", "tower", "ruin", "shrine", "camp", "boat"],
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
        "road_join_rows": 3.0,  # a street this close (rows) beside the world road, not touching it, is run into it
        "storey_chance": 0.6,  # chance a building has another storey, each, near the plaza (less with distance)
        # An upper storey is cut back so a tall building steps in (a tower on an L, not a block): an L or T keeps its
        # whole outline on its first upper storey with chance ``whole``, else (and above) it is one wing; a plain
        # rectangle is shortened along its longer side to a share in ``shrink`` of its length, at each storey.
        "upper": {"whole": 0.35, "shrink": [0.6, 0.85]},
        "road_stretch": 0.3,  # how far the outline bulges towards each road gate, as a share of the radius
        "spokes": [3, 5],  # streets from the plaza to the outline, besides the ones towards road gates
        "rings": [0.4, 0.72],  # ring streets, each at this share of the way from the plaza to the outline
        "ring_gap": 0.3,  # chance a ring street leaves out one of its arcs
        "max_lanes": 80,  # most lanes laid into ground too far from a street
        "kind_reach_rows": 8,  # a specialized building stands within this many rows of a street (its door joins it)
        # A port (a POI tagged ``port``) builds a harbour when open water lies within ``reach_rows`` rows of the
        # plaza: a pier ``pier_rows`` rows long (columns scale with the cell aspect) from the dry shore nearest the
        # plaza, joined to it by a street, with up to ``boats`` boats of ``boat_length`` by ``boat_beam`` rows moored
        # beside it. A river settlement with a river in its extent builds a mill (a building kind, with its own size)
        # on free ground within ``reach`` rows of the river. A water wheel ``wheel_rows`` rows
        # tall (as wide as the cell aspect makes it round) turns in the river, set a cell into the water, and an axle
        # runs from the middle of the house's wall to its hub.
        "harbour": {"pier_rows": 6, "boats": 2, "boat_length": 5, "boat_beam": 4, "reach_rows": 45},
        "mill": {"reach": 2.0, "wheel_rows": 3},
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
        "tent_area_cells": 200,  # one more tent per this many cleared cells
        "tent_cells": [[6, 3], [8, 3], [6, 4]],  # tent sizes [columns, rows]; at least 3 by 3, so bedding fits inside
        "tent_bedding": [0.5, 1.0],  # the bedding is this share (drawn per side) of the room inside a tent's edge cells
        "tent_gear": 0.2,  # chance a bare floor cell of a tent holds a piece of gear
    },
    # A camp's purpose (POI.purpose) overrides keys of ``camp`` with ``camp_<purpose>``: builders keep few tents
    # and a yard of timber and crates, an army camp is a field of tents, bandits keep the plain camp.
    "camp_founding": {"clearing": 0.38, "min_tents": 1, "tent_area_cells": 200, "tent_cells": [[6, 3]]},
    "camp_army": {"clearing": 0.46, "min_tents": 5, "tent_area_cells": 120},
    # A battlefield: a trampled field (``clearing`` of the plan height) with a standard at each end, debris thickest
    # at the centre (``debris_density`` at the rim), ``wagons`` [min, max] wrecked carts, ``graves`` [min, max] mounds.
    "battlefield": {
        "clearing": 0.46,
        "debris_density": 0.09,
        "centre_boost": 2.5,  # debris is this many times denser at the centre of the field than at its rim
        "wagons": [2, 4],
        "graves": [8, 18],  # burial mounds laid out in rows in one corner of the field
        "banners": 2,  # the armies' standards, one at each end of the field
    },
    # A homestead: one building of its style's kind (``tables.buildings``: its size, roof and furniture)
    # beside a yard track ``track_rows`` rows long each way, dressed within ``yard_reach`` [columns, rows] of it
    # and ``trees`` of the free ground wooded. ``dress`` gives each dressing (a site row's ``dress`` key): ``field``
    # sows a wheat plot of about ``[rows, columns]`` beside the house, ``clearing`` bares a plot of that size for
    # ``logs`` felled trunks, ``spoil`` heaps that many rock and rubble cells, ``wagons`` and ``supplies`` (the
    # family's ``yard`` role) are counts, ``trees`` replaces the wooded share.
    "homestead": {
        "track_rows": 3,
        "yard_reach": [8, 4],
        "trees": 0.02,
        "dress": {
            "farm": {"field": [5, 16], "wagons": 1, "supplies": 4},
            "mill": {"supplies": 3},
            "mine": {"spoil": 14, "wagons": 1, "supplies": 3},
            "lodge": {"trees": 0.14, "clearing": [4, 14], "logs": 3, "supplies": 3},
            "fishery": {"supplies": 4},
        },
    },
    "boat": {"cabin_share": 0.25},  # the deckhouse is this share of the deck's length
    "cache_size": 256,  # site plans kept in memory
}

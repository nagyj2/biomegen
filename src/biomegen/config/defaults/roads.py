"""Defaults for the ``roads`` section (roads)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "pathfinder": "astar",  # "astar" (in-house default), "tcod", or "dijkstra"
    "k_neighbors": 5,  # candidate edges per POI (k-nearest)
    "civilized_connect_prob": 0.9,  # keep-probability for edges between civilized POIs
    "uncivilized_connect_prob": 0.25,  # keep-probability for edges touching uncivilized POIs
    "extra_edge_prob": 0.15,  # chance to keep a non-tree candidate edge (creates loops)
    "base_cost": 1.0,  # cost per east-west step on flat grassland; biome and relief move_cost rows scale and add to it
    "uphill_surcharge_per_km": 0.38,  # extra cost per km climbed (makes roads contour)
    "slope_cost_per_km": 0.92,  # cost per km of height change, up or down
    "water_cost": 14.0,  # cost to cross a water tile: high enough that roads prefer land and
    # never run ALONG a river, but low enough that crossing a narrow river
    # (a bridge, drawn wherever a road lies over water) beats a long detour. Ocean is unroutable regardless.
    "road_discount": 0.3,  # cost multiplier when reusing an existing road tile (encourages joins)
    "turn_cost": 0.1,  # flat penalty added whenever the path changes direction; values in
    # the 1–3× base_cost range reduce zigzagging without over-straightening
    "cardinal_only": False,  # True routes every road north, east, south or west only (no diagonal links), so the
    # map draws one box-drawing glyph set with no slashes or junction stars
    "meander_strength": 0.10,  # how far a long road wanders sideways, as a share of its length (0 = as straight as the
    # terrain allows, 0.1 a gentle wander, 0.25 very winding); it also scales a small per-tile noise added to the cost
    "meander_step_km": 60.0,  # a road is steered through a waypoint every this far along its line (a road shorter than
    # two steps is not bent), each pushed sideways by up to meander_strength x the road's length
}

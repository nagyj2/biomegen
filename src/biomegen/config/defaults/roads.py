"""Defaults for the ``roads`` section (roads)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "pathfinder": "astar",  # "astar" (in-house default), "tcod", or "dijkstra"
    "k_neighbors": 5,  # candidate edges per POI (k-nearest)
    "civilized_connect_prob": 0.9,  # keep-probability for edges between civilized POIs
    "uncivilized_connect_prob": 0.25,  # keep-probability for edges touching uncivilized POIs
    "extra_edge_prob": 0.15,  # chance to keep a non-tree candidate edge (creates loops)
    "base_cost": 1.0,  # per-step movement cost on flat ground
    "uphill_surcharge": 2.5,  # extra cost factor for climbing (makes roads contour)
    "slope_cost": 6.0,  # cost factor on absolute elevation change
    "water_cost": 14.0,  # cost to cross a water tile: high enough that roads prefer land and
    # never run ALONG a river, but low enough that crossing a narrow river
    # (a bridge) beats a long detour. Ocean is unroutable regardless.
    "mountain_cost": 14.0,  # extra cost over mountain/snow tiles
    "road_discount": 0.3,  # cost multiplier when reusing an existing road tile (encourages joins)
    "turn_cost": 0.1,  # flat penalty added whenever the path changes direction; values in
    # the 1–3× base_cost range reduce zigzagging without over-straightening
    "meander_strength": 0.30,  # deterministic per-tile noise added to cost so paths curve
    # Bridges: when a road is forced to cross a river/water tile, a "bridge" POI is placed there
    # and the crossing tile is flagged as a bridge (implemented with the roads stage in Phase 4).
    "bridges": True,
}

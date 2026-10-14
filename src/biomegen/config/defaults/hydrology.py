"""Defaults for the ``hydrology`` section (hydrology)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "flow_model": "d8",  # "d8" (default) or "dinf"
    "accumulation_threshold": 55,  # min drainage area for a tile to become a river channel
    "min_lake_size": 5,  # depression pools smaller than this are not treated as lakes
    "lake_min_depth": 0.0008,  # min (filled - elevation) for a cell to count as standing water
    "source_min_elevation": 0.55,  # rivers only start above this elevation
    "max_rivers": 24,  # cap on traced rivers (largest-accumulation sources first)
    "meander_strength": 0.0,  # extra lateral wobble added to river paths (0 = pure downhill)
    # River width grows with drainage area: a channel carrying ``ratio`` x the channelisation
    # threshold widens by ``(ratio-1) * river_width_scale`` tiles, capped at ``river_max_width``.
    # So small streams stay 1 tile; great rivers near the sea span several tiles.
    "river_width_scale": 0.5,
    "river_max_width": 5,
    "moisture_radius": 5,  # tiles within this of fresh water get a moisture boost
    "moisture_strength": 0.28,  # magnitude of the freshwater-proximity moisture boost
}

"""Defaults for the ``interiors`` section (POI interiors)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "partition": "bsp",  # "bsp" (in-house default) or "tcod_bsp"
    # Each POI interior is generated once at a CANONICAL resolution of cells_per_tile detail cells
    # per world tile across its footprint, then the detail renderer samples that single artifact
    # into whatever cell block the current scale provides - so the zoom and local views are coarse
    # vs fine samplings of the SAME interior (mirroring the biome-blend philosophy).
    "cells_per_tile": 6,
    "room_min": 4,  # min room side in detail cells
    "room_max": 10,
    # Coast strip (in canonical detail cells) kept clear between a structure and any water its
    # footprint clips: the buildable area is pulled back this many cells from the water, so a band of
    # bare biome floor (beach/grass via the blend) reads as a little shoreline around the structure -
    # like the biome blend. 0 builds right up to the water's edge. Only affects coastal POIs.
    "coast_margin": 2,
    # Bridges within settlements: when a stream or lake cuts through a village/town/city footprint,
    # PATH streets that cross non-buildable (water) ground are turned into small pedestrian bridges.
    # ``bridge_max_span`` (in interior grid cells) is the maximum crossing width that qualifies;
    # wider gaps are treated as ocean edges rather than bridgeable streams.
    "settlement_bridges": True,
    "bridge_max_span": 30,
    # When a coastal footprint loses land to the water it clips, grow the footprint (keeping the
    # anchor centred) until its dry-land area is back to nominal, capped at this multiple of the
    # nominal footprint area. Growth never overlaps another POI; water is simply carved again. 1.0
    # (or less) disables the restoration, so carved coastal structures stay smaller.
    "expand_max_factor": 2.0,
    "clutter_density": 0.10,  # fraction of free interior cells that receive clutter/furniture
    "ruin_erosion": 0.45,  # fraction of a ruined structure carved away by erosion noise
    # Per-POI footprint size variation (fraction). Each footprint dimension of a kind that HAS an
    # interior builder is scaled by a deterministic factor in [1-jitter, 1+jitter], so structures
    # of the same kind spawn a bit larger or smaller. 0 disables (every footprint stays nominal).
    "size_jitter": 0.4,
    # Outer-boundary SHAPE algorithm for the solid-building archetypes (dungeon/tower/ruin; see
    # biomegen.interiors.shapes / SHAPES registry): "rectangle" (boxy), "blob", "cellular",
    # "drunkard", "diamond", "cross", or "mixed" (default) to pick a different organic shape per
    # structure so none is square. The shape is filled solid with rooms+rock; terrain shows around
    # its organic outline. (Settlements, camps and boats use their own layout, not this shape.)
    "shape": "mixed",
    # Per-kind interior footprint in WORLD TILES (w, h), centred on the POI anchor. Render-only
    # metadata (the base ``poi_index`` array still marks just the anchor). Every kind below has an
    # interior builder (Phase 5 complete); only ``bridge`` (placed by the roads stage, absent here)
    # stays a plain map marker.
    "footprints": {
        "dungeon": [6, 4],
        "tower": [3, 3],
        "city": [7, 5],
        "town": [5, 4],
        "village": [4, 3],
        "ruin": [4, 3],
        "camp": [3, 3],
        "boat": [3, 2],
    },
}

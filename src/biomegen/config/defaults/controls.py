"""Defaults for the ``controls`` section (controls / cursor movement)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Holding Shift with an arrow key (or using capital W/A/S/D / H/J/K/L) moves this many tiles
    # at once for fast travel across the map.
    "fast_step": 8,
    "site_margin": 4,  # cells between the cursor and the edge of the screen before the site view scrolls
    # How a panned view (1:1 map, zoom, local, site) follows the cursor once it reaches the edge margin: "centre" jumps
    # the camera to centre the cursor (about half a screen, so the screen is redrawn once per half screen of travel),
    # "edge" scrolls one step at a time (a whole-screen redraw on every step).
    "pan": "centre",
}

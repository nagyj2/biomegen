"""Defaults for the ``controls`` section (controls / cursor movement)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Holding Shift with an arrow key (or using capital W/A/S/D / H/J/K/L) moves this many tiles
    # at once for fast travel across the map.
    "fast_step": 8,
}

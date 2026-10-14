"""Defaults for the ``keys`` section (key bindings)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "zoom": " ",  # step OUT a zoom level: biome<->zoom, and local->zoom
    "local": "z",  # step IN to the deeper "local" scale (zoom->local). Rebindable; most
    # terminals can't distinguish Shift+Space from Space, so a real key is used.
    "floor_up": "<",  # cycle to the floor above (towers)
    "floor_down": ">",  # cycle to the floor below (dungeons)
    "export_view": "e",  # export the current view to ./images
    "export_world": "E",  # export the whole island map to ./images
    "toggle_scale": "f",  # toggle fit-to-screen <-> 1:1 panning
    "cycle_view": "v",  # cycle the render.views (terrain, elevation, ...)
    "help": "?",  # show the key help and legend
    "refresh": "r",  # regenerate the world with a fresh random seed (unbound until phase 9 brings it back)
    "quit": "q",
}

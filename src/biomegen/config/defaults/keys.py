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
    # The chronicle pager (``--chronicle`` on a terminal) also uses help and quit; arrows, WASD and HJKL scroll.
    "search": "/",  # ask for text to find; matches are highlighted
    "search_next": "n",  # jump to the next match
    "search_prev": "N",  # jump to the previous match
    "filter_kind": "v",  # cycle the event-kind filter (all, founding, secession, ...)
    "filter_salience": "m",  # toggle major only <-> major and minor events
    "filter_years": "y",  # ask for a year range, e.g. 100-300
    "filter_realm": "p",  # ask for a realm name to keep
    "filter_clear": "c",  # drop every filter
    "top": "g",  # scroll to the first event
    "bottom": "G",  # scroll to the last event
}

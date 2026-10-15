"""How a point of interest is marked on the map.

Settlement tiers read their glyph, ASCII glyph and colours from their ``tables.tiers`` row; every other kind (the
wild POIs) reads ``render.markers`` with the shared ``render.marker_style`` colours.
"""

from __future__ import annotations

from typing import Optional

from ..config.model import Config
from .grid import RGB

_UNKNOWN = "?"


def _rgb(value: list) -> RGB:
    return int(value[0]), int(value[1]), int(value[2])


def poi_marker(
    config: Config, kind: str, ascii_only: bool = False, free: bool = False
) -> tuple[str, RGB, Optional[RGB]]:
    """Return ``(glyph, fg, bg)`` for a POI of ``kind``; ``bg`` is None to keep the terrain background.

    ``free`` is a settlement no realm holds: its tier's ``free_fg`` replaces the colour when the row has one. Looked up
    once per config, kind and state: the markers layer asks for every POI on every frame.
    """
    return config.cached(
        (__name__, kind, bool(ascii_only), bool(free)), lambda: _marker(config, kind, ascii_only, free)
    )


def _marker(config: Config, kind: str, ascii_only: bool, free: bool) -> tuple[str, RGB, Optional[RGB]]:
    tier = config.get(f"tables.tiers.{kind}", None)
    if tier is not None:
        bg = tier.get("bg")
        fg = tier["free_fg"] if free and "free_fg" in tier else tier["fg"]
        return tier["ascii" if ascii_only else "glyph"], _rgb(fg), _rgb(bg) if bg is not None else None
    style = config.get("render.marker_style")
    return config.get("render.markers").get(kind, _UNKNOWN), _rgb(style["fg"]), _rgb(style["bg"])


def poi_on_map(config: Config, kind: str) -> bool:
    """Return whether a ``kind`` POI is marked at the map scale (a tier row sets ``map_marker = false`` to hide it)."""
    return config.cached((__name__, "on_map", kind), lambda: bool(config.get(f"tables.tiers.{kind}.map_marker", True)))

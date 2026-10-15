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


def poi_marker(config: Config, kind: str, ascii_only: bool = False) -> tuple[str, RGB, Optional[RGB]]:
    """Return ``(glyph, fg, bg)`` for a POI of ``kind``; ``bg`` is None to keep the terrain background.

    Looked up once per config and kind: the markers layer asks for every POI on every frame.
    """
    return config.cached((__name__, kind, bool(ascii_only)), lambda: _marker(config, kind, ascii_only))


def _marker(config: Config, kind: str, ascii_only: bool) -> tuple[str, RGB, Optional[RGB]]:
    tier = config.get(f"tables.tiers.{kind}", None)
    if tier is not None:
        bg = tier.get("bg")
        return tier["ascii" if ascii_only else "glyph"], _rgb(tier["fg"]), _rgb(bg) if bg is not None else None
    style = config.get("render.marker_style")
    return config.get("render.markers").get(kind, _UNKNOWN), _rgb(style["fg"]), _rgb(style["bg"])

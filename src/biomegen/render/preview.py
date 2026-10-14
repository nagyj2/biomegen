"""Plain-text (no-curses) renderings of the map and zoom frames.

Useful as a quick visual check that the pure frame-construction logic is correct, for users on a
terminal without curses, and for headless verification (curses needs a real TTY). These reuse the
same :mod:`map_view` / :mod:`zoom_view` frame builders the curses renderer uses, so what you see here
mirrors the real layout (minus colour).
"""

from __future__ import annotations

from typing import Optional

from ..config.model import Config
from ..world.world import World
from .glyphs import Glyphs
from .map_view import build_biome_frame
from .state import SCALE_LOCAL, SCALE_ZOOM, ViewState, edge_pan
from .surface import display_biome_at
from .zoom_view import build_detail_frame, detail_cell_size


def render_biome_ascii(
    world: World,
    config: Config,
    area_w: int = 150,
    area_h: int = 40,
    vs: ViewState | None = None,
) -> str:
    """Return an ASCII rendering of the biome map (fit-to-screen by default)."""
    glyphs = Glyphs(config)
    vs = vs or ViewState(cx=world.width // 2, cy=world.height // 2, mode="fit")
    frame = build_biome_frame(world, vs, area_w, area_h, config)
    overrides = frame.overrides
    lines = []
    for ry in range(frame.rows):
        chars = []
        for rx in range(frame.cols):
            coord = frame.tiles[ry][rx]
            stamp = overrides[ry][rx] if overrides is not None else None
            if stamp is not None:
                chars.append(stamp[0])  # stamped interior outline wins over the terrain glyph
            elif coord is None:
                chars.append(" ")
            else:
                wx, wy = coord
                marker = _marker_glyph(world, glyphs, wx, wy)
                chars.append(marker or glyphs.biome_glyph(display_biome_at(world, wx, wy)))
        lines.append("".join(chars))
    return "\n".join(lines)


def render_detail_ascii(
    world: World,
    config: Config,
    scale: str = SCALE_ZOOM,
    area_w: int = 80,
    area_h: int = 30,
    vs: ViewState | None = None,
) -> str:
    """Return an ASCII rendering of a detail view (``scale`` = "zoom" or "local") centred on the cursor."""
    cell_w, cell_h = detail_cell_size(scale, config, area_w, area_h)
    if vs is None:
        vs = ViewState(cx=world.width // 2, cy=world.height // 2, scale=scale)
        vs.cam_x = edge_pan(0, vs.cx, max(1, area_w // cell_w), world.width)
        vs.cam_y = edge_pan(0, vs.cy, max(1, area_h // cell_h), world.height)
    frame = build_detail_frame(world, config, vs, area_w, area_h, cell_w, cell_h)
    return "\n".join("".join(cell[0] for cell in row) for row in frame.cells)


def render_zoom_ascii(
    world: World,
    config: Config,
    area_w: int = 80,
    area_h: int = 30,
    vs: ViewState | None = None,
) -> str:
    """Return an ASCII rendering of the mid 'zoom' detail view."""
    return render_detail_ascii(world, config, SCALE_ZOOM, area_w, area_h, vs)


def render_local_ascii(
    world: World,
    config: Config,
    area_w: int = 80,
    area_h: int = 30,
    vs: ViewState | None = None,
) -> str:
    """Return an ASCII rendering of the close 'local' detail view."""
    return render_detail_ascii(world, config, SCALE_LOCAL, area_w, area_h, vs)


def _marker_glyph(world: World, glyphs: Glyphs, x: int, y: int) -> Optional[str]:
    """Return a POI/road marker glyph for a tile, or None (so the biome glyph is used)."""
    i = int(world.poi_index[y, x])
    if 0 <= i < len(world.pois):
        return glyphs.marker(world.pois[i].kind, "?")
    if world.road[y, x]:
        return glyphs.marker("road", "+")
    return None

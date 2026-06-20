"""The interactive curses application: bootstrap + main loop.

``run(world, config)`` is the single public entry. It is an *event-driven* loop: it blocks on
``getch`` and redraws only after input (zero CPU while idle, no tearing). The cursor is a biome-tile
coordinate shared by all view modes; the camera is edge-panned so it scrolls only when the cursor
reaches a viewport edge. All reads go through the base world composited with a (currently empty)
:class:`~biomegen.world.overlay.Overlay`, so the gameplay-mutation path is wired in from the start.
"""

from __future__ import annotations

import curses
import os
from typing import Callable, Optional

import numpy as np

from ..config.model import Config
from ..util import rng
from ..world.overlay import Overlay
from ..world.tile import WaterType
from ..world.world import World
from . import map_view, status
from .glyphs import Glyphs
from .input import resolve_action
from .map_view import Frame, build_biome_frame
from .palette import Palette
from .state import SCALE_BIOME, SCALE_LOCAL, SCALE_ZOOM, ViewState, center_cam, clamp, edge_pan
from .status import safe_addstr
from .zoom_view import ZoomFrame, build_detail_frame, detail_cell_size


def run(world: World, config: Config) -> None:
    """Launch the curses UI for ``world``. Restores the terminal on exit (via ``curses.wrapper``)."""
    curses.wrapper(_main, world, config)


def _initial_cursor(world: World) -> tuple[int, int]:
    """Place the cursor on the land tile nearest the map centre (fallback: the centre)."""
    land = world.water_type == int(WaterType.NONE)
    if land.any():
        ys, xs = np.nonzero(land)
        d = (xs - world.width / 2) ** 2 + (ys - world.height / 2) ** 2
        i = int(np.argmin(d))
        return int(xs[i]), int(ys[i])
    return world.width // 2, world.height // 2


def _interesting_cursor(world: World) -> tuple[int, int]:
    """Place the cursor on the most 'interesting' land feature - used when entering a NEW world.

    Interest is ranked by the same priority the map down-sampler uses (POI > road > notable
    terrain), restricted to land so the cursor never starts on open water. Among the equally
    top-ranked tiles the one nearest the land centroid is chosen, so the start point is a salient
    feature near the middle of the island rather than off in a corner. (Returning from a zoom keeps
    the previous cursor instead - that is handled by simply not calling this.)
    """
    land = world.water_type == int(WaterType.NONE)
    if not land.any():
        return _initial_cursor(world)

    max_biome = int(world.biome.max()) + 1
    lut = np.zeros(max_biome, dtype=float)
    for biome_int, prio_val in map_view._BIOME_PRIORITY.items():
        if biome_int < max_biome:
            lut[biome_int] = prio_val
    priority = lut[world.biome]
    priority[~land] = -1.0  # never start on open water
    priority[world.road != 0] = map_view._ROAD_PRIORITY
    priority[world.poi_index >= 0] = map_view._POI_PRIORITY

    best = priority.max()
    cand = (priority == best) & land
    ys, xs = np.nonzero(cand)
    lys, lxs = np.nonzero(land)
    cxc, cyc = float(lxs.mean()), float(lys.mean())
    i = int(np.argmin((xs - cxc) ** 2 + (ys - cyc) ** 2))
    return int(xs[i]), int(ys[i])


def _tile_glyph(world: World, glyphs: Glyphs, overlay: Overlay, x: int, y: int) -> str:
    """Glyph for a biome-map tile: overlay edit > POI marker > road marker > biome glyph."""
    edit = overlay.get_surface(x, y)
    if edit and "glyph" in edit:
        return edit["glyph"]
    i = int(world.poi_index[y, x])
    if 0 <= i < len(world.pois):
        return glyphs.marker(world.pois[i].kind, "?")
    if world.road[y, x]:
        return glyphs.marker("road", "+")
    return glyphs.biome_glyph(int(world.biome[y, x]))


def _draw_biome(
    stdscr: curses.window,
    world: World,
    frame: Frame,
    glyphs: Glyphs,
    palette: Palette,
    overlay: Overlay,
) -> None:
    """Paint a biome-map frame (fit or 1:1) and the cursor highlight."""
    for ry in range(frame.rows):
        row = frame.tiles[ry]
        for rx in range(frame.cols):
            coord = row[rx]
            if coord is None:
                continue
            wx, wy = coord
            glyph = _tile_glyph(world, glyphs, overlay, wx, wy)
            attr = palette.tile_attr(world, wx, wy)
            # POI/road markers get the bold marker attribute on top of the tile colour.
            if int(world.poi_index[wy, wx]) >= 0 or world.road[wy, wx]:
                attr |= palette.marker_attr
            safe_addstr(stdscr, ry, rx, glyph, attr)
    if frame.cursor is not None:
        ccol, crow = frame.cursor
        coord = frame.tiles[crow][ccol] if 0 <= crow < frame.rows and 0 <= ccol < frame.cols else None
        glyph = _tile_glyph(world, glyphs, overlay, *coord) if coord else " "
        safe_addstr(stdscr, crow, ccol, glyph, palette.cursor_attr)


def _draw_zoom(stdscr: curses.window, frame: ZoomFrame, palette: Palette) -> None:
    """Paint a magnified zoom frame and outline the focused (cursor) tile."""
    for ry in range(frame.rows):
        row = frame.cells[ry]
        for rx in range(frame.cols):
            glyph, biome_int = row[rx]
            safe_addstr(stdscr, ry, rx, glyph, palette.biome_attr(biome_int))
    if frame.cursor_rect is not None:
        x0, y0, x1, y1 = frame.cursor_rect
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                glyph, biome_int = frame.cells[yy][xx]
                safe_addstr(stdscr, yy, xx, glyph, palette.biome_attr(biome_int) | curses.A_REVERSE)


def _visible_biomes_map(world: World, frame: Frame) -> set[int]:
    """Collect the biome ints actually shown in a biome-map frame (for an on-screen-only legend)."""
    seen = set()
    for row in frame.tiles:
        for coord in row:
            if coord is not None:
                wx, wy = coord
                seen.add(int(world.biome[wy, wx]))
    return seen


def _draw(
    stdscr: curses.window,
    world: World,
    config: Config,
    vs: ViewState,
    glyphs: Glyphs,
    palette: Palette,
    overlay: Overlay,
) -> None:
    """Render one full frame: the active map view plus the status panel."""
    max_y, max_x = stdscr.getmaxyx()
    status_h = clamp(int(config.get("render.status_height")), 3, max(3, max_y - 2))
    map_h = max_y - status_h
    area_w = max_x

    stdscr.erase()
    if map_h < 1 or area_w < 1:
        safe_addstr(stdscr, 0, 0, "terminal too small - enlarge the window")
        stdscr.refresh()
        return

    if vs.is_detail:
        # ZOOM and LOCAL share one renderer; only the per-tile cell size differs.
        cell_w, cell_h = detail_cell_size(vs.scale, config, area_w, map_h)
        tiles_w = max(1, area_w // cell_w)
        tiles_h = max(1, map_h // cell_h)
        # Centre on the cursor when we just entered/changed scale; otherwise pan only at the edges.
        if vs.recenter:
            vs.cam_x = center_cam(vs.cx, tiles_w, world.width)
            vs.cam_y = center_cam(vs.cy, tiles_h, world.height)
            vs.recenter = False
        else:
            vs.cam_x = edge_pan(vs.cam_x, vs.cx, tiles_w, world.width)
            vs.cam_y = edge_pan(vs.cam_y, vs.cy, tiles_h, world.height)
        detail_frame = build_detail_frame(world, config, vs, area_w, map_h, cell_w, cell_h)
        _draw_zoom(stdscr, detail_frame, palette)
        visible = {b for row in detail_frame.cells for (_g, b) in row}
    else:
        if vs.mode == "onetoone":
            if vs.recenter:
                vs.cam_x = center_cam(vs.cx, area_w, world.width)
                vs.cam_y = center_cam(vs.cy, map_h, world.height)
            else:
                vs.cam_x = edge_pan(vs.cam_x, vs.cx, area_w, world.width)
                vs.cam_y = edge_pan(vs.cam_y, vs.cy, map_h, world.height)
        vs.recenter = False
        biome_frame = build_biome_frame(world, vs, area_w, map_h)
        _draw_biome(stdscr, world, biome_frame, glyphs, palette, overlay)
        visible = _visible_biomes_map(world, biome_frame)

    status.draw(stdscr, world, config, vs, glyphs, palette, map_h, status_h, area_w, visible)
    stdscr.refresh()


def _main(stdscr: curses.window, world: World, config: Config, get_key: Optional[Callable[[], int]] = None) -> None:
    """curses.wrapper target: set up, then run the input/redraw loop until the user quits.

    ``get_key`` defaults to ``stdscr.getch``; tests inject a scripted key source so the real loop
    (palette setup, drawing, input handling) can be exercised headlessly.
    """
    try:
        curses.curs_set(0)  # hide the hardware cursor; we draw our own
    except curses.error:
        pass
    stdscr.keypad(True)
    if get_key is None:
        get_key = stdscr.getch

    palette = Palette(config)
    palette.setup(world)
    glyphs = Glyphs(config)
    overlay = Overlay()

    vs = ViewState(mode=config.get("render.default_view", "fit"))
    vs.cx, vs.cy = _interesting_cursor(world)  # new world -> start on a notable feature
    vs.notify(f"colour mode: {palette.mode}")

    while True:
        _draw(stdscr, world, config, vs, glyphs, palette, overlay)
        action = resolve_action(get_key(), config)
        name = action[0]
        if name == "quit":
            break
        elif name == "move":
            vs.cx = clamp(vs.cx + action[1], 0, world.width - 1)
            vs.cy = clamp(vs.cy + action[2], 0, world.height - 1)
        elif name == "zoom":
            # Space steps OUT: biome->zoom (enter), zoom->biome (exit), local->zoom (back out one).
            if vs.scale == SCALE_BIOME:
                vs.scale = SCALE_ZOOM
            elif vs.scale == SCALE_ZOOM:
                vs.scale = SCALE_BIOME
            else:  # SCALE_LOCAL
                vs.scale = SCALE_ZOOM
            vs.recenter = True
            vs.notify(f"scale: {vs.scale}")
        elif name == "local":
            # Deeper key steps IN: biome->zoom, zoom->local, local stays (already deepest).
            if vs.scale == SCALE_BIOME:
                vs.scale = SCALE_ZOOM
                vs.recenter = True
            elif vs.scale == SCALE_ZOOM:
                vs.scale = SCALE_LOCAL
                vs.recenter = True
            vs.notify(f"scale: {vs.scale}")
        elif name == "toggle_scale":
            if vs.scale != SCALE_BIOME:
                vs.notify("fit/1:1 applies to the biome map only")
            else:
                vs.mode = "onetoone" if vs.mode == "fit" else "fit"
                if vs.mode == "onetoone":
                    vs.recenter = True
                vs.notify(f"view: {'1:1 pan' if vs.mode == 'onetoone' else 'fit-to-screen'}")
        elif name == "refresh":
            # Regenerate the whole world from a fresh random seed (echoed so it stays reproducible).
            new_seed = rng.normalize_seed(int.from_bytes(os.urandom(8), "big"))
            from .. import pipeline

            world = pipeline.generate(config, new_seed)
            palette = Palette(config)
            palette.setup(world)  # region colours changed -> rebuild the palette
            overlay = Overlay()  # a new world has no runtime edits
            # A fresh world is shown from the biome map, cursor on its most interesting feature.
            vs.scale = SCALE_BIOME
            vs.mode = config.get("render.default_view", "fit")
            vs.cx, vs.cy = _interesting_cursor(world)
            vs.cam_x = vs.cam_y = 0
            vs.floor = 0
            vs.recenter = True
            vs.notify(f"new world: seed {new_seed}")
        elif name == "floor":
            vs.notify("no floors here (POI interiors arrive in a later build)")
        elif name == "export":
            vs.notify("export arrives in a later build")
        # "resize" / "none": just redraw on the next loop iteration.

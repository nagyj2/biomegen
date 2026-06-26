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
from ..world.entities import POI
from ..world.interiors import INTERIOR_BUILDERS, footprint_origin
from ..world.overlay import Overlay
from ..world.tile import INTERIOR_COLOR_BASE, WaterType
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


def _poi_under_cursor(world: World, vs: ViewState) -> Optional[POI]:
    """Return the interior-bearing POI whose footprint covers the cursor, or None.

    Footprint coverage is computed from the POI list (the base ``poi_index`` array still marks only the
    anchor), so this is what drives floor cycling - the cursor is "inside" a structure when it sits
    anywhere on that structure's footprint.
    """
    for poi in world.pois:
        if not INTERIOR_BUILDERS.has(poi.kind):
            continue
        fw, fh = poi.footprint
        if fw <= 0 or fh <= 0:
            continue
        tx0, ty0 = footprint_origin(poi)
        if tx0 <= vs.cx < tx0 + fw and ty0 <= vs.cy < ty0 + fh:
            return poi
    return None


def _sync_floor_to_cursor(world: World, vs: ViewState, prev_poi_id: object) -> object:
    """Keep ``vs.floor`` valid for the structure under the cursor; return the new tracking id.

    Entering a new structure starts at its ground/entry floor; moving within the same one preserves
    (and clamps) the chosen floor; off any structure resets to 0.
    """
    poi = _poi_under_cursor(world, vs)
    cur_id = id(poi) if poi is not None else None
    if cur_id != prev_poi_id:
        # Enter at the ground/entry level (floor 0 by the floors_for convention) - the floor you walk
        # in at, whether the structure descends (dungeon) or rises (tower) from it.
        vs.floor = 0
    elif poi is not None:
        vs.floor = clamp(vs.floor, poi.lowest_floor, poi.lowest_floor + poi.floor_count - 1)
    return cur_id


def _cycle_floor(world: World, vs: ViewState, delta: int) -> None:
    """Move up/down a floor on the structure under the cursor (or explain why it can't)."""
    poi = _poi_under_cursor(world, vs)
    if poi is None:
        vs.notify("no interior here - move onto a structure to cycle floors")
        return
    if poi.floor_count <= 1:
        vs.notify(f"{poi.name or poi.kind}: single floor")
        return
    top = poi.lowest_floor + poi.floor_count - 1
    new = clamp(vs.floor + delta, poi.lowest_floor, top)
    if new == vs.floor:
        vs.notify("no further floor that way")
        return
    vs.floor = new
    # Floor 0 is the ground/entry level either way (dungeons go negative below it, towers positive above).
    vs.notify(f"{poi.name or poi.kind}: floor {vs.floor} ({'ground' if vs.floor == 0 else vs.floor})")


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
    """Paint a biome-map frame (fit or 1:1), any stamped interior outlines, and the cursor highlight."""
    overrides = frame.overrides
    for ry in range(frame.rows):
        row = frame.tiles[ry]
        for rx in range(frame.cols):
            coord = row[rx]
            if coord is None:
                continue
            stamp = overrides[ry][rx] if overrides is not None else None
            if stamp is not None:
                # A scaled interior cell wins over the terrain tile (this is the dungeon's outline).
                glyph, color_id = stamp
                safe_addstr(stdscr, ry, rx, glyph, palette.zoom_attr(color_id))
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
        in_bounds = 0 <= crow < frame.rows and 0 <= ccol < frame.cols
        stamp = overrides[crow][ccol] if (overrides is not None and in_bounds) else None
        coord = frame.tiles[crow][ccol] if in_bounds else None
        glyph = stamp[0] if stamp is not None else (_tile_glyph(world, glyphs, overlay, *coord) if coord else " ")
        safe_addstr(stdscr, crow, ccol, glyph, palette.cursor_attr)


def _draw_zoom(stdscr: curses.window, frame: ZoomFrame, palette: Palette) -> None:
    """Paint a magnified zoom frame and outline the focused (cursor) tile.

    Each cell carries a *colour id* (biome int, or an interior :class:`Cell` colour encoded above
    ``INTERIOR_COLOR_BASE``); ``palette.zoom_attr`` resolves either to a curses attribute.
    """
    for ry in range(frame.rows):
        row = frame.cells[ry]
        for rx in range(frame.cols):
            glyph, color_id = row[rx]
            safe_addstr(stdscr, ry, rx, glyph, palette.zoom_attr(color_id))
    if frame.cursor_rect is not None:
        x0, y0, x1, y1 = frame.cursor_rect
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                glyph, color_id = frame.cells[yy][xx]
                safe_addstr(stdscr, yy, xx, glyph, palette.zoom_attr(color_id) | curses.A_REVERSE)


def _visible_biomes_map(world: World, frame: Frame) -> set[int]:
    """Collect the biome ints actually shown in a biome-map frame (for an on-screen-only legend)."""
    seen = set()
    for row in frame.tiles:
        for coord in row:
            if coord is not None:
                wx, wy = coord
                seen.add(int(world.biome[wy, wx]))
    return seen


def _visible_cells_map(frame: Frame) -> set[int]:
    """Collect the interior Cell ints stamped on a biome-map frame (for the interior legend)."""
    if frame.overrides is None:
        return set()
    return {stamp[1] - INTERIOR_COLOR_BASE for row in frame.overrides for stamp in row if stamp is not None}


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
        detail_frame = build_detail_frame(world, config, vs, area_w, map_h, cell_w, cell_h, overlay)
        _draw_zoom(stdscr, detail_frame, palette)
        visible = {b for row in detail_frame.cells for (_g, b) in row if b < INTERIOR_COLOR_BASE}
        visible_cells = {
            b - INTERIOR_COLOR_BASE for row in detail_frame.cells for (_g, b) in row if b >= INTERIOR_COLOR_BASE
        }
    else:
        if vs.mode == "onetoone":
            if vs.recenter:
                vs.cam_x = center_cam(vs.cx, area_w, world.width)
                vs.cam_y = center_cam(vs.cy, map_h, world.height)
            else:
                vs.cam_x = edge_pan(vs.cam_x, vs.cx, area_w, world.width)
                vs.cam_y = edge_pan(vs.cam_y, vs.cy, map_h, world.height)
        vs.recenter = False
        biome_frame = build_biome_frame(world, vs, area_w, map_h, config, overlay)
        _draw_biome(stdscr, world, biome_frame, glyphs, palette, overlay)
        visible = _visible_biomes_map(world, biome_frame)
        visible_cells = _visible_cells_map(biome_frame)

    status.draw(stdscr, world, config, vs, glyphs, palette, map_h, status_h, area_w, visible, visible_cells)
    stdscr.refresh()


def _export(
    stdscr: curses.window,
    world: World,
    config: Config,
    vs: ViewState,
    overlay: Overlay,
    target: str,
) -> None:
    """Write the current view (``target == "view"``) or the whole island (``"world"``) to disk.

    The screen dimensions are recomputed exactly as :func:`_draw` does so a "view" export captures
    the same frame the user is looking at (same scale, camera and footprints). Failures are reported
    on the HUD rather than crashing the session.
    """
    from .. import export

    try:
        if target == "world":
            paths = export.export_world(world, config, overlay)
        else:
            max_y, max_x = stdscr.getmaxyx()
            status_h = clamp(int(config.get("render.status_height")), 3, max(3, max_y - 2))
            paths = export.export_view(world, config, vs, overlay, area_w=max_x, area_h=max_y - status_h)
    except Exception as exc:  # never let an export error kill the explorer
        vs.notify(f"export failed: {exc}")
        return

    names = ", ".join(os.path.basename(p) for p in paths)
    if any(p.endswith(".png") for p in paths):
        vs.notify(f"exported {names}")
    else:
        vs.notify(f"exported {names} (install Pillow for PNG)")


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
    prev_poi_id: object = None  # tracks the structure under the cursor, to reset the floor on entry

    while True:
        prev_poi_id = _sync_floor_to_cursor(world, vs, prev_poi_id)
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
            _cycle_floor(world, vs, action[1])
        elif name == "export":
            _export(stdscr, world, config, vs, overlay, action[1])
        # "resize" / "none": just redraw on the next loop iteration.

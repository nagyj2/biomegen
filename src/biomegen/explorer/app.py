"""The interactive explorer: compose a frame from the layered renderer, diff-write it, read a key, repeat.

``run`` is event driven: it redraws only after input. While it waits it prepares the next frames in small steps
(:mod:`~biomegen.explorer.prefetch`: nearby terrain chunks and site plans), stopping as soon as a key arrives, then
blocks, so an idle explorer soon uses no CPU. The
frame is a terminal-sized :class:`~biomegen.render.grid.CellGrid` (the map on top, the info panel below) that the
:class:`~biomegen.explorer.writer.DiffWriter` sends as minimal updates. Everything outside ``run`` is pure, so the
whole loop is tested with a scripted key source and an in-memory terminal.
"""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional, TextIO

from ..config.model import Config
from ..render.cache import RenderCache
from ..render.fit import FitSampler
from ..render.grid import CellGrid
from ..render.layers import Seen, build_grid
from ..render.views import View, resolve_view, view_names
from ..sampling.detail import SCALE_SITE, DetailSampler, centre_camera, detail_cell_size
from ..sampling.sampler import Sampler
from ..sites import SiteGeometry, site_geometry, window_sampler
from ..world.overlay import Overlay
from ..world.reader import WorldReader
from ..world.world import World
from .exports import export_screen, export_world
from .history_viewer import Stop, history_loop, initial_state, present_moment
from .input import Action, KeyReader, make_reader, resolve_action
from .panel import build_panel, draw_help, panel_color
from .prefetch import idle_work
from .state import (
    MODE_FIT,
    MODE_ONE_TO_ONE,
    ViewState,
    clamp,
    cycle_floor,
    initial_cursor,
    move_cursor,
    pan,
    pan_view,
    pan_viewport,
    step_in,
    step_out,
    sync_floor,
    toggle_mode,
)
from .ticks import Clock, NoTicks, TickSource, next_token, sim_status
from .writer import DiffWriter

Size = tuple[int, int]  # (columns, rows)


@dataclass
class Frame:
    """One composed frame.

    Attributes:
        screen: The whole terminal: map, cursor, panel and any help overlay.
        map_grid: The map as drawn, without the cursor (what ``e`` exports).
        view_name: The view that was drawn.
        sampler: The sampler the map was drawn through (``None`` when nothing was drawn), for idle-time prefetch.
    """

    screen: CellGrid
    map_grid: CellGrid
    view_name: str
    sampler: Optional[Sampler] = None


def _draw(
    cache: Optional[RenderCache],
    world: World,
    config: Config,
    view: View,
    sampler: Sampler,
    overlay: Overlay,
    ascii_only: bool,
    color: bool,
    floor: int,
    seen: Seen,
    reader: Optional[WorldReader] = None,
) -> CellGrid:
    """Draw the map through ``sampler``: from the render cache when the explorer keeps one, else from scratch."""
    if cache is None:
        return build_grid(
            world, config, view, sampler, overlay, ascii_only, color, floor=floor, seen=seen, reader=reader
        )
    return cache.draw(world, config, view, sampler, overlay, ascii_only, color, floor=floor, seen=seen, reader=reader)


def _paste(screen: CellGrid, grid: CellGrid, top: int) -> None:
    rows, cols = min(grid.rows, screen.rows - top), min(grid.cols, screen.cols)
    screen.glyph[top : top + rows, :cols] = grid.glyph[:rows, :cols]
    screen.fg[top : top + rows, :cols] = grid.fg[:rows, :cols]
    screen.bg[top : top + rows, :cols] = grid.bg[:rows, :cols]
    screen.bold[top : top + rows, :cols] = grid.bold[:rows, :cols]


def _reverse(grid: CellGrid, rows: slice, cols: slice) -> None:
    """Swap foreground and background in a rectangle: the cursor highlight."""
    fg = grid.fg[rows, cols].copy()
    grid.fg[rows, cols] = grid.bg[rows, cols]
    grid.bg[rows, cols] = fg


def _apply_pan(state: ViewState, world: World, view_w: int, view_h: int) -> None:
    """Scroll the map camera by the pending pan, dragging the cursor if it would leave the viewport."""
    if not (state.pan_x or state.pan_y):
        return
    state.cam_x, state.cx = pan_viewport(state.cam_x, state.cx, view_w, world.width, 1, state.pan_x)
    state.cam_y, state.cy = pan_viewport(state.cam_y, state.cy, view_h, world.height, 1, state.pan_y)


def _map_sampler(
    world: World, config: Config, state: ViewState, area: Size, reader: Optional[WorldReader] = None
) -> Sampler:
    """Return the sampler for the current scale and mode, moving the camera as the cursor needs."""
    cols, rows = area
    mode = str(config.get("controls.pan"))
    if state.is_detail:
        cell_w, cell_h = detail_cell_size(state.scale, config, cols, rows)
        tiles_w, tiles_h = max(1, cols // cell_w), max(1, rows // cell_h)
        if state.recenter:
            state.cam_x = centre_camera(state.cx, tiles_w, world.width)
            state.cam_y = centre_camera(state.cy, tiles_h, world.height)
        else:
            _apply_pan(state, world, tiles_w, tiles_h)
            state.cam_x = pan(state.cam_x, state.cx, tiles_w, world.width, 1, mode)
            state.cam_y = pan(state.cam_y, state.cy, tiles_h, world.height, 1, mode)
        state.recenter = False
        state.pan_x = state.pan_y = 0
        return DetailSampler(world, config, cell_w, cell_h, state.cam_x, state.cam_y, tiles_w, tiles_h, state.scale)
    if state.mode == MODE_ONE_TO_ONE:
        if state.recenter:
            state.cam_x = centre_camera(state.cx, cols, world.width)
            state.cam_y = centre_camera(state.cy, rows, world.height)
        else:
            _apply_pan(state, world, cols, rows)
            state.cam_x = pan(state.cam_x, state.cx, cols, world.width, 1, mode)
            state.cam_y = pan(state.cam_y, state.cy, rows, world.height, 1, mode)
        state.recenter = False
        state.pan_x = state.pan_y = 0
        return Sampler.viewport(world, rows, cols, x0=float(state.cam_x), y0=float(state.cam_y))
    state.recenter = False
    state.pan_x = state.pan_y = 0
    return FitSampler(world, config, cols, rows, reader)


def _highlight_cursor(grid: CellGrid, sampler: Sampler, state: ViewState) -> None:
    """Reverse the cursor's cell, or its whole tile block at the detail scales."""
    if isinstance(sampler, DetailSampler):
        left, top = (state.cx - sampler.cam_x) * sampler.cell_w, (state.cy - sampler.cam_y) * sampler.cell_h
        rows = slice(max(0, top), min(grid.rows, top + sampler.cell_h))
        cols = slice(max(0, left), min(grid.cols, left + sampler.cell_w))
        if rows.start < rows.stop and cols.start < cols.stop:
            _reverse(grid, rows, cols)
        return
    cell = sampler.cell_of(state.cx, state.cy)
    if cell is not None:
        _reverse(grid, slice(cell[1], cell[1] + 1), slice(cell[0], cell[0] + 1))


def _apply_site_pan(state: ViewState, geometry: SiteGeometry, cols: int, rows: int, margin: int) -> None:
    """Scroll the site camera by the pending pan, dragging the cell cursor (and its tile) if it would leave the view."""
    if not (state.pan_x or state.pan_y):
        return
    state.site_cam_x, state.px = pan_viewport(state.site_cam_x, state.px, cols, geometry.cols, margin, state.pan_x)
    state.site_cam_y, state.py = pan_viewport(state.site_cam_y, state.py, rows, geometry.rows, margin, state.pan_y)
    x, y = geometry.position_of(state.px, state.py)
    state.cx, state.cy = round(x), round(y)


def _site_view(
    world: World,
    config: Config,
    view_name: str,
    state: ViewState,
    overlay: Overlay,
    area: Size,
    seen: Seen,
    geometry: SiteGeometry,
    color: bool,
    ascii_only: bool,
    cache: Optional[RenderCache] = None,
    reader: Optional[WorldReader] = None,
) -> tuple[CellGrid, CellGrid, Optional[Sampler]]:
    """Draw the part of the open site's window that fits ``area``; return ``(map grid, shown grid, sampler)``.

    The camera, in cells, scrolls over the window as the cursor nears an edge; only the visible cells are drawn. A
    window smaller than the area is centred, the outside left blank. The cursor is one cell.
    """
    cols, rows = area
    margin = int(config.get("controls.site_margin"))
    if state.recenter:
        state.site_cam_x = centre_camera(state.px, cols, geometry.cols)
        state.site_cam_y = centre_camera(state.py, rows, geometry.rows)
    else:
        _apply_site_pan(state, geometry, cols, rows, margin)
        mode = str(config.get("controls.pan"))
        state.site_cam_x = pan(state.site_cam_x, state.px, cols, geometry.cols, margin, mode)
        state.site_cam_y = pan(state.site_cam_y, state.py, rows, geometry.rows, margin, mode)
    state.recenter = False
    state.pan_x = state.pan_y = 0
    view = CellGrid(rows, cols)
    sampler: Optional[Sampler] = None
    src_rows = slice(max(0, state.site_cam_y), min(geometry.rows, state.site_cam_y + rows))
    src_cols = slice(max(0, state.site_cam_x), min(geometry.cols, state.site_cam_x + cols))
    dst_rows = slice(src_rows.start - state.site_cam_y, src_rows.stop - state.site_cam_y)
    dst_cols = slice(src_cols.start - state.site_cam_x, src_cols.stop - state.site_cam_x)
    if src_rows.stop > src_rows.start and src_cols.stop > src_cols.start:
        # Only the cells on screen are drawn; they match the whole window's cells exactly.
        sampler = window_sampler(
            world,
            config,
            geometry,
            (src_cols.start, src_rows.start),
            (src_rows.stop - src_rows.start, src_cols.stop - src_cols.start),
        )
        part = _draw(
            cache,
            world,
            config,
            resolve_view(config, view_name),
            sampler,
            overlay,
            ascii_only,
            color,
            state.floor,
            seen,
            reader,
        )
        for name in ("glyph", "fg", "bg", "bold"):
            getattr(view, name)[dst_rows, dst_cols] = getattr(part, name)
    shown = CellGrid(rows, cols)
    for name in ("glyph", "fg", "bg", "bold"):
        getattr(shown, name)[...] = getattr(view, name)
    cursor_row, cursor_col = state.py - state.site_cam_y, state.px - state.site_cam_x
    if 0 <= cursor_row < rows and 0 <= cursor_col < cols:
        _reverse(shown, slice(cursor_row, cursor_row + 1), slice(cursor_col, cursor_col + 1))
    return view, shown, sampler


def compose_frame(
    world: World,
    config: Config,
    state: ViewState,
    overlay: Overlay,
    size: Size,
    color: bool = True,
    ascii_only: bool = False,
    help_open: bool = False,
    cache: Optional[RenderCache] = None,
    reader: Optional[WorldReader] = None,
    sim_status: str = "",
) -> Frame:
    """Compose one terminal-sized frame for ``state``: the map with its cursor, the panel, and the help overlay.

    With a ``cache`` (the explorer keeps one) the map reuses what earlier frames drew; the frame is the same. The
    realms, owners, places and manifests are read through ``reader`` (default: the world as generated) and
    ``sim_status`` is the simulation's clock for the panel (blank when none runs).
    """
    cols, rows = size
    names = view_names(config)
    view_name = names[state.view_index % len(names)]
    panel_height = clamp(int(config.get("render.status_height")), 3, max(3, rows - 2))
    map_rows = rows - panel_height
    screen = CellGrid(rows, cols, bg=panel_color(config, "bg"), fg=panel_color(config, "fg"))
    if map_rows < 1 or cols < 1:
        text = "terminal too small - enlarge the window"[:cols]
        screen.glyph[0, : len(text)] = list(text)
        return Frame(screen, screen, view_name)
    seen = Seen()
    geometry = site_geometry(state.poi, config) if state.scale == SCALE_SITE and state.poi is not None else None
    if geometry is not None:
        map_grid, shown, sampler = _site_view(
            world, config, view_name, state, overlay, (cols, map_rows), seen, geometry, color, ascii_only, cache, reader
        )
    else:
        sampler = _map_sampler(world, config, state, (cols, map_rows), reader)
        map_grid = _draw(
            cache,
            world,
            config,
            resolve_view(config, view_name),
            sampler,
            overlay,
            ascii_only,
            color,
            state.floor,
            seen,
            reader,
        )
        shown = CellGrid(map_grid.rows, map_grid.cols)
        for name in ("glyph", "fg", "bg", "bold"):
            getattr(shown, name)[...] = getattr(map_grid, name)
        _highlight_cursor(shown, sampler, state)
    _paste(screen, shown, 0)
    panel = build_panel(
        world, config, state, view_name, seen, cols, panel_height, ascii_only, reader=reader, sim_status=sim_status
    )
    _paste(screen, panel, map_rows)
    if help_open:
        draw_help(screen, config)
    return Frame(screen, map_grid, view_name, sampler)


def _export(
    world: World,
    config: Config,
    state: ViewState,
    overlay: Overlay,
    frame: Frame,
    target: str,
    reader: Optional[WorldReader] = None,
) -> None:
    """Write the screen's map (``view``) or the whole world (``world``); failures go to the panel, not a crash."""
    try:
        if target == "world":
            paths = export_world(world, config, frame.view_name, overlay, reader)
        else:
            paths = export_screen(world, config, frame.map_grid, state.scale, frame.view_name)
    except Exception as error:  # never let an export error kill the explorer
        state.notify(f"export failed: {error}")
        return
    names = ", ".join(path.rsplit("/", 1)[-1] for path in paths)
    suffix = "" if any(path.endswith(".png") for path in paths) else " (install Pillow for PNG)"
    state.notify(f"exported {names}{suffix}")


def _view_action(
    world: World, config: Config, state: ViewState, name: str, reader: Optional[WorldReader] = None
) -> None:
    """Apply a zoom, local, fit-toggle or view-cycle key to the view state and say what changed."""
    if name == "zoom":
        step_out(state)
        state.notify(f"scale: {state.scale}")
    elif name == "local":
        step_in(world, config, state, reader)
        state.notify(f"scale: {state.scale}")
    elif name == "toggle_scale":
        toggle_mode(state)
    else:
        state.view_index = (state.view_index + 1) % len(view_names(config))
        state.notify(f"view: {view_names(config)[state.view_index]}")


def _restart(
    world: World,
    config: Config,
    source: TickSource,
    clock: Clock,
    regenerate: Optional[Callable[[], World]],
) -> tuple[World, Overlay, RenderCache, ViewState]:
    """Start again from the world's seed: the same world made anew, with no overlay edits, a fresh view and cache, the
    clock at normal speed and the tick source told to forget its state."""
    from biomegen import pipeline  # the explorer sits above the pipeline in the layering

    fresh = regenerate() if regenerate is not None else pipeline.generate(config, world.master_seed)
    source.reset(fresh)
    clock.reset()
    state = ViewState(mode=config.get("render.default_view", MODE_FIT))
    state.cx, state.cy = initial_cursor(fresh, config)
    state.notify(f"restarted from seed {fresh.master_seed}")
    return fresh, Overlay(), RenderCache(config), state


def _clock_message(source: TickSource, clock: Clock, name: str, action: Action) -> str:
    """Apply a pause or speed key to the clock and return what to tell the user (nothing ticks without a source)."""
    if not source.active:
        return "no simulation is running"
    return clock.toggle_pause() if name == "pause" else clock.step(action[1])


def history_start(world: World, config: Config, state: ViewState) -> Stop:
    """Return the moment the history viewer opens at: the latest event at the cursor, else the present."""
    events = world.events_at(state.cx, state.cy)
    if events:
        latest = max(events, key=lambda event: (event.year, event.month, event.id))
        return latest.year, latest.month, latest.id
    return present_moment(world, config)


def _drain_moves(world: World, config: Config, state: ViewState, reader: KeyReader) -> Optional[Action]:
    """Apply every move key already waiting, without drawing between them; return the first other action, if any.

    Held arrow keys repeat faster than a frame can be drawn. Drawing once per repeat would leave a backlog that keeps
    the cursor moving after the key is let go, so the waiting moves are applied one by one and only the end is drawn.
    """
    while reader.pending():
        action = resolve_action(reader.read_key(), config)
        if action[0] == "move":
            move_cursor(world, config, state, action[1], action[2])
        elif action[0] == "pan":
            pan_view(world, config, state, action[1], action[2])
        else:
            return action
    return None


def run(
    world: World,
    config: Config,
    color_mode: str = "truecolor",
    ascii_only: bool = False,
    *,
    reader: Optional[KeyReader] = None,
    out: Optional[TextIO] = None,
    get_size: Optional[Callable[[], Size]] = None,
    ticks: Optional[TickSource] = None,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    regenerate: Optional[Callable[[], World]] = None,
) -> None:
    """Run the explorer until the user quits.

    Args:
        world: The generated world.
        config: The merged configuration.
        color_mode: ``"truecolor"``, ``"256"`` or ``"none"``.
        ascii_only: Use only 7-bit glyphs.
        reader: The key source (default: the platform reader on stdin); tests pass a scripted one.
        out: The output stream (default: stdout).
        get_size: Returns ``(columns, rows)``; default is the terminal size.
        ticks: What advances while the explorer is open (a simulation); nothing ticks by default, so the loop blocks
            on keys. While it is active the loop polls it between keys.
        now: The clock the tick source is asked about (seconds); tests pass a fake one.
        sleep: How the loop waits between polls of an active tick source; tests pass a fake one.
        regenerate: Makes the world again for the restart key (default: generate it again from the world's own seed).
    """
    reader = reader if reader is not None else make_reader()
    writer = DiffWriter(out if out is not None else sys.stdout, color_mode)
    size_of = get_size if get_size is not None else _terminal_size
    overlay = Overlay()
    cache = RenderCache(config)
    state = ViewState(mode=config.get("render.default_view", MODE_FIT))
    state.cx, state.cy = initial_cursor(world, config)
    state.notify(f"colour mode: {color_mode}")
    tracking: object = None
    help_open = False
    queued: Optional[Action] = None  # an action read while draining moves, handled after the frame they lead to
    source: TickSource = ticks if ticks is not None else NoTicks()
    live = WorldReader(world, getattr(source, "state", None))  # the world as the simulation (if any) has changed it
    clock = Clock.from_config(config)
    poll_seconds = float(config.get("controls.tick_poll_seconds"))
    with reader:
        writer.enter()
        try:
            while True:
                tracking = sync_floor(world, config, state, tracking, live)
                frame = compose_frame(
                    world,
                    config,
                    state,
                    overlay,
                    size_of(),
                    color_mode != "none",
                    ascii_only,
                    help_open,
                    cache,
                    live,
                    sim_status(source, clock, config),
                )
                writer.draw(frame.screen)
                if queued is None:  # nothing to do yet: prepare the next frames until a key arrives
                    work = idle_work(
                        world,
                        config,
                        state,
                        cache,
                        frame.view_name,
                        frame.sampler,
                        overlay,
                        color_mode != "none",
                        ascii_only,
                        live,
                    )
                    for _ in work:
                        if reader.pending():
                            break
                token = next_token(reader, source, clock, poll_seconds, now, sleep) if queued is None else ""
                action = queued if queued is not None else resolve_action(token, config)
                queued = None
                if help_open and action[0] != "resize":
                    help_open = False  # any key closes the help and does nothing else
                    continue
                name = action[0]
                if name == "quit":
                    break
                if name in ("move", "pan"):
                    (move_cursor if name == "move" else pan_view)(world, config, state, action[1], action[2])
                    queued = _drain_moves(world, config, state, reader)
                elif name == "restart":
                    state.notify(f"restarting from seed {world.master_seed}...")
                    writer.draw(
                        compose_frame(
                            world,
                            config,
                            state,
                            overlay,
                            size_of(),
                            color_mode != "none",
                            ascii_only,
                            False,
                            cache,
                            live,
                        ).screen
                    )
                    world, overlay, cache, state = _restart(world, config, source, clock, regenerate)
                    live = WorldReader(world, getattr(source, "state", None))
                    tracking = None
                elif name in ("zoom", "local", "toggle_scale", "cycle_view"):
                    _view_action(world, config, state, name, live)
                elif name == "floor":
                    cycle_floor(world, config, state, action[1], live)
                elif name == "history":
                    history_loop(
                        world,
                        config,
                        initial_state(world, config, history_start(world, config, state), (state.cx, state.cy)),
                        reader,
                        writer,
                        size_of,
                        color_mode != "none",
                        ascii_only,
                    )
                    writer.invalidate()  # the viewer drew the whole screen
                elif name == "export":
                    _export(world, config, state, overlay, frame, action[1], live)
                elif name in ("pause", "speed"):
                    state.notify(_clock_message(source, clock, name, action))
                elif name == "help":
                    help_open = True
                elif name == "resize":
                    writer.invalidate()
        finally:
            writer.leave()


def _terminal_size() -> Size:
    size = shutil.get_terminal_size(fallback=(120, 36))
    return size.columns, size.lines

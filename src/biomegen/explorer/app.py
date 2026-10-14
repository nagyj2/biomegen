"""The interactive explorer: compose a frame from the layered renderer, diff-write it, read a key, repeat.

``run`` is event driven: it blocks on a key and redraws only after input, so an idle explorer uses no CPU. The
frame is a terminal-sized :class:`~biomegen.render.grid.CellGrid` (the map on top, the info panel below) that the
:class:`~biomegen.explorer.writer.DiffWriter` sends as minimal updates. Everything outside ``run`` is pure, so the
whole loop is tested with a scripted key source and an in-memory terminal.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import Callable, Optional, TextIO

from ..config.model import Config
from ..render.detail import DetailSampler, centre_camera, detail_cell_size
from ..render.fit import FitSampler
from ..render.grid import CellGrid
from ..render.layers import Seen, build_grid
from ..render.sampler import Sampler
from ..render.views import resolve_view, view_names
from ..world.overlay import Overlay
from ..world.world import World
from .exports import export_screen, export_world
from .input import KeyReader, make_reader, resolve_action
from .panel import build_panel, draw_help, panel_color
from .state import (
    MODE_FIT,
    MODE_ONE_TO_ONE,
    ViewState,
    clamp,
    cycle_floor,
    edge_pan,
    initial_cursor,
    move_cursor,
    step_in,
    step_out,
    sync_floor,
    toggle_mode,
)
from .writer import DiffWriter

Size = tuple[int, int]  # (columns, rows)


@dataclass
class Frame:
    """One composed frame.

    Attributes:
        screen: The whole terminal: map, cursor, panel and any help overlay.
        map_grid: The map as drawn, without the cursor (what ``e`` exports).
        view_name: The view that was drawn.
    """

    screen: CellGrid
    map_grid: CellGrid
    view_name: str


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


def _map_sampler(world: World, config: Config, state: ViewState, area: Size) -> Sampler:
    """Return the sampler for the current scale and mode, moving the camera as the cursor needs."""
    cols, rows = area
    if state.is_detail:
        cell_w, cell_h = detail_cell_size(state.scale, config, cols, rows)
        tiles_w, tiles_h = max(1, cols // cell_w), max(1, rows // cell_h)
        if state.recenter:
            state.cam_x = centre_camera(state.cx, tiles_w, world.width)
            state.cam_y = centre_camera(state.cy, tiles_h, world.height)
        else:
            state.cam_x = edge_pan(state.cam_x, state.cx, tiles_w, world.width)
            state.cam_y = edge_pan(state.cam_y, state.cy, tiles_h, world.height)
        state.recenter = False
        return DetailSampler(world, config, cell_w, cell_h, state.cam_x, state.cam_y, tiles_w, tiles_h, state.scale)
    if state.mode == MODE_ONE_TO_ONE:
        if state.recenter:
            state.cam_x = centre_camera(state.cx, cols, world.width)
            state.cam_y = centre_camera(state.cy, rows, world.height)
        else:
            state.cam_x = edge_pan(state.cam_x, state.cx, cols, world.width)
            state.cam_y = edge_pan(state.cam_y, state.cy, rows, world.height)
        state.recenter = False
        return Sampler.viewport(world, rows, cols, x0=float(state.cam_x), y0=float(state.cam_y))
    state.recenter = False
    return FitSampler(world, config, cols, rows)


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


def compose_frame(
    world: World,
    config: Config,
    state: ViewState,
    overlay: Overlay,
    size: Size,
    color: bool = True,
    ascii_only: bool = False,
    help_open: bool = False,
) -> Frame:
    """Compose one terminal-sized frame for ``state``: the map with its cursor, the panel, and the help overlay."""
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
    sampler = _map_sampler(world, config, state, (cols, map_rows))
    seen = Seen()
    map_grid = build_grid(
        world,
        config,
        resolve_view(config, view_name),
        sampler,
        overlay,
        ascii_only,
        color,
        floor=state.floor,
        seen=seen,
    )
    shown = CellGrid(map_grid.rows, map_grid.cols)
    for name in ("glyph", "fg", "bg", "bold"):
        getattr(shown, name)[...] = getattr(map_grid, name)
    _highlight_cursor(shown, sampler, state)
    _paste(screen, shown, 0)
    _paste(screen, build_panel(world, config, state, view_name, seen, cols, panel_height, ascii_only), map_rows)
    if help_open:
        draw_help(screen, config)
    return Frame(screen, map_grid, view_name)


def _export(world: World, config: Config, state: ViewState, overlay: Overlay, frame: Frame, target: str) -> None:
    """Write the screen's map (``view``) or the whole world (``world``); failures go to the panel, not a crash."""
    try:
        if target == "world":
            paths = export_world(world, config, frame.view_name, overlay)
        else:
            paths = export_screen(world, config, frame.map_grid, state.scale, frame.view_name)
    except Exception as error:  # never let an export error kill the explorer
        state.notify(f"export failed: {error}")
        return
    names = ", ".join(path.rsplit("/", 1)[-1] for path in paths)
    suffix = "" if any(path.endswith(".png") for path in paths) else " (install Pillow for PNG)"
    state.notify(f"exported {names}{suffix}")


def run(
    world: World,
    config: Config,
    color_mode: str = "truecolor",
    ascii_only: bool = False,
    *,
    reader: Optional[KeyReader] = None,
    out: Optional[TextIO] = None,
    get_size: Optional[Callable[[], Size]] = None,
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
    """
    reader = reader if reader is not None else make_reader()
    writer = DiffWriter(out if out is not None else sys.stdout, color_mode)
    size_of = get_size if get_size is not None else _terminal_size
    overlay = Overlay()
    state = ViewState(mode=config.get("render.default_view", MODE_FIT))
    state.cx, state.cy = initial_cursor(world, config)
    state.notify(f"colour mode: {color_mode}")
    tracking: object = None
    help_open = False
    with reader:
        writer.enter()
        try:
            while True:
                tracking = sync_floor(world, state, tracking)
                frame = compose_frame(
                    world, config, state, overlay, size_of(), color_mode != "none", ascii_only, help_open
                )
                writer.draw(frame.screen)
                action = resolve_action(reader.read_key(), config)
                if help_open and action[0] != "resize":
                    help_open = False  # any key closes the help and does nothing else
                    continue
                name = action[0]
                if name == "quit":
                    break
                if name == "move":
                    move_cursor(world, state, action[1], action[2])
                elif name == "zoom":
                    step_out(state)
                    state.notify(f"scale: {state.scale}")
                elif name == "local":
                    step_in(state)
                    state.notify(f"scale: {state.scale}")
                elif name == "toggle_scale":
                    toggle_mode(state)
                elif name == "cycle_view":
                    state.view_index = (state.view_index + 1) % len(view_names(config))
                    state.notify(f"view: {view_names(config)[state.view_index]}")
                elif name == "floor":
                    cycle_floor(world, state, action[1])
                elif name == "export":
                    _export(world, config, state, overlay, frame, action[1])
                elif name == "help":
                    help_open = True
                elif name == "resize":
                    writer.invalidate()
        finally:
            writer.leave()


def _terminal_size() -> Size:
    size = shutil.get_terminal_size(fallback=(120, 36))
    return size.columns, size.lines

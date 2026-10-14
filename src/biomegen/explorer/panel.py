"""The explorer's info panel and help overlay, drawn as cell grids (pure: no terminal I/O).

The panel sits under the map: the island line, the tile under the cursor, its region and point of interest, a
legend of what is on screen, and the controls with the latest message. The help overlay lists every key.
"""

from __future__ import annotations

from typing import Optional

from ..config.model import Config
from ..render.colors import biome_style, interior_style
from ..render.detail import SCALE_MAP
from ..render.grid import RGB, CellGrid
from ..render.layers import Seen
from ..world.tile import BIOME_NAME, Cell
from ..world.world import World
from .state import MODE_ONE_TO_ONE, ViewState

_LEGEND_INDENT = 9


def _color(config: Config, key: str) -> RGB:
    red, green, blue = config.get(f"render.panel.{key}")
    return int(red), int(green), int(blue)


def _rgb(color: object) -> RGB:
    red, green, blue = color  # type: ignore[misc]
    return int(red), int(green), int(blue)


class _Canvas:
    """A cell grid with clipped text drawing."""

    def __init__(self, rows: int, cols: int, fg: RGB, bg: RGB) -> None:
        self.grid = CellGrid(rows, cols, bg=bg, fg=fg)
        self.fg = fg

    def text(self, row: int, col: int, text: str, fg: Optional[RGB] = None, bold: bool = False) -> None:
        if not 0 <= row < self.grid.rows or col >= self.grid.cols:
            return
        text = text[: max(0, self.grid.cols - col)]
        if not text:
            return
        span = slice(col, col + len(text))
        self.grid.glyph[row, span] = list(text)
        self.grid.fg[row, span] = fg if fg is not None else self.fg
        self.grid.bold[row, span] = bold


def view_label(state: ViewState) -> str:
    """The scale shown in the panel: ``ZOOM``, ``LOCAL``, or ``FIT`` / ``1:1`` for the map."""
    if state.scale != SCALE_MAP:
        return state.scale.upper()
    return "1:1" if state.mode == MODE_ONE_TO_ONE else "FIT"


def controls_line(config: Config) -> str:
    """The one-line key summary, built from the ``keys`` table so rebinding shows up."""
    keys = config.get("keys")

    def show(name: str) -> str:
        key = keys[name]
        return "space" if key == " " else key

    return (
        f"[arrows] move  [{show('zoom')}] zoom  [{show('local')}] local  [{show('toggle_scale')}] fit/1:1  "
        f"[{show('cycle_view')}] view  [{show('help')}] help  [{show('export_view')}/{show('export_world')}] export  "
        f"[{show('quit')}] quit"
    )


def _legend(canvas: _Canvas, config: Config, seen: Seen, top: int, bottom: int, ascii_only: bool) -> int:
    """Draw the biome and item legends in rows ``[top, bottom)``; return the next free row."""
    style = biome_style(config, ascii_only)
    labels = config.get("tables.biomes")
    row = top
    canvas.text(row, 0, " legend:", canvas.fg)
    column = _LEGEND_INDENT
    for biome in sorted(seen.biomes):
        label = labels[BIOME_NAME[biome]]["label"]
        entry = f"{style.glyph[biome]} {label}  "
        if column + len(entry) >= canvas.grid.cols:
            row, column = row + 1, _LEGEND_INDENT
            if row >= bottom:
                return row
        canvas.text(row, column, str(style.glyph[biome]), _rgb(style.fg[biome]))
        canvas.grid.bg[row, column] = style.bg[biome]
        canvas.text(row, column + 1, f" {label}  ")
        column += len(entry)
    items = [cell for cell in sorted(seen.cells) if cell != int(Cell.VOID)]
    if items and row + 1 < bottom:
        interior = interior_style(config)
        row, column = row + 1, _LEGEND_INDENT
        canvas.text(row, 0, " items: ", canvas.fg)
        for cell in items:
            name = Cell(cell).name.lower()
            entry = f"{interior.glyph[cell]} {name}  "
            if column + len(entry) >= canvas.grid.cols:
                row, column = row + 1, _LEGEND_INDENT
                if row >= bottom:
                    return row
            canvas.text(row, column, str(interior.glyph[cell]), _rgb(interior.fg[cell]))
            canvas.grid.bg[row, column] = interior.bg[cell]
            canvas.text(row, column + 1, f" {name}  ")
            column += len(entry)
    return row + 1


def build_panel(
    world: World,
    config: Config,
    state: ViewState,
    view_name: str,
    seen: Seen,
    width: int,
    height: int,
    ascii_only: bool = False,
) -> CellGrid:
    """Return the info panel as a ``height x width`` grid for the current cursor, view and what is on screen."""
    canvas = _Canvas(height, width, _color(config, "fg"), _color(config, "bg"))
    dim, head = _color(config, "dim"), _color(config, "head")
    canvas.text(0, 0, "-" * width, dim)
    island = world.island_name or "(unnamed isle)"
    canvas.text(
        1,
        0,
        f" {island}   seed {world.seed}   view {view_label(state)} / {view_name}   floor {state.floor}",
        head,
        bold=True,
    )
    tile = world.view(state.cx, state.cy)
    relief = f"  relief {tile.relief.name.lower()}" if tile.relief.value else ""
    canvas.text(
        2,
        0,
        f" cursor ({state.cx},{state.cy})  biome {tile.biome_name}{relief}  water {tile.water_type.name.lower()}"
        f"  elev {tile.elevation_m:.0f} m  temp {tile.temperature_c:.1f} C  moist {tile.moisture:.2f}",
    )
    region = world.region_at(state.cx, state.cy)
    if region is not None:
        name = region.name or f"region #{region.id}"
        canvas.text(3, 0, f" {name}  (mostly {BIOME_NAME[region.biome_class]}, {region.size} tiles)")
        if region.lore:
            canvas.text(4, 1, region.lore[0], dim)
    else:
        canvas.text(3, 0, " region: open ocean")
    poi = world.poi_at(state.cx, state.cy)
    canvas.text(5, 0, f" POI: {poi.name or poi.kind} ({poi.kind})" if poi is not None else " POI: -")
    last = height - 1
    if config.get("render.show_legend", True) and 6 < last:
        _legend(canvas, config, seen, 6, last, ascii_only)
    canvas.text(last, 0, controls_line(config), dim)
    message = state.last_message
    if message:
        canvas.text(last, max(0, width - len(message) - 1), message, head, bold=True)
    return canvas.grid


_HELP_LINES = (
    "Keys",
    "",
    "arrows / WASD / HJKL   move the cursor (shift or capitals: {step} tiles)",
    "{zoom}   step out: map <-> zoom, local -> zoom",
    "{local}   step in: map -> zoom -> local",
    "{toggle_scale}   fit-to-screen <-> 1:1 (map only)",
    "{cycle_view}   next view (terrain, elevation, temperature, rainfall)",
    "{floor_up} / {floor_down}   floor up / down on a structure",
    "{export_view} / {export_world}   export the view / the whole world",
    "{help}   this help      {quit} or Esc   quit",
)


def draw_help(screen: CellGrid, config: Config) -> None:
    """Draw the key help as a centred box over ``screen`` (in place), clipped to its size."""
    keys = config.get("keys")
    shown = {name: ("space" if key == " " else key) for name, key in keys.items()}
    shown["step"] = str(config.get("controls.fast_step", 8))
    lines = [line.format(**shown) for line in _HELP_LINES]
    box_w = min(screen.cols, max(len(line) for line in lines) + 4)
    box_h = min(screen.rows, len(lines) + 2)
    top, left = (screen.rows - box_h) // 2, (screen.cols - box_w) // 2
    fg, bg = _color(config, "help_fg"), _color(config, "help_bg")
    screen.fg[top : top + box_h, left : left + box_w] = fg
    screen.bg[top : top + box_h, left : left + box_w] = bg
    screen.glyph[top : top + box_h, left : left + box_w] = " "
    screen.bold[top : top + box_h, left : left + box_w] = False
    for offset, line in enumerate(lines[: box_h - 2]):
        text = line[: box_w - 4]
        span = slice(left + 2, left + 2 + len(text))
        screen.glyph[top + 1 + offset, span] = list(text)
    screen.bold[top + 1, left + 2 : left + 2 + len("Keys")] = True
    screen.fg[top + 1, left + 2 : left + 6] = _color(config, "head")

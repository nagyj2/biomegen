"""The explorer's info panel and help overlay, drawn as cell grids (pure: no terminal I/O).

The panel sits under the map: the island line, the tile under the cursor, its realm and point of interest, a
legend of what is on screen, and the controls with the latest message. The help overlay lists every key.
"""

from __future__ import annotations

from typing import Any, Optional

from ..config.model import Config
from ..render.chronicle import colored_text, event_row, name_color
from ..render.colors import biome_style, interior_style
from ..render.grid import RGB, CellGrid, Span
from ..render.layers import Seen
from ..sampling.detail import SCALE_MAP, SCALE_SITE
from ..sites import site_plan
from ..sites.kinds import building_at, building_counts, cell_name
from ..world.entities import POI, REF_POI, Realm
from ..world.tile import BIOME_NAME, Cell
from ..world.world import World
from .events import ChronicleReader, EventReader
from .state import MODE_ONE_TO_ONE, ViewState, floor_label, poi_under_cursor

_LEGEND_INDENT = 9


def panel_color(config: Config, key: str) -> RGB:
    red, green, blue = config.get(f"render.panel.{key}")
    return int(red), int(green), int(blue)


def _rgb(color: Any) -> RGB:
    return int(color[0]), int(color[1]), int(color[2])


class _Canvas:
    """A cell grid with clipped text drawing."""

    def __init__(self, rows: int, cols: int, fg: RGB, bg: RGB) -> None:
        self.grid = CellGrid(rows, cols, bg=bg, fg=fg)
        self.fg = fg

    def spans(self, row: int, col: int, spans: list[Span], fg: Optional[RGB] = None) -> None:
        """Draw styled spans one after the other; a span with no colour takes ``fg`` (default: the panel's text)."""
        for span in spans:
            self.text(row, col, span.text, span.fg if span.fg is not None else fg, span.bold)
            col += len(span.text)

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
    """The scale shown in the panel: ``ZOOM``, ``LOCAL``, ``SITE``, or ``FIT`` / ``1:1`` for the map."""
    if state.scale != SCALE_MAP:
        return state.scale.upper()
    return "1:1" if state.mode == MODE_ONE_TO_ONE else "FIT"


def _buildings_line(world: World, config: Config, state: ViewState, poi: Optional[POI]) -> str:
    """In an open site, the buildings that stand there (``Hall, Farmhouse, House x9``) and the one under the cursor.

    Empty outside a site view or for a site with no buildings. A building shows by its kind's label.
    """
    if state.scale != SCALE_SITE or poi is None:
        return ""
    plan = site_plan(poi, 0, config, world)
    if plan is None or not plan.buildings:
        return ""

    def label(kind: str) -> str:
        return str(config.get(f"tables.buildings.{kind}.label"))

    parts = [
        label(kind) if count == 1 else f"{label(kind)} x{count}" for kind, count in building_counts(plan.buildings)
    ]
    line = f" buildings: {', '.join(parts)}"
    here = building_at(plan, state.px, state.py)
    return f"{line}   under cursor: {label(here)}" if here is not None else line


def _poi_spans(world: World, config: Config, poi: Optional[POI]) -> list[Span]:
    """The panel's POI line: name (in its realm's colour), kind, the style of a homestead or generated hamlet, and for
    settlements the population and tags."""
    if poi is None:
        return [Span(" POI: -")]
    detail = [poi.kind]
    if poi.style:
        detail.append(poi.style)
    if poi.pop:
        detail.append(f"pop {poi.pop:,}")
    detail.extend(poi.tags)
    index = next((i for i, other in enumerate(world.pois) if other is poi), -1)
    name = poi.name or poi.kind
    color = name_color(world, config, REF_POI, index) if index >= 0 else None
    return [Span(" POI: "), Span(name, color, bold=color is not None), Span(f" ({', '.join(detail)})")]


def _hook_spans(world: World, config: Config, poi: Optional[POI]) -> list[Span]:
    """The story text of the point of interest under the cursor, its names coloured, or no spans at all."""
    if poi is None or not poi.hook:
        return []
    return [Span(" "), *colored_text(world, config, poi.hook, poi.hook_refs)]


def _event_spans(
    world: World, events: EventReader, config: Config, state: ViewState, realm: Optional[Realm]
) -> list[tuple[list[Span], bool]]:
    """List up to ``render.panel_events`` events as ``(spans, at the cursor)``: the latest at the cursor's tile (they
    stay while the cursor does), then the latest of the realm that holds it (plain text dimmed) to fill the rest. Every
    name is in its realm's colour."""
    limit = int(config.get("render.panel_events"))
    here = events.at(state.cx, state.cy)[-limit:] if limit else []
    lines = [(event_row(world, config, event), True) for event in here]
    if realm is not None and len(lines) < limit:
        shown = {event.id for event in here}
        rest = [e for e in events.of_realm(realm.id) if e.id not in shown][-(limit - len(lines)) :]
        lines += [(event_row(world, config, event), False) for event in rest]
    return lines


def controls_line(config: Config) -> str:
    """The one-line key summary, built from the ``keys`` table so rebinding shows up."""
    keys = config.get("keys")

    def show(name: str) -> str:
        key = keys[name]
        return "space" if key == " " else key

    return (
        f"[arrows] move  [WSAD] pan  [{show('zoom')}] zoom  [{show('local')}] local  [{show('toggle_scale')}] fit/1:1  "
        f"[{show('cycle_view')}] view  [{show('history')}] history  [{show('help')}] help  "
        f"[{show('export_view')}/{show('export_world')}] export  "
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
        interior = interior_style(config, ascii_only)
        row, column = row + 1, _LEGEND_INDENT
        canvas.text(row, 0, " items: ", canvas.fg)
        for cell in items:
            name = cell_name(config, cell)
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
    events: Optional[EventReader] = None,
) -> CellGrid:
    """Return the info panel as a ``height x width`` grid for the current cursor, view and what is on screen.

    ``events`` is where the panel reads history from (default: the world's chronicle).
    """
    canvas = _Canvas(height, width, panel_color(config, "fg"), panel_color(config, "bg"))
    dim, head = panel_color(config, "dim"), panel_color(config, "head")
    poi = poi_under_cursor(world, config, state)
    canvas.text(0, 0, "-" * width, dim)
    island = world.island_name or "(unnamed isle)"
    floor_text = str(state.floor) if poi is None or state.floor == 0 else floor_label(poi, config, state.floor)
    canvas.text(
        1,
        0,
        f" {island}   seed {world.seed}   view {view_label(state)} / {view_name}   floor {floor_text}",
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
    realm = world.realm_at(state.cx, state.cy)
    if realm is not None:
        kind = config.get(f"tables.realm_kinds.{realm.kind}.label")
        ruler = realm.ruler or "no one"
        canvas.spans(
            3,
            0,
            [
                Span(" "),
                Span(realm.name or f"realm #{realm.id}", realm.color, bold=True),
                Span(f"  ({kind}, ruled by "),
                Span(ruler, realm.color if realm.ruler else None, bold=bool(realm.ruler)),
                Span(")"),
            ],
        )
        canvas.text(4, 1, f"{realm.area_km2:,.0f} km2, pop. ~{realm.pop:,}", dim)
    else:
        canvas.text(3, 0, " realm: open water" if tile.is_water else " realm: none (wild land)")
    canvas.spans(5, 0, _poi_spans(world, config, poi))
    # The hook's row is always reserved (blank when there is none), so nothing under it jumps as the cursor moves.
    canvas.spans(6, 0, _hook_spans(world, config, poi), canvas.fg)
    info: list[tuple[list[Span], RGB]] = [
        ([Span(line)], canvas.fg) for line in [_buildings_line(world, config, state, poi)] if line
    ]
    info += [
        (spans, canvas.fg if at_cursor else dim)
        for spans, at_cursor in _event_spans(world, events or ChronicleReader(world), config, state, realm)
    ]
    for offset, (spans, default) in enumerate(info):
        canvas.spans(7 + offset, 0, spans, default)
    first = 7 + len(info)
    last = height - 1
    if config.get("render.show_legend", True) and first < last:
        _legend(canvas, config, seen, first, last, ascii_only)
    message = state.last_message
    controls = controls_line(config)
    if message:
        controls = controls[: max(0, width - len(message) - 2)]  # leave the message its own cells
    canvas.text(last, 0, controls, dim)
    if message:
        canvas.text(last, max(0, width - len(message) - 1), message, head, bold=True)
    return canvas.grid


_HELP_LINES = (
    "Keys",
    "",
    "arrows / HJKL   move the cursor (shift or capitals: {step} tiles)",
    "WASD   scroll the viewport (capitals: {step} tiles); on the fit map they move the cursor",
    "{zoom}   step out: map <-> zoom, local or a site -> zoom",
    "{local}   step in: map -> zoom -> local, or into the site of a POI (arrows then move one cell)",
    "{toggle_scale}   fit-to-screen <-> 1:1 (map only)",
    "{cycle_view}   next view (terrain, political, elevation, temperature, rainfall)",
    "{history}   history viewer, opened at the latest event at the cursor",
    "{refresh}   restart from the seed (the same world, view and edits reset)",
    "{floor_up} / {floor_down}   floor up / down on a structure",
    "{export_view} / {export_world}   export the view / the whole world",
    "{help}   this help      {quit} or Esc   quit",
)


def draw_help(screen: CellGrid, config: Config, help_lines: tuple[str, ...] = _HELP_LINES) -> None:
    """Draw the key help (``help_lines``, ``{name}`` filled from the ``keys`` table) as a centred box over ``screen``.

    The box is drawn in place and clipped to the screen's size.
    """
    keys = config.get("keys")
    shown = {name: ("space" if key == " " else key) for name, key in keys.items()}
    shown["step"] = str(config.get("controls.fast_step", 8))
    lines = [line.format(**shown) for line in help_lines]
    box_w = min(screen.cols, max(len(line) for line in lines) + 4)
    box_h = min(screen.rows, len(lines) + 2)
    top, left = (screen.rows - box_h) // 2, (screen.cols - box_w) // 2
    fg, bg = panel_color(config, "help_fg"), panel_color(config, "help_bg")
    screen.fg[top : top + box_h, left : left + box_w] = fg
    screen.bg[top : top + box_h, left : left + box_w] = bg
    screen.glyph[top : top + box_h, left : left + box_w] = " "
    screen.bold[top : top + box_h, left : left + box_w] = False
    for offset, line in enumerate(lines[: box_h - 2]):
        text = line[: box_w - 4]
        span = slice(left + 2, left + 2 + len(text))
        screen.glyph[top + 1 + offset, span] = list(text)
    title = slice(left + 2, left + 2 + min(len(lines[0]), box_w - 4))  # the whole first line is the title
    screen.bold[top + 1, title] = True
    screen.fg[top + 1, title] = panel_color(config, "head")

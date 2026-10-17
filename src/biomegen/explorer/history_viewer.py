"""The history viewer: the political map at a moment, with the powers then and the chronicle beside it.

It is the interactive form of ``--history``, built like the chronicle pager (the same key reader, writer, help box and
panel colours) but for travelling through time: ``[`` and ``]`` step between the moments the political map changes
(a founding, annexation, battle, peace, fall, secession or conquest), ``{`` and ``}`` between years, ``g`` asks for a
year and ``\\`` returns to the present. It never changes the world. Everything outside :func:`run_history` is pure, so
the loop is tested with a scripted key source and an in-memory terminal.

The left column is the map (the political view at the moment, fitted to the pane) over the powers that hold land then;
the right column is the chronicle, scrolled to the events of the moment, which are drawn on a highlight, the events
still to come dimmed.
"""

from __future__ import annotations

import shutil
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Callable, Optional, TextIO

import numpy as np

from ..config.model import Config
from ..render.chronicle import layout_events
from ..render.colors import mix_colors
from ..render.fit import FitSampler
from ..render.grid import RGB, CellGrid, Document
from ..render.layers import build_grid
from ..render.views import resolve_view
from ..world.chronicle import ChronicleFilter, filter_events
from ..world.entities import NO_LOCATION, ChronicleEvent
from ..world.territory import (
    WILD,
    TerritoryChange,
    fallen_id_of,
    is_fallen_owner,
    is_predecessor_owner,
    predecessor_id_of,
)
from ..world.world import World
from .input import Action, KeyReader, make_reader
from .panel import draw_help, panel_color
from .writer import DiffWriter

Size = tuple[int, int]  # (columns, rows)
Stop = tuple[int, int]  # (year, month)

_HEADER_ROWS = 1
_FOOTER_ROWS = 2
_POWER_ROWS = 6  # the powers list keeps at least this many rows under the map
_SCROLL_LETTERS = {"w": "up", "s": "down", "k": "up", "j": "down"}
_BOUND_ACTIONS = (
    ("history_prev", ("step", -1)),
    ("history_next", ("step", 1)),
    ("history_prev_year", ("year", -1)),
    ("history_next_year", ("year", 1)),
    ("history_goto", ("goto",)),
    ("history_present", ("present",)),
    ("filter_salience", ("minor",)),
    ("help", ("help",)),
)
_DEFAULT_KEYS = {
    "history_prev": "[",
    "history_next": "]",
    "history_prev_year": "{",
    "history_next_year": "}",
    "history_goto": "g",
    "history_present": "\\",
    "filter_salience": "m",
    "help": "?",
}
_HISTORY_HELP = (
    "History keys",
    "",
    "{history_prev} / {history_next}   previous / next event (the map changes where an event moves it)",
    "{history_prev_year} / {history_next_year}   an earlier / a later year",
    "{history_goto}   go to a year (the map at the end of it)",
    "{history_present}   the present (the map after the last event)",
    "{filter_salience}   show / hide the minor events (towers, roads, small settlements)",
    "Home / End   the first event / the present",
    "arrows / WASD / HJKL   scroll the chronicle (shift or capitals: {step})",
    "space / Page Down / Page Up   scroll a page",
    "{help}   this help      {quit} or Esc   quit",
)


@dataclass
class HistoryState:
    """Where the viewer is in time and what it has cached.

    Attributes:
        at: The moment shown: the map after every change at or before ``(year, month)``.
        moments: Every moment it can stop at (every event listed and the present), oldest first.
        minor: Whether minor events are listed (and stopped at) too.
        scroll: Index of the first chronicle line shown.
        prompt: The text typed in the open year prompt, or ``None``.
        message: A short note for the status line.
    """

    at: Stop
    moments: list[Stop] = field(default_factory=list)
    minor: bool = False
    scroll: int = 0
    prompt: Optional[str] = None
    message: str = ""
    _synced: Optional[tuple] = field(default=None, repr=False)  # (width, current stop): when the scroll last followed
    _map: Optional[tuple[tuple, CellGrid]] = field(default=None, repr=False)  # the last map drawn, with its key
    _events: Optional[tuple[tuple[int, bool], list[ChronicleEvent], Document, list[int]]] = field(
        default=None, repr=False
    )


def present_moment(world: World, config: Config) -> Stop:
    """The moment of the present map: the end of the world's last year."""
    return world.year, int(config.get("history.months_per_year"))


def change_moments(world: World, config: Config, minor: bool = False) -> list[Stop]:
    """Return each distinct ``(year, month)`` the viewer can stop at, oldest first: that of every event listed (the
    major ones, and the minor too when ``minor``), of every territory change, and the present at the end."""
    events = world.chronicle if minor else [e for e in world.chronicle if e.salience == "major"]
    moments = {(e.year, e.month) for e in events} | set(world.territory_moments())
    moments.add(present_moment(world, config))
    return sorted(moments)


def stop_index(moments: list[Stop], at: Stop) -> int:
    """Return the index of the last moment at or before ``at`` (-1 before the first)."""
    return bisect_right(moments, at) - 1


def _year_end(world: World, config: Config, year: int) -> Stop:
    return year, int(config.get("history.months_per_year"))


def initial_state(world: World, config: Config, start: Optional[int | Stop] = None) -> HistoryState:
    """Return the starting state: at ``start`` (a year, or a ``(year, month)``), else the first change."""
    moments = change_moments(world, config)
    if start is None:
        at = moments[0] if moments else _year_end(world, config, 0)
    elif isinstance(start, int):
        at = _year_end(world, config, start)
    else:
        at = start
    return HistoryState(at=at, moments=moments)


def resolve_history_action(token: str, config: Config, prompting: bool = False) -> Action:
    """Translate a key token into a viewer action.

    Actions: ``("step", ±1)``, ``("year", ±1)``, ``("goto",)``, ``("present",)``, ``("first",)``, ``("last",)``,
    ``("scroll", n)``, ``("page", ±1)``, ``("help",)``, ``("quit",)``, ``("resize",)``, ``("none",)``; while the year
    prompt is open also ``("type", char)``, ``("backspace",)``, ``("submit",)`` and ``("cancel",)``.
    """
    keys = config.get("keys")
    if token == "resize":
        return ("resize",)
    if token == "eof":
        return ("quit",)
    if prompting:
        if token == "esc":
            return ("cancel",)
        if token in ("\r", "\n"):
            return ("submit",)
        if token in ("\x7f", "\x08"):
            return ("backspace",)
        return ("type", token) if len(token) == 1 and token.isprintable() else ("none",)
    bound = {keys.get(name, _DEFAULT_KEYS[name]): action for name, action in _BOUND_ACTIONS}
    if token == "esc" or token == keys.get("quit", "q"):
        return ("quit",)
    if token in bound:
        return bound[token]
    step = int(config.get("controls.fast_step", 8))
    steps = {"up": -1, "down": 1}
    if token in steps:
        return ("scroll", steps[token])
    if token.startswith("shift-") and token[6:] in steps:
        return ("scroll", steps[token[6:]] * step)
    lower = token.lower()
    if len(token) == 1 and lower in _SCROLL_LETTERS:
        return ("scroll", steps[_SCROLL_LETTERS[lower]] * (step if token.isupper() else 1))
    if token == "pagedown" or token == " ":
        return ("page", 1)
    if token == "pageup":
        return ("page", -1)
    if token == "home":
        return ("first",)
    if token == "end":
        return ("last",)
    return ("none",)


def owner_label(world: World, owner: int) -> tuple[str, RGB]:
    """Return the name and colour of a territory owner (a realm, a fallen realm or a predecessor)."""
    if owner >= 0:
        realm = world.realms[owner]
        return realm.short or realm.name or f"realm {owner}", realm.color
    if is_fallen_owner(owner):
        fallen = world.fallen_realms[fallen_id_of(owner)]
        return fallen.name or f"fallen realm {fallen.id}", fallen.color
    if is_predecessor_owner(owner):
        predecessor = world.predecessors[predecessor_id_of(owner)]
        return predecessor.name or f"old realm {predecessor.id}", predecessor.color
    return "wild land", (128, 128, 128)


def _words_for(world: World, change: TerritoryChange) -> str:
    """One short phrase for a change: ``expansion: Phya +46 cells`` or ``battle: Aldor takes 12 cells from Wend``."""
    gained, lost = owner_label(world, change.to_owner)[0], owner_label(world, change.from_owner)[0]
    cells = len(change.cells)
    if change.from_owner == WILD:
        return f"{change.kind}: {gained} +{cells} cells"
    if change.to_owner == WILD:
        return f"{change.kind}: {lost} -{cells} cells to the wild"
    return f"{change.kind}: {gained} takes {cells} cells from {lost}"


def moment_summary(world: World, config: Config, moment: Stop) -> str:
    """Describe what the map does at ``moment``: its territory changes and conquests, one phrase each."""
    parts = [_words_for(world, c) for c in world.territory if c.moment == moment]
    for event in world.chronicle:
        if (event.year, event.month) == moment and event.kind == "conquest" and "vassalage" in event.tags:
            parts.append(
                f"conquest: {world.realms[event.realm_ids[1]].short} takes {world.realms[event.realm_ids[0]].short}"
            )
    if moment == present_moment(world, config):
        parts.append("the present")
    return "; ".join(parts) if parts else "the map does not change here"


def _put(grid: CellGrid, row: int, col: int, text: str, fg: RGB, bg: RGB, bold: bool = False) -> None:
    """Write clipped ``text`` into one row of ``grid`` (nothing if the row is off the grid)."""
    if not 0 <= row < grid.rows:
        return
    text = text[: max(0, grid.cols - col)]
    if not text:
        return
    span = slice(col, col + len(text))
    grid.glyph[row, span] = list(text)
    grid.fg[row, span] = fg
    grid.bg[row, span] = bg
    grid.bold[row, span] = bold


def _geometry(config: Config, cols: int) -> tuple[int, int]:
    """Return ``(map columns, event column)``: the map pane's width and where the chronicle starts."""
    settings = config.get("history.viewer")
    map_cols = int(cols * float(settings["map_share"]))
    map_cols = max(int(settings["min_map_cols"]), min(map_cols, cols - int(settings["min_event_cols"]) - 1))
    return map_cols, map_cols + 1


def _map_grid(world: World, config: Config, state: HistoryState, area: Size, color: bool, ascii_only: bool) -> CellGrid:
    """Return the political map at ``state.at`` fitted into ``area`` with the recent events marked on it.

    Drawn again only when something changed.
    """
    key = (area, state.at, state.minor, color, ascii_only)
    if state._map is None or state._map[0] != key:
        sampler = FitSampler(world, config, area[0], area[1])
        view = resolve_view(config, "political")
        grid = build_grid(world, config, view, sampler, None, ascii_only, color, "all", 0, None, state.at)
        _draw_markers(grid, world, config, state, sampler)
        state._map = (key, grid)
    return state._map[1]


def _draw_markers(grid: CellGrid, world: World, config: Config, state: HistoryState, sampler: FitSampler) -> None:
    """Mark the events with a place on ``grid``: this moment's in full colour and bold, the earlier ones of the last
    ``marker_years`` years faded (glyphs from ``history.viewer.glyphs``, colours from ``history.colors``)."""
    settings = config.get("history.viewer")
    glyphs, palette = settings["glyphs"], config.get("history.colors")
    index = stop_index(state.moments, state.at)
    current = state.moments[index] if index >= 0 else None
    oldest = state.at[0] - int(settings["marker_years"])
    for event in world.chronicle:  # oldest first, so a newer marker is drawn over an older one
        moment = (event.year, event.month)
        if event.kind not in glyphs or event.location == NO_LOCATION or moment > state.at or event.year < oldest:
            continue
        if event.salience == "minor" and not state.minor:
            continue
        col, row = sampler.cell_coords(*event.location) or (-1, -1)
        if not (0 <= row < grid.rows and 0 <= col < grid.cols):
            continue
        red, green, blue = palette[event.kind]
        colour: RGB = (int(red), int(green), int(blue))
        now = moment == current
        grid.glyph[row, col] = glyphs[event.kind]
        grid.fg[row, col] = colour if now else mix_colors(colour, grid.bg[row, col], float(settings["marker_fade"]))
        grid.bold[row, col] = now


def _paste(screen: CellGrid, grid: CellGrid, top: int, left: int) -> None:
    rows, cols = min(grid.rows, screen.rows - top), min(grid.cols, screen.cols - left)
    target = (slice(top, top + rows), slice(left, left + cols))
    source = (slice(0, rows), slice(0, cols))
    screen.glyph[target], screen.fg[target] = grid.glyph[source], grid.fg[source]
    screen.bg[target], screen.bold[target] = grid.bg[source], grid.bold[source]


def _powers(world: World, state: HistoryState) -> list[tuple[int, int]]:
    """Return ``(owner, cells)`` for each owner holding land at ``state.at``, largest first (wild land last)."""
    owners, counts = np.unique(world.owners_at(*state.at), return_counts=True)
    held = [(int(o), int(n)) for o, n in zip(owners, counts, strict=True) if o != WILD]
    return sorted(held, key=lambda item: (-item[1], item[0]))


def _draw_powers(
    screen: CellGrid, world: World, config: Config, state: HistoryState, top: int, bottom: int, width: int
) -> None:
    """List the powers at the moment under the map: a swatch, the name (a vassal names its overlord) and the area."""
    fg, bg, dim = panel_color(config, "fg"), panel_color(config, "bg"), panel_color(config, "dim")
    km2 = world.scale.cell_area_km2
    entries = _powers(world, state)
    _put(screen, top, 1, f"powers: {len(entries)}", dim, bg)
    room = max(0, bottom - top - 1)
    shown = entries[: room if len(entries) <= room else max(0, room - 1)]
    for offset, (owner, cells) in enumerate(shown):
        name, color = owner_label(world, owner)
        if owner >= 0:
            lord = world.top_realm_at(owner, *state.at)
            if lord != owner:
                name += f" (vassal of {world.realms[lord].short})"
        row = top + 1 + offset
        _put(screen, row, 1, "  ", fg, color)
        area = f"{cells * km2:,.0f} km2"
        _put(screen, row, 4, name[: max(0, width - len(area) - 6)], fg, bg)
        _put(screen, row, max(4, width - len(area) - 1), area, dim, bg)
    if len(entries) > len(shown) and room:
        _put(screen, top + room, 1, f"... and {len(entries) - len(shown)} more", dim, bg)


def _events_layout(world: World, config: Config, state: HistoryState, width: int):
    """Return ``(events, lines, starts)`` of the listed events (the major ones, and the minor too when shown) wrapped to
    ``width`` (cached per width and listing)."""
    if state._events is None or state._events[0] != (width, state.minor):
        events = filter_events(world, ChronicleFilter(salience="all" if state.minor else "major"))
        lines, starts, _ = layout_events(world, config, events, width)
        state._events = ((width, state.minor), events, lines, starts)
    return state._events[1:]


def _help_lines(config: Config) -> tuple[str, ...]:
    """The help text: the keys, then what the marks on the map and the powers list mean (from the config's glyphs)."""
    glyphs = config.get("history.viewer.glyphs")
    marks = "   ".join(f"{glyph} {kind}" for kind, glyph in glyphs.items())
    years = int(config.get("history.viewer.marker_years"))
    return (
        *_HISTORY_HELP[:-1],
        "",
        "Marks on the map: events that had a place",
        f"  {marks}",
        f"  bold: this moment's events; faded: those of the last {years} years",
        "Powers list: the colour swatch is the power's colour on the map;",
        "  (vassal of X) means it had bowed to X by then",
        _HISTORY_HELP[-1],
    )


def _title(world: World, config: Config, state: HistoryState) -> str:
    year, month = state.at
    index = stop_index(state.moments, state.at)
    place = "before the first event" if index < 0 else f"stop {index + 1}/{len(state.moments)}"
    if state.at >= present_moment(world, config):
        place += ", the present"
    return f"History of {world.island_name or 'the island'}  seed {world.seed}  -  year {year}, month {month} ({place})"


def compose_history_frame(
    world: World,
    config: Config,
    state: HistoryState,
    size: Size,
    help_open: bool = False,
    color: bool = True,
    ascii_only: bool = False,
) -> CellGrid:
    """Compose one terminal-sized frame: title, the map and powers, the chronicle, the status line and the key hints.

    Scrolls the chronicle to the current moment when it has just changed, and clamps ``state.scroll``.
    """
    cols, rows = size
    fg, bg = panel_color(config, "fg"), panel_color(config, "bg")
    dim, head = panel_color(config, "dim"), panel_color(config, "head")
    screen = CellGrid(max(1, rows), max(1, cols), bg=bg, fg=fg)
    settings = config.get("history.viewer")
    if cols < int(settings["min_map_cols"]) + int(settings["min_event_cols"]) + 1 or rows < _POWER_ROWS + 6:
        _put(screen, 0, 0, "terminal too small - enlarge the window", fg, bg)
        return screen
    map_cols, event_col = _geometry(config, cols)
    body = rows - _HEADER_ROWS - _FOOTER_ROWS
    _put(screen, 0, 0, _title(world, config, state), head, bg, bold=True)
    grid = _map_grid(world, config, state, (map_cols, max(1, body - _POWER_ROWS)), color, ascii_only)
    _paste(screen, grid, _HEADER_ROWS, 0)
    _draw_powers(screen, world, config, state, _HEADER_ROWS + grid.rows + 1, rows - _FOOTER_ROWS, map_cols)
    screen.glyph[_HEADER_ROWS : rows - _FOOTER_ROWS, map_cols] = "|"
    screen.fg[_HEADER_ROWS : rows - _FOOTER_ROWS, map_cols] = dim
    _draw_events(screen, world, config, state, event_col, body)
    index = stop_index(state.moments, state.at)
    status = moment_summary(world, config, state.moments[index]) if index >= 0 else "no change yet"
    status_row = rows - _FOOTER_ROWS
    if state.prompt is not None:
        _put(screen, status_row, 0, f" year: {state.prompt}_", head, bg, bold=True)
    else:
        _put(screen, status_row, 0, f" {status}", fg, bg)
        if state.message:
            _put(screen, status_row, max(0, cols - len(state.message) - 1), state.message, head, bg, bold=True)
    _put(screen, rows - 1, 0, _hint_line(config, state.prompt is not None), dim, bg)
    if help_open:
        draw_help(screen, config, _help_lines(config))
    return screen


def _draw_events(screen: CellGrid, world: World, config: Config, state: HistoryState, left: int, body: int) -> None:
    """Draw the chronicle in the right column: events at the current moment highlighted, later ones dimmed."""
    fg, bg, dim = panel_color(config, "fg"), panel_color(config, "bg"), panel_color(config, "dim")
    width = screen.cols - left - 1
    events, lines, starts = _events_layout(world, config, state, width)
    index = stop_index(state.moments, state.at)
    current = state.moments[index] if index >= 0 else None
    moments = [(e.year, e.month) for e in events]
    key = (width, current, state.minor)
    if state._synced != key and events:
        first = bisect_left(moments, current) if current is not None else 0
        first = min(first, len(events) - 1)
        state.scroll = max(0, starts[first] - body // 3)
        state._synced = key
    state.scroll = max(0, min(state.scroll, len(lines) - body))
    owner_of_line = np.zeros(len(lines), dtype=np.int64)
    for position in range(len(events)):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        owner_of_line[starts[position] : end] = position
    red, green, blue = config.get("history.viewer.current_bg")
    highlight: RGB = (int(red), int(green), int(blue))
    for offset, line in enumerate(lines[state.scroll : state.scroll + body]):
        number = state.scroll + offset
        moment = moments[int(owner_of_line[number])]
        row = _HEADER_ROWS + offset
        is_current = current is not None and moment == current
        future = moment > state.at
        line_bg = highlight if is_current else bg
        if is_current:
            screen.bg[row, left : left + width] = line_bg
        col = left
        for span in line:
            _put(
                screen,
                row,
                col,
                span.text[: max(0, left + width - col)],
                dim if future else (span.fg or fg),
                line_bg,
                span.bold,
            )
            col += len(span.text)
    if not lines:
        _put(screen, _HEADER_ROWS, left, "(no events)", dim, bg)


def _hint_line(config: Config, prompting: bool) -> str:
    keys = config.get("keys")

    def show(name: str) -> str:
        key = keys.get(name, _DEFAULT_KEYS.get(name, "q"))
        return "space" if key == " " else key

    if prompting:
        return " [Enter] go  [Esc] cancel"
    return (
        f" [{show('history_prev')}/{show('history_next')}] event  "
        f"[{show('history_prev_year')}/{show('history_next_year')}] year  "
        f"[{show('history_goto')}] go to year  [{show('history_present')}] present  [{show('filter_salience')}] minor  "
        f"[arrows] scroll  [{show('help')}] help  [{show('quit')}] quit"
    )


def apply_history_action(world: World, config: Config, state: HistoryState, action: Action, size: Size) -> None:
    """Apply ``action`` to ``state``; ``help``, ``resize`` and ``quit`` are the loop's, not handled here."""
    name = action[0]
    state.message = ""
    if state.prompt is not None:
        if name == "type":
            state.prompt += action[1]
        elif name == "backspace":
            state.prompt = state.prompt[:-1]
        elif name == "cancel":
            state.prompt = None
        elif name == "submit":
            text, state.prompt = state.prompt.strip(), None
            try:
                state.at = _year_end(world, config, int(text))
            except ValueError:
                state.message = "year: type a whole number"
        return
    moments, here = state.moments, state.at
    body = max(1, size[1] - _HEADER_ROWS - _FOOTER_ROWS)
    if name == "step":
        target = bisect_right(moments, here) if action[1] > 0 else bisect_left(moments, here) - 1
        if 0 <= target < len(moments):
            state.at = moments[target]
        else:
            state.message = "no later change" if action[1] > 0 else "no earlier change"
    elif name == "year":
        years = [m[0] for m in moments]
        target = bisect_right(years, here[0]) if action[1] > 0 else bisect_left(years, here[0]) - 1
        if 0 <= target < len(moments):
            state.at = moments[target]
        else:
            state.message = "no later year" if action[1] > 0 else "no earlier year"
    elif name == "goto":
        state.prompt = ""
    elif name == "minor":
        state.minor = not state.minor
        state.moments = change_moments(world, config, state.minor)
        state.message = "showing minor events too" if state.minor else "showing major events only"
    elif name == "present":
        state.at = moments[-1] if moments else here
    elif name == "first":
        state.at = moments[0] if moments else here
    elif name == "last":
        state.at = moments[-1] if moments else here
    elif name == "scroll":
        state.scroll = max(0, state.scroll + action[1])
    elif name == "page":
        state.scroll = max(0, state.scroll + action[1] * max(1, body - 1))


def history_loop(
    world: World,
    config: Config,
    state: HistoryState,
    reader: KeyReader,
    writer: DiffWriter,
    size_of: Callable[[], Size],
    color: bool,
    ascii_only: bool,
) -> None:
    """Draw and handle keys until the user quits the viewer, on a reader and writer already in the terminal's modes.

    The explorer calls this with its own reader and writer (and invalidates the writer afterwards); :func:`run_history`
    wraps it for the command line.
    """
    help_open = False
    while True:
        size = size_of()
        writer.draw(compose_history_frame(world, config, state, size, help_open, color, ascii_only))
        action = resolve_history_action(reader.read_key(), config, state.prompt is not None)
        if action[0] == "resize":
            writer.invalidate()
            continue
        if help_open:
            help_open = False  # any key closes the help and does nothing else
            continue
        if action[0] == "quit":
            return
        if action[0] == "help":
            help_open = True
            continue
        apply_history_action(world, config, state, action, size)


def run_history(
    world: World,
    config: Config,
    color_mode: str = "truecolor",
    start: Optional[int | Stop] = None,
    ascii_only: bool = False,
    *,
    reader: Optional[KeyReader] = None,
    out: Optional[TextIO] = None,
    get_size: Optional[Callable[[], Size]] = None,
) -> None:
    """Run the history viewer until the user quits.

    Args:
        world: The generated world.
        config: The merged configuration.
        color_mode: ``"truecolor"``, ``"256"`` or ``"none"``.
        start: A year (the map at the end of it) or a ``(year, month)`` to open at; the first change when ``None``.
        ascii_only: Use only 7-bit glyphs.
        reader: The key source (default: the platform reader on stdin); tests pass a scripted one.
        out: The output stream (default: stdout).
        get_size: Returns ``(columns, rows)``; default is the terminal size.
    """
    reader = reader if reader is not None else make_reader()
    writer = DiffWriter(out if out is not None else sys.stdout, color_mode)
    size_of = get_size if get_size is not None else _terminal_size
    with reader:
        writer.enter()
        try:
            history_loop(
                world,
                config,
                initial_state(world, config, start),
                reader,
                writer,
                size_of,
                color_mode != "none",
                ascii_only,
            )
        finally:
            writer.leave()


def _terminal_size() -> Size:
    size = shutil.get_terminal_size(fallback=(120, 36))
    return size.columns, size.lines

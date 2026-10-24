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
from ..world.powers import power_profile
from ..world.territory import (
    LAST,
    WILD,
    TerritoryChange,
    at_end,
    fallen_id_of,
    fallen_owner,
    is_fallen_owner,
    is_predecessor_owner,
    predecessor_id_of,
    predecessor_owner,
)
from ..world.world import World
from .input import Action, KeyReader, make_reader
from .panel import draw_help, panel_color
from .writer import DiffWriter

Size = tuple[int, int]  # (columns, rows)
Stop = tuple[int, int, int]  # (year, month, chronicle event id): a place in time down to one event

_HEADER_ROWS = 1
_FOOTER_ROWS = 2
_POWER_ROWS = 6  # the powers list keeps at least this many rows under the map
_SCROLL_LETTERS = {"w": "up", "s": "down", "k": "up", "j": "down"}
_BOUND_ACTIONS = (
    ("history_prev", ("step", -1)),
    ("history_next", ("step", 1)),
    ("history_prev_tile", ("tile", -1)),
    ("history_next_tile", ("tile", 1)),
    ("history_goto", ("goto",)),
    ("history_focus", ("focus",)),
    ("history_present", ("present",)),
    ("filter_salience", ("minor",)),
    ("help", ("help",)),
)
_DEFAULT_KEYS = {
    "history_prev": "[",
    "history_next": "]",
    "history_prev_tile": "{",
    "history_next_tile": "}",
    "history_goto": "g",
    "history_focus": "\t",
    "history_present": "\\",
    "filter_salience": "m",
    "help": "?",
}
_HISTORY_HELP = (
    "History keys",
    "",
    "{history_prev} / {history_next}   previous / next event (the map changes where an event moves it)",
    "{history_goto}   go to a year (the map at the end of it)",
    "{history_present}   the present (the map after the last event); Home: the start, before any event",
    "{history_focus}   switch to the powers list and back (examine a power at this moment)",
    "{filter_salience}   show / hide the minor events (towers, roads, small settlements)",
    "Home / End   the start (before any event) / the present",
    "arrows / WASD / HJKL   scroll the chronicle (shift or capitals: {step})",
    "space   light what this moment's events are about on the map (a place, or the realms of a war or deal)",
    "Page Down / Page Up   scroll a page",
    "{help}   this help      {quit} or Esc   quit",
)


@dataclass
class HistoryState:
    """Where the viewer is in time and what it has cached.

    Attributes:
        at: The moment shown: the map after every change at or before ``(year, month)``.
        moments: Every moment it can stop at (every event listed and the present), oldest first.
        minor: Whether minor events are listed (and stopped at) too.
        tile: The tile the viewer was opened on from the explorer (None from the command line): the tile keys step
            through the events and changes at it.
        focus: ``"time"`` (the stop keys and the chronicle) or ``"powers"`` (the powers list and a power's profile).
        selected: The power being examined (a territory owner), kept as the stops change.
        highlight: Whether the selected power is being shown on the map (until the next key).
        scroll: Index of the first chronicle line shown.
        prompt: The text typed in the open year prompt, or ``None``.
        message: A short note for the status line.
    """

    at: Stop
    moments: list[Stop] = field(default_factory=list)
    minor: bool = False
    tile: Optional[tuple[int, int]] = None
    focus: str = "time"
    selected: Optional[int] = None
    highlight: bool = False
    scroll: int = 0
    prompt: Optional[str] = None
    message: str = ""
    _synced: Optional[tuple] = field(default=None, repr=False)  # (width, current stop): when the scroll last followed
    _map: Optional[tuple[tuple, CellGrid]] = field(default=None, repr=False)  # the last map drawn, with its key
    _events: Optional[tuple[tuple[int, bool], list[ChronicleEvent], Document, list[int]]] = field(
        default=None, repr=False
    )


START: Stop = (0, 0, -1)  # before any event: year 0, month 0 (events are in months 1 and up)


def present_moment(world: World, config: Config) -> Stop:
    """The moment of the present map: after the last event of the world's last year."""
    return world.year, int(config.get("history.months_per_year")), LAST


def _event_stop(event: ChronicleEvent) -> Stop:
    return event.year, event.month, event.id


def _listed_keys(world: World, minor: bool) -> list[Stop]:
    """The keys of the territory changes the chronicle lists: a change made by a minor event is left out while minor
    events are hidden (it would be a stop with no line), and shows on the map from the next stop."""
    hidden = {e.id for e in world.chronicle if e.salience != "major"} if not minor else set()
    return [key for key in world.territory_keys() if key[2] not in hidden]


def change_moments(world: World, config: Config, minor: bool = False) -> list[Stop]:
    """Return every stop of the viewer, oldest first: one for each listed event (the major ones, and the minor too when
    ``minor``) and for each territory change of a listed event, so two events of one month are two stops; the start
    (before any event) first and the present last."""
    events = world.chronicle if minor else [e for e in world.chronicle if e.salience == "major"]
    moments = {_event_stop(e) for e in events} | set(_listed_keys(world, minor))
    moments |= {START, present_moment(world, config)}
    return sorted(moments)


def stop_index(moments: list[Stop], at: Stop) -> int:
    """Return the index of the last stop at or before ``at`` (-1 before the first)."""
    return bisect_right(moments, at) - 1


def _year_end(world: World, config: Config, year: int) -> Stop:
    return year, int(config.get("history.months_per_year")), LAST


def tile_moments(world: World, config: Config, tile: tuple[int, int], minor: bool = False) -> list[Stop]:
    """Return a stop for each event at ``tile`` (the minor ones too when ``minor``) and each territory change of a
    listed event that took the tile from one owner to another, oldest first, between the start and the present (both
    always reachable, even when nothing happens at the tile)."""
    x, y = tile
    cell = y * world.width + x
    moments = {_event_stop(e) for e in world.events_at(x, y) if minor or e.salience == "major"}
    listed = set(_listed_keys(world, minor))
    for change in world.territory:
        if change.key not in listed:
            continue
        at = int(np.searchsorted(change.cells, cell))
        if at < len(change.cells) and int(change.cells[at]) == cell:
            moments.add(change.key)
    moments |= {START, present_moment(world, config)}
    return sorted(moments)


def initial_state(
    world: World, config: Config, start: Optional[int | tuple[int, ...]] = None, tile: Optional[tuple[int, int]] = None
) -> HistoryState:
    """Return the starting state: at ``start`` (a year, or a ``(year, month[, event id])``), else the start.

    ``tile`` is the tile the viewer was opened on from the explorer (the tile keys then step through its history).
    """
    moments = change_moments(world, config)
    if start is None:
        at = moments[0]
    elif isinstance(start, int):
        at = _year_end(world, config, start)
    else:
        at = at_end(start)
    return HistoryState(at=at, moments=moments, tile=tile)


def resolve_history_action(token: str, config: Config, prompting: bool = False) -> Action:
    """Translate a key token into a viewer action.

    Actions: ``("step", ±1)``, ``("tile", ±1)``, ``("goto",)``, ``("present",)``, ``("first",)``, ``("last",)``,
    ``("scroll", n)``, ``("page", ±1)``,
    ``("highlight",)``, ``("help",)``, ``("quit",)``, ``("resize",)``, ``("none",)``; while the year
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
    if token == " ":
        return ("highlight",)
    if token == "pagedown":
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


Seg = tuple[str, Optional[RGB]]  # a piece of text and its colour (None: the panel's own)


def _segments_for(world: World, change: TerritoryChange) -> list[Seg]:
    """One short phrase for a change, its powers in their colours: ``expansion: Phya +46 cells`` or
    ``battle: Aldor takes 12 cells from Wend``."""
    (gained, gain_color), (lost, loss_color) = (
        owner_label(world, change.to_owner),
        owner_label(world, change.from_owner),
    )
    cells = len(change.cells)
    if change.from_owner == WILD:
        return [(f"{change.kind}: ", None), (gained, gain_color), (f" +{cells} cells", None)]
    if change.to_owner == WILD:
        return [(f"{change.kind}: ", None), (lost, loss_color), (f" -{cells} cells to the wild", None)]
    return [
        (f"{change.kind}: ", None),
        (gained, gain_color),
        (f" takes {cells} cells from ", None),
        (lost, loss_color),
    ]


def moment_segments(world: World, config: Config, moment: Stop) -> list[Seg]:
    """Describe what the map does at stop ``moment`` in coloured pieces: the territory changes of its event, one phrase
    each, and its conquest."""
    phrases = [_segments_for(world, c) for c in world.territory if c.key == moment]
    for event in world.chronicle:
        if _event_stop(event) == moment and event.kind == "conquest" and "vassalage" in event.tags:
            lord, vassal = world.realms[event.realm_ids[1]], world.realms[event.realm_ids[0]]
            phrases.append(
                [("conquest: ", None), (lord.short, lord.color), (" takes ", None), (vassal.short, vassal.color)]
            )
    if moment == START:
        phrases.append([("the start: before any event", None)])
    if moment == present_moment(world, config):
        phrases.append([("the present", None)])
    if not phrases:
        return [("the map does not change here", None)]
    return [seg for index, phrase in enumerate(phrases) for seg in ([("; ", None)] if index else []) + phrase]


def moment_summary(world: World, config: Config, moment: Stop) -> str:
    """Describe what the map does at stop ``moment`` as plain text (see :func:`moment_segments`)."""
    return "".join(text for text, _ in moment_segments(world, config, moment))


def _fit_segments(segments: list[Seg], width: int) -> list[Seg]:
    """``segments`` cut to ``width`` cells in all, ending in ``...`` when something was cut."""
    if sum(len(text) for text, _ in segments) <= width:
        return segments
    kept: list[Seg] = []
    room = max(0, width - 3)
    for text, color in segments:
        if room <= 0:
            break
        kept.append((text[:room], color))
        room -= len(text)
    return [*kept, ("...", None)] if width >= 3 else kept


def _put_segments(grid: CellGrid, row: int, col: int, segments: list[Seg], fg: RGB, bg: RGB, bold: bool = False) -> int:
    """Write coloured pieces of text one after the other from ``col`` and return the column after the last."""
    for text, color in segments:
        _put(grid, row, col, text, color if color is not None else fg, bg, bold and color is None)
        col += len(text)
    return col


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
    shown = state.selected if state.highlight else None
    key = (area, state.at, state.minor, state.tile, shown, state.highlight, state.focus, color, ascii_only)
    if state._map is None or state._map[0] != key:
        sampler = FitSampler(world, config, area[0], area[1])
        view = resolve_view(config, "political")
        grid = build_grid(world, config, view, sampler, None, ascii_only, color, "all", 0, None, state.at)
        _draw_markers(grid, world, config, state, sampler)
        _mark_tile(grid, state, sampler)
        _show_power(grid, world, state, sampler)
        _show_event(grid, world, config, state, sampler)
        state._map = (key, grid)
    return state._map[1]


def _mark_tile(grid: CellGrid, state: HistoryState, sampler: FitSampler) -> None:
    """Reverse the cell of the selected tile, so it can be found on the map."""
    if state.tile is None:
        return
    col, row = sampler.cell_coords(*state.tile) or (-1, -1)
    if 0 <= row < grid.rows and 0 <= col < grid.cols:
        fg, bg = grid.fg[row, col].copy(), grid.bg[row, col].copy()
        grid.fg[row, col], grid.bg[row, col] = bg, fg
        grid.bold[row, col] = True


def _show_power(grid: CellGrid, world: World, state: HistoryState, sampler: FitSampler) -> None:
    """While the highlight is on, brighten the selected power's land on the map and dim everything else."""
    if not state.highlight or state.selected is None:
        return
    owners = sampler.nearest(world.owners_at(*state.at))
    mine = owners == state.selected
    grid.bg[mine] = mix_colors(grid.bg[mine], (255, 255, 255), 0.45)
    grid.bg[~mine] = mix_colors(grid.bg[~mine], (0, 0, 0), 0.55)
    grid.fg[~mine] = mix_colors(grid.fg[~mine], (0, 0, 0), 0.55)


def event_focus(world: World, config: Config, state: HistoryState) -> tuple[np.ndarray, set[int]]:
    """Return ``(cells, owners)`` the events at ``state.at`` are about.

    ``cells`` are flat tile indices: an event's location, its points of interest, the road it laid and the land its
    territory changes moved (a battle's front). ``owners`` holds the territory owner values of the realms of an event
    of a ``realm_kinds`` kind (a war: its combatants), or of an event with no place at all; any other event with a
    place leaves its realms out.
    """
    cells: list[int] = []
    owners: set[int] = set()
    realm_kinds = set(config.get("history.viewer.event_highlight.realm_kinds"))
    here = [e for e in world.chronicle if _event_stop(e) == state.at]
    for event in here:
        found: list[int] = []
        if event.kind not in realm_kinds:
            if event.location != NO_LOCATION:
                found.append(event.location[1] * world.width + event.location[0])
            found += [world.pois[i].y * world.width + world.pois[i].x for i in event.poi_ids if i < len(world.pois)]
            for link in world.road_links:
                if link.event_id == event.id:
                    found += link.cells.tolist()
        if found:
            cells += found
        else:
            owners |= set(event.realm_ids)
            owners |= {fallen_owner(i) for i in event.fallen_ids}
            owners |= {predecessor_owner(i) for i in event.predecessor_ids}
    for change in world.territory:
        if change.key == state.at:
            cells += change.cells.tolist()
    return np.array(sorted(set(cells)), dtype=np.int64), owners


def _show_event(grid: CellGrid, world: World, config: Config, state: HistoryState, sampler: FitSampler) -> None:
    """Brighten what the current moment's events are about (their tiles, or the land of their realms when they have no
    place) and dim the rest, as the powers list does for a power. Shown while Space has switched the highlight on, and
    only in the time focus (the powers list lights its own power)."""
    settings = config.get("history.viewer.event_highlight")
    if not settings["enabled"] or state.focus != "time" or not state.highlight:
        return
    cells, owners = event_focus(world, config, state)
    lit = np.zeros((grid.rows, grid.cols), dtype=bool)
    if owners:
        lit |= np.isin(sampler.nearest(world.owners_at(*state.at)), sorted(owners))
    if cells.size:
        cols, rows = (cells % world.width) // sampler.block_w, (cells // world.width) // sampler.block_h
        lit[rows, cols] = True
    if not lit.any():
        return
    grid.bg[lit] = mix_colors(grid.bg[lit], (255, 255, 255), float(settings["lift"]))
    grid.bg[~lit] = mix_colors(grid.bg[~lit], (0, 0, 0), float(settings["dim"]))
    grid.fg[~lit] = mix_colors(grid.fg[~lit], (0, 0, 0), float(settings["dim"]))


def _draw_markers(grid: CellGrid, world: World, config: Config, state: HistoryState, sampler: FitSampler) -> None:
    """Mark the events with a place on ``grid``: this moment's in full colour and bold, the earlier ones of the last
    ``marker_years`` years faded (glyphs from ``history.viewer.glyphs``, colours from ``history.colors``)."""
    settings = config.get("history.viewer")
    glyphs, palette = settings["glyphs"], config.get("history.colors")
    oldest = state.at[0] - int(settings["marker_years"])
    for event in world.chronicle:  # oldest first, so a newer marker is drawn over an older one
        moment = _event_stop(event)
        if event.kind not in glyphs or event.location == NO_LOCATION or moment > state.at or event.year < oldest:
            continue
        if event.salience == "minor" and not state.minor:
            continue
        col, row = sampler.cell_coords(*event.location) or (-1, -1)
        if not (0 <= row < grid.rows and 0 <= col < grid.cols):
            continue
        red, green, blue = palette[event.kind]
        colour: RGB = (int(red), int(green), int(blue))
        now = moment == state.at
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
    """List the powers at the moment under the map: a swatch, the name (a vassal names its overlord) and the area.

    The selected power is marked with ``>`` (reversed while the list has the focus) and kept in view.
    """
    fg, bg, dim = panel_color(config, "fg"), panel_color(config, "bg"), panel_color(config, "dim")
    km2 = world.scale.cell_area_km2
    entries = _powers(world, state)
    heading = f"powers: {len(entries)}" + ("  (Tab: back to time)" if state.focus == "powers" else "  (Tab: examine)")
    _put(screen, top, 1, heading, dim, bg)
    room = max(0, bottom - top - 1)
    owners = [owner for owner, _ in entries]
    at = owners.index(state.selected) if state.selected in owners else -1
    first = max(0, at - room + 2) if at >= room - 1 and len(entries) > room else 0
    shown = entries[first : first + (room if len(entries) - first <= room else max(0, room - 1))]
    for offset, (owner, cells) in enumerate(shown):
        label, color = owner_label(world, owner)
        name: list[Seg] = [(label, color)]
        if owner >= 0:
            lord = world.top_realm_at(owner, *state.at)
            if lord != owner:
                name += [(" (vassal of ", None), (world.realms[lord].short, world.realms[lord].color), (")", None)]
        row = top + 1 + offset
        picked = owner == state.selected
        row_fg, row_bg = (bg, fg) if picked and state.focus == "powers" else (fg, bg)
        if picked:
            screen.glyph[row, 0:width] = " "
            screen.bg[row, 0:width] = row_bg
        _put(screen, row, 0, ">" if picked else " ", row_fg, row_bg, bold=picked)
        _put(screen, row, 1, "  ", row_fg, color)
        area = f"{cells * km2:,.0f} km2"
        reversed_row = picked and state.focus == "powers"  # a reversed row keeps one colour so it stays readable
        shown_name = [(text, None if reversed_row else paint) for text, paint in name]
        _put_segments(screen, row, 4, _fit_segments(shown_name, max(0, width - len(area) - 6)), row_fg, row_bg)
        _put(screen, row, max(4, width - len(area) - 1), area, dim if not picked else row_fg, row_bg)
    if first + len(shown) < len(entries) and room:
        _put(screen, top + room, 1, f"... and {len(entries) - first - len(shown)} more", dim, bg)


def _years(now: int, since: Optional[int]) -> str:
    """How long ago ``since`` was from year ``now``: ``for 40 years`` (the viewed year minus the start year)."""
    gap = max(0, now - (now if since is None else since))
    return "for less than a year" if gap == 0 else f"for {gap} year" + ("s" if gap > 1 else "")


_NONE = "-"  # what a row shows when it has no data, so every row is always there
_LABEL_WIDTH = 13  # the value column: every label fits in front of it
_VASSAL_SLOTS = 3  # rows kept for the vassals before the relations list begins


def _profile_rows(world: World, config: Config, state: HistoryState, width: int) -> list[list[Seg]]:
    """The selected power's profile at the stop as rows of coloured pieces of text (colour None: the panel's).

    The layout is the same for every power, so one can be compared with the next by flicking between them: each
    fact has its own row with a ``-`` where the power has none; the settlements have a row per tier; the vassals have a
    heading and a few reserved rows (``+N more`` after them); and the relations, the one list left to grow, come last
    under a heading that never moves. Every row is one line long. A ruler, a seat, a liege, a vassal or a power in a
    relation is in the colour of its realm.
    """
    if state.selected is None:
        return [[("no power selected", None)]]
    profile = power_profile(world, config, state.selected, state.at)
    year = state.at[0]

    def row(label: str, value: object = None, color: Optional[RGB] = None, tail: str = "") -> list[Seg]:
        shown = _NONE if value is None or value == "" else str(value)
        pieces: list[Seg] = [(f"{label:<{_LABEL_WIDTH}}", None), (shown, color if shown != _NONE else None)]
        return _fit_segments([*pieces, (tail, None)] if tail else pieces, width)

    if not profile.exists:
        status = f"not yet: begins in year {profile.founded}" if (profile.founded or 0) > year else "gone"
    else:
        status = f"standing since year {profile.founded}" if profile.founded is not None else "standing"
    here, real = profile.exists, profile.exists and profile.owner >= 0  # a fallen or old realm has no ruler or ties
    own = profile.color
    rows = [
        _fit_segments([(f"{profile.name}  ({profile.kind})", profile.color)], width),
        row("status:", status),
        row("ruler:", profile.ruler if real else None, own),
        row("rule:", profile.style if real else None),
        row("reigning:", _years(year, profile.ruler_since).removeprefix("for ") if real and profile.ruler else None),
        row("seat:", profile.capital if real else None, own),
        row("land:", f"{profile.area_km2:,.0f} km2" if here else None),
        row("share:", f"{profile.share:.1%} of the claimed land" if here else None),
        row("people:", f"~{profile.people:,} (~{profile.settled:,} in places)" if here and profile.people else None),
        row(
            "density:",
            f"{profile.people / (profile.area_km2 / 1000.0):.1f} per 1,000 km2" if here and profile.people else None,
        ),
        row("strength:", f"{profile.strength:.2f}" if here and profile.strength else None),
        row("bows to:", profile.liege if real else None, profile.liege_color),
        row("places:", f"{sum(count for _, count in profile.settlements)}" if here and profile.settlements else None),
    ]
    held = dict(profile.settlements)
    tiers = [str(r["label"]) for r in sorted(config.get("tables.tiers").values(), key=lambda r: int(r["rank"]))]
    for label in (*tiers, "Homestead"):
        count = held.get(label)
        rows.append(row(f"  {label}:", count if here and count else None))
    vassals = list(zip(profile.vassals, profile.vassal_colors, strict=False)) if real else []
    rows.append(row("vassals:", len(vassals) or None))
    shown = vassals[:_VASSAL_SLOTS] if len(vassals) <= _VASSAL_SLOTS else vassals[: _VASSAL_SLOTS - 1]
    for slot in range(_VASSAL_SLOTS):
        if slot < len(shown):
            rows.append(row("", shown[slot][0], shown[slot][1]))
        elif slot == len(shown) and len(vassals) > _VASSAL_SLOTS:
            rows.append(row("", f"+{len(vassals) - _VASSAL_SLOTS + 1} more"))
        else:
            rows.append(row("", _NONE if slot == 0 and not vassals else None))
    ties = list(zip(profile.ties, profile.tie_colors, strict=False)) if real else []
    rows.append(row("relations:", len(ties) or None))
    labels = {"war": "at war with", "rivalry": "rival of", "alliance": "allied with", "trade": "trading with"}
    for (kind, other, since), color in ties:
        rows.append(
            _fit_segments(
                [
                    (f"{'':<{_LABEL_WIDTH}}{labels.get(kind, kind)} ", None),
                    (other, color),
                    (f", {_years(year, since).removeprefix('for ')}", None),
                ],
                width,
            )
        )
    return rows


def _draw_profile(screen: CellGrid, world: World, config: Config, state: HistoryState, left: int, body: int) -> None:
    """Draw the selected power's profile in the right column, one fixed row per fact (see :func:`_profile_rows`)."""
    fg, bg = panel_color(config, "fg"), panel_color(config, "bg")
    width = screen.cols - left - 1
    for offset, segments in enumerate(_profile_rows(world, config, state, width)[:body]):
        _put_segments(screen, _HEADER_ROWS + offset, left, segments, fg, bg)
        if offset == 0:
            screen.bold[_HEADER_ROWS, left : left + width] = True


def _select(world: World, state: HistoryState, step: int) -> None:
    """Move the selection ``step`` places down the powers list (up when negative), starting at the largest."""
    owners = [owner for owner, _ in _powers(world, state)]
    if not owners:
        return
    at = owners.index(state.selected) if state.selected in owners else (-1 if step > 0 else len(owners))
    state.selected = owners[max(0, min(len(owners) - 1, at + step))]


def _events_layout(world: World, config: Config, state: HistoryState, width: int):
    """Return ``(events, lines, starts)`` of the listed events (the major ones, and the minor too when shown) wrapped to
    ``width`` (cached per width and listing)."""
    if state._events is None or state._events[0] != (width, state.minor):
        events = filter_events(world, ChronicleFilter(salience="all" if state.minor else "major"))
        lines, starts, _ = layout_events(world, config, events, width)
        state._events = ((width, state.minor), events, lines, starts)
    return state._events[1:]


def _help_lines(config: Config, tile: bool) -> tuple[str, ...]:
    """The help text: the keys (the tile keys when a tile is selected), then what the marks on the map and the powers
    list mean (from the config's glyphs)."""
    glyphs = config.get("history.viewer.glyphs")
    marks = "   ".join(f"{glyph} {kind}" for kind, glyph in glyphs.items())
    years = int(config.get("history.viewer.marker_years"))
    return (
        *_HISTORY_HELP[:3],
        *(("{history_prev_tile} / {history_next_tile}   previous / next event at the selected tile",) if tile else ()),
        *_HISTORY_HELP[3:-1],
        "",
        "Marks on the map: events that had a place",
        f"  {marks}",
        f"  bold: this moment's events; faded: those of the last {years} years",
        "  Space lights what this moment's events are about (their tiles, or their realms' land for a war or a deal)",
        "Powers list: the swatch is the power's colour on the map; (vassal of X): it had bowed to X by then.",
        "  {history_focus}: examine a power; up / down choose; Space shows its land on the map, Space again hides it",
        _HISTORY_HELP[-1],
    )


def _title(world: World, config: Config, state: HistoryState) -> str:
    year, month = state.at[:2]
    index = stop_index(state.moments, state.at)
    place = "before the first event" if index < 0 else f"stop {index + 1}/{len(state.moments)}"
    if state.at == START:
        place += ", the start"
    if state.at >= present_moment(world, config):
        place += ", the present"
    where = "" if state.tile is None else f"  tile {state.tile[0]},{state.tile[1]}"
    island = world.island_name or "the island"
    return f"History of {island}  seed {world.seed}{where}  -  year {year}, month {month} ({place})"


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
    if state.focus == "powers":
        _draw_profile(screen, world, config, state, event_col, body)
    else:
        _draw_events(screen, world, config, state, event_col, body)
    index = stop_index(state.moments, state.at)
    status = moment_segments(world, config, state.moments[index]) if index >= 0 else [("no change yet", None)]
    status_row = rows - _FOOTER_ROWS
    if state.prompt is not None:
        _put(screen, status_row, 0, f" year: {state.prompt}_", head, bg, bold=True)
    else:
        _put_segments(screen, status_row, 0, [(" ", None), *status], fg, bg)
        if state.message:
            _put(screen, status_row, max(0, cols - len(state.message) - 1), state.message, head, bg, bold=True)
    _put(
        screen, rows - 1, 0, _hint_line(config, state.prompt is not None, state.tile is not None, state.focus), dim, bg
    )
    if help_open:
        draw_help(screen, config, _help_lines(config, state.tile is not None))
    return screen


def _draw_events(screen: CellGrid, world: World, config: Config, state: HistoryState, left: int, body: int) -> None:
    """Draw the chronicle in the right column: the event the viewer is at highlighted, later ones dimmed."""
    fg, bg, dim = panel_color(config, "fg"), panel_color(config, "bg"), panel_color(config, "dim")
    width = screen.cols - left - 1
    events, lines, starts = _events_layout(world, config, state, width)
    moments = [_event_stop(e) for e in events]
    key = (width, state.at, state.minor)
    if state._synced != key and events:
        first = min(bisect_left(moments, state.at), len(events) - 1)
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
        is_current = moment == state.at  # the one event the viewer is at
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


def _hint_line(config: Config, prompting: bool, tile: bool, focus: str = "time") -> str:
    keys = config.get("keys")

    def show(name: str) -> str:
        key = keys.get(name, _DEFAULT_KEYS.get(name, "q"))
        return {" ": "space", "\t": "Tab"}.get(key, key)

    if prompting:
        return " [Enter] go  [Esc] cancel"
    here = f"[{show('history_prev_tile')}/{show('history_next_tile')}] this tile  " if tile else ""
    if focus == "powers":
        return (
            f" [up/down] choose a power  [Space] show / hide it on the map  [{show('history_focus')}] back to time  "
            f"[{show('history_prev')}/{show('history_next')}] event  {here}[{show('help')}] help  [{show('quit')}] quit"
        )
    return (
        f" [{show('history_prev')}/{show('history_next')}] event  {here}[Space] light events  "
        f"[{show('history_goto')}] go to year  [{show('history_present')}] present  [{show('filter_salience')}] minor  "
        f"[{show('history_focus')}] powers  [arrows] scroll  [{show('help')}] help  [{show('quit')}] quit"
    )


def _answer_prompt(world: World, config: Config, state: HistoryState, action: Action) -> None:
    """Apply a key to the open year prompt."""
    assert state.prompt is not None
    name = action[0]
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


def _travel(world: World, config: Config, state: HistoryState, action: Action) -> None:
    """Move ``state.at`` along the stops (``step``, ``present``, ``first``, ``last``) or the selected tile's own events
    (``tile``), or change which events are listed (``minor``)."""
    name, here, moments = action[0], state.at, state.moments
    if name == "minor":
        state.minor = not state.minor
        state.moments = change_moments(world, config, state.minor)
        state.message = "showing minor events too" if state.minor else "showing major events only"
        return
    if name in ("step", "tile"):
        if name == "tile" and state.tile is None:
            state.message = "open the viewer with t in the explorer to follow one tile"
            return
        stops = moments if name == "step" else tile_moments(world, config, state.tile or (0, 0), state.minor)
        target = bisect_right(stops, here) if action[1] > 0 else bisect_left(stops, here) - 1
        if 0 <= target < len(stops):
            state.at = stops[target]
        else:
            where = "" if name == "step" else " at this tile"
            state.message = ("nothing later" if action[1] > 0 else "nothing earlier") + where
    elif moments:
        state.at = moments[0] if name == "first" else moments[-1]


def _examine(world: World, state: HistoryState, action: Action) -> None:
    """Apply a key while the powers list has the focus: up and down choose a power, Space shows it on the map."""
    if action[0] == "scroll":
        _select(world, state, 1 if action[1] > 0 else -1)
    elif action[0] == "highlight":
        state.highlight = state.selected is not None and not state.highlight  # Space shows, Space again hides


def apply_history_action(world: World, config: Config, state: HistoryState, action: Action, size: Size) -> None:
    """Apply ``action`` to ``state``; ``help``, ``resize`` and ``quit`` are the loop's, not handled here."""
    name = action[0]
    state.message = ""
    if state.prompt is not None:
        _answer_prompt(world, config, state, action)
    elif name in ("step", "tile", "minor", "present", "first", "last"):
        _travel(world, config, state, ("last",) if name == "present" else action)
    elif name == "goto":
        state.prompt = ""
    elif name == "focus":
        state.focus = "time" if state.focus == "powers" else "powers"
        state.highlight = False
        if state.focus == "powers" and state.selected is None:
            _select(world, state, 1)
    elif state.focus == "powers" and name in ("scroll", "highlight"):
        _examine(world, state, action)
    elif name == "highlight":
        state.highlight = not state.highlight  # Space lights what the events at this moment are about
    elif name == "scroll":
        state.scroll = max(0, state.scroll + action[1])
    elif name == "page":
        state.scroll = max(0, state.scroll + action[1] * max(1, size[1] - _HEADER_ROWS - _FOOTER_ROWS - 1))

        state.scroll = max(0, state.scroll + action[1] * max(1, size[1] - _HEADER_ROWS - _FOOTER_ROWS - 1))


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

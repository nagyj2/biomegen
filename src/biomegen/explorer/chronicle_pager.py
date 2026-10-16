"""The chronicle pager: scroll, filter and search a world's chronicle full screen.

It is the interactive form of ``--chronicle``. It reuses the explorer's machinery (key tokens, the rebindable ``keys``
table, the panel colours, the help box and the diff writer), so it feels like the map: arrows, WASD and HJKL scroll
(shift or capitals go ``controls.fast_step`` lines), ``?`` shows the help and ``q`` or Esc quits. Everything outside
:func:`run_chronicle` is pure, so the loop is tested with a scripted key source and an in-memory terminal.

Filters (kind, years, realm and the CLI's text) narrow the list; a search highlights its matches in what is listed and
jumps between them. Both start from the CLI's ``--kind``, ``--from-year``, ``--to-year``, ``--realm`` and ``--search``.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, TextIO

from ..config.model import Config
from ..render.chronicle import layout_events
from ..render.grid import RGB, CellGrid, Document
from ..world.chronicle import ChronicleFilter, chronicle_names, chronicle_title, describe_filter, filter_events
from ..world.entities import EVENT_KINDS, ChronicleEvent
from ..world.world import World
from .input import Action, KeyReader, make_reader
from .panel import draw_help, panel_color
from .writer import DiffWriter

Size = tuple[int, int]  # (columns, rows)

_HEADER_ROWS = 1  # the title
_FOOTER_ROWS = 2  # the status line and the key hints
_MIN_COLS = 24

_SCROLL_LETTERS = {"w": "up", "s": "down", "k": "up", "j": "down"}
_BOUND_ACTIONS = (
    ("search", ("prompt", "search")),
    ("search_next", ("match", 1)),
    ("search_prev", ("match", -1)),
    ("filter_kind", ("cycle_kind",)),
    ("filter_years", ("prompt", "years")),
    ("filter_realm", ("prompt", "realm")),
    ("filter_clear", ("clear",)),
    ("top", ("top",)),
    ("bottom", ("bottom",)),
    ("help", ("help",)),
)
_DEFAULT_KEYS = {
    "search": "/",
    "search_next": "n",
    "search_prev": "N",
    "filter_kind": "v",
    "filter_years": "y",
    "filter_realm": "p",
    "filter_clear": "c",
    "top": "g",
    "bottom": "G",
    "help": "?",
}
_PROMPT_LABELS = {"search": "search", "years": "years (FROM-TO)", "realm": "realm, ruler or place"}
_MAX_SUGGESTIONS = 8
_PAGER_HELP = (
    "Chronicle keys",
    "",
    "arrows / WASD / HJKL   scroll (shift or capitals: {step})",
    "space / Page Down / Page Up   scroll a page",
    "{top} / {bottom}   first / last event",
    "{search}   search (highlights)   {search_next} / {search_prev}   next / previous",
    "{filter_kind}   cycle the event-kind filter",
    "{filter_years}   filter by years (100-300, 100-, -300)",
    "{filter_realm}   filter by realm, ruler or settlement name",
    "      (Up / Down pick a name, Tab completes it)",
    "{filter_clear}   clear every filter and search",
    "{help}   this help      {quit} or Esc   quit",
)


@dataclass
class _Layout:
    """The wrapped lines of the listed events for one width, filter and search."""

    key: tuple
    events: list[ChronicleEvent]
    lines: Document
    starts: list[int]
    matches: list[int]


@dataclass
class _Prompt:
    """An open prompt: what it asks for, the text typed so far, and the suggestion picked with Up / Down (-1: none)."""

    kind: str
    text: str = ""
    choice: int = -1


@dataclass
class PagerState:
    """What the pager shows and where it is.

    Attributes:
        chronicle_filter: The filter applied to the chronicle.
        query: The search text (any case); empty means no search.
        scroll: Index of the first line shown.
        current: Index (in the listed events) of the search match the view is on, -1 before the first jump.
        prompt: The open prompt, or ``None``.
        names: Every realm, ruler and settlement name of the chronicle, for the realm prompt's suggestions.
        message: A short note for the status line (an unparsable year range, no match, ...).
        layout: The last layout, reused while the width, filter and search stay the same.
    """

    chronicle_filter: ChronicleFilter = field(default_factory=ChronicleFilter)
    query: str = ""
    scroll: int = 0
    current: int = -1
    prompt: Optional[_Prompt] = None
    names: Optional[list[str]] = None
    message: str = ""
    layout: Optional[_Layout] = None


def resolve_pager_action(token: str, config: Config, prompting: bool = False) -> Action:
    """Translate a key token into a pager action.

    Actions: ``("scroll", n)``, ``("page", ±1)``, ``("top",)``, ``("bottom",)``, ``("match", ±1)``, ``("cycle_kind",)``,
    ``("prompt", "search" | "years" | "realm")``, ``("clear",)``, ``("help",)``, ``("quit",)``, ``("resize",)``,
    ``("none",)``; while a prompt is open also ``("type", char)``, ``("backspace",)``, ``("submit",)``, ``("cancel",)``,
    ``("choice", ±1)`` (Up / Down) and ``("complete",)`` (Tab).
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
        if token in ("up", "down"):
            return ("choice", -1 if token == "up" else 1)
        if token == "\t":
            return ("complete",)
        return ("type", token) if len(token) == 1 and token.isprintable() else ("none",)
    step = int(config.get("controls.fast_step", 8))
    bound = {keys.get(name, _DEFAULT_KEYS[name]): action for name, action in _BOUND_ACTIONS}
    if token == "esc" or token == keys.get("quit", "q"):
        return ("quit",)
    if token in bound:
        return bound[token]
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
        return ("top",)
    if token == "end":
        return ("bottom",)
    return ("none",)


def parse_years(text: str) -> tuple[Optional[int], Optional[int]]:
    """Parse ``FROM-TO``, ``FROM-``, ``-TO`` or one year into ``(year_from, year_to)``; unreadable: ``ValueError``."""
    low, dash, high = text.strip().partition("-")  # years are never negative, so a leading dash means "no start"
    if not dash:
        return int(low), int(low)
    year_from = int(low) if low.strip() else None
    year_to = int(high) if high.strip() else None
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("the range ends before it starts")
    return year_from, year_to


def _layout(world: World, config: Config, state: PagerState, width: int) -> _Layout:
    """Return the layout for ``width``, the filter and the search, building it only when one of them changed."""
    key = (width, state.chronicle_filter, state.query, state.current)
    if state.layout is None or state.layout.key != key:
        events = filter_events(world, state.chronicle_filter)
        lines, starts, matches = layout_events(world, config, events, width, state.query, state.current)
        state.layout = _Layout(key, events, lines, starts, matches)
    return state.layout


def body_rows(rows: int) -> int:
    """Return how many lines of the chronicle fit in a terminal of ``rows`` rows."""
    return max(0, rows - _HEADER_ROWS - _FOOTER_ROWS)


def _put(grid: CellGrid, row: int, col: int, text: str, fg: RGB, bg: RGB, bold: bool = False) -> None:
    """Write clipped ``text`` into one row of ``grid``."""
    text = text[: max(0, grid.cols - col)]
    if not text:
        return
    span = slice(col, col + len(text))
    grid.glyph[row, span] = list(text)
    grid.fg[row, span] = fg
    grid.bg[row, span] = bg
    grid.bold[row, span] = bold


def _hint_line(config: Config, prompt: Optional[_Prompt]) -> str:
    """The key hints in the explorer's ``[key] action`` form, built from the ``keys`` table so rebinding shows up."""
    keys = config.get("keys")

    def show(name: str) -> str:
        key = keys.get(name, _DEFAULT_KEYS.get(name, "q"))
        return "space" if key == " " else key

    if prompt is not None:
        choose = "  [Up/Down] choose  [Tab] complete" if prompt.kind == "realm" else ""
        return f" [Enter] apply{choose}  [Esc] cancel"
    return (
        f" [arrows] scroll  [{show('search')}] search  [{show('search_next')}/{show('search_prev')}] next/prev  "
        f"[{show('filter_kind')}] kind  [{show('filter_years')}] years  [{show('filter_realm')}] name  "
        f"[{show('filter_clear')}] clear  [{show('help')}] help  [{show('quit')}] quit"
    )


def _status_line(world: World, state: PagerState, layout: _Layout, first: int, shown_rows: int) -> str:
    """The status text: events listed, the filter, the search and where the view is."""
    total = len(world.chronicle)
    parts = [f" {len(layout.events)}/{total} events"]
    described = describe_filter(state.chronicle_filter)
    if described:
        parts.append(described)
    if state.query:
        found = f"{layout.matches.index(state.current) + 1}/" if state.current in layout.matches else ""
        parts.append(f"search {state.query!r}: {found}{len(layout.matches)} found")
    last = min(len(layout.lines), first + shown_rows)
    parts.append(f"lines {min(first + 1, last)}-{last}/{len(layout.lines)}")
    return "   ".join(parts)


def compose_pager_frame(
    world: World, config: Config, state: PagerState, size: Size, help_open: bool = False
) -> CellGrid:
    """Compose one terminal-sized frame: title, the visible lines, the status line and the key hints.

    Clamps ``state.scroll`` to the lines that exist for this size.
    """
    cols, rows = size
    fg, bg = panel_color(config, "fg"), panel_color(config, "bg")
    dim, head = panel_color(config, "dim"), panel_color(config, "head")
    screen = CellGrid(max(1, rows), max(1, cols), bg=bg, fg=fg)
    if body_rows(rows) < 1 or cols < _MIN_COLS:
        _put(screen, 0, 0, "terminal too small - enlarge the window"[:cols], fg, bg)
        return screen
    layout = _layout(world, config, state, cols)
    shown_rows = body_rows(rows)
    state.scroll = max(0, min(state.scroll, len(layout.lines) - shown_rows))
    _put(screen, 0, 0, chronicle_title(world)[:cols], head, bg, bold=True)
    for offset, line in enumerate(layout.lines[state.scroll : state.scroll + shown_rows]):
        col = 0
        for span in line:
            _put(screen, _HEADER_ROWS + offset, col, span.text, span.fg or fg, span.bg or bg, span.bold)
            col += len(span.text)
    if not layout.lines:
        _put(screen, _HEADER_ROWS, 1, "(no events match)", dim, bg)
    status_row = rows - _FOOTER_ROWS
    if state.prompt is not None:
        label = _PROMPT_LABELS[state.prompt.kind]
        _put(screen, status_row, 0, f" {label}: {state.prompt.text}_", head, bg, bold=True)
        _draw_suggestions(screen, config, world, state, status_row)
    else:
        _put(screen, status_row, 0, _status_line(world, state, layout, state.scroll, shown_rows), fg, bg)
        if state.message:
            _put(screen, status_row, max(0, cols - len(state.message) - 1), state.message, head, bg, bold=True)
    _put(screen, rows - 1, 0, _hint_line(config, state.prompt), dim, bg)
    if help_open:
        draw_help(screen, config, _PAGER_HELP)
    return screen


def suggestions(names: list[str], text: str) -> list[str]:
    """Return the names containing ``text`` (any case), those that start with it first."""
    needle = text.lower()
    hits = [name for name in names if needle in name.lower()]
    return sorted(hits, key=lambda name: not name.lower().startswith(needle))


def _suggestions_of(world: World, state: PagerState) -> list[str]:
    """Return the realm prompt's suggestions for what is typed so far (none for the other prompts)."""
    if state.prompt is None or state.prompt.kind != "realm":
        return []
    if state.names is None:
        state.names = chronicle_names(world)
    return suggestions(state.names, state.prompt.text)


def _draw_suggestions(screen: CellGrid, config: Config, world: World, state: PagerState, status_row: int) -> None:
    """List the suggestions in the rows just above the status line, the picked one reversed."""
    assert state.prompt is not None
    found = _suggestions_of(world, state)
    shown = min(_MAX_SUGGESTIONS, len(found), max(0, status_row - _HEADER_ROWS))
    first = max(0, state.prompt.choice - shown + 1)
    fg, bg = panel_color(config, "help_fg"), panel_color(config, "help_bg")
    for offset, name in enumerate(found[first : first + shown]):
        picked = first + offset == state.prompt.choice
        _put(
            screen,
            status_row - shown + offset,
            0,
            f" {name}".ljust(screen.cols),
            bg if picked else fg,
            fg if picked else bg,
        )


def _reveal(state: PagerState, layout: _Layout, position: int, shown_rows: int) -> None:
    """Scroll just enough for the event at ``position`` to be in view (starting the view with it when it is not)."""
    start = layout.starts[position]
    end = layout.starts[position + 1] if position + 1 < len(layout.starts) else len(layout.lines)
    if start < state.scroll or end > state.scroll + shown_rows:
        state.scroll = max(0, min(start, len(layout.lines) - shown_rows))


def _go_to_match(state: PagerState, layout: _Layout, direction: int, shown_rows: int) -> None:
    """Move to the next (``direction`` 1) or previous (-1) event that matches the search, wrapping round.

    Before the first jump the nearest match at or below (above) the view is taken.
    """
    matches = layout.matches
    if not state.query:
        state.message = "no search yet"
        return
    if not matches:
        state.message = "no match"
        return
    if state.current in matches:
        index = (matches.index(state.current) + direction) % len(matches)
    elif direction > 0:
        index = next((i for i, m in enumerate(matches) if layout.starts[m] >= state.scroll), 0)
    else:
        index = next((i for i in range(len(matches) - 1, -1, -1) if layout.starts[matches[i]] < state.scroll), -1)
    state.current = matches[index]
    _reveal(state, layout, state.current, shown_rows)
    state.message = f"match {index % len(matches) + 1}/{len(matches)}"


def _submit_prompt(world: World, config: Config, state: PagerState, size: Size) -> None:
    """Apply the open prompt's text: a search, a year range or a name (empty text clears that part)."""
    assert state.prompt is not None
    kind, text = state.prompt.kind, state.prompt.text
    found = _suggestions_of(world, state)
    if 0 <= state.prompt.choice < len(found):
        text = found[state.prompt.choice]
    state.prompt = None
    if kind == "search":
        state.query = text
        state.current = -1
        if text:
            _go_to_match(state, _layout(world, config, state, size[0]), 1, body_rows(size[1]))
        return
    if kind == "years":
        try:
            year_from, year_to = parse_years(text) if text.strip() else (None, None)
        except ValueError:
            state.message = "years: use FROM-TO, FROM- or -TO"
            return
        state.chronicle_filter = replace(state.chronicle_filter, year_from=year_from, year_to=year_to)
    else:
        state.chronicle_filter = replace(state.chronicle_filter, realm=text.strip())
    state.scroll = 0
    state.current = -1


def _complete(world: World, state: PagerState) -> None:
    """Tab: take the picked suggestion, else the prefix all suggestions share, else the first suggestion."""
    assert state.prompt is not None
    found = _suggestions_of(world, state)
    if not found:
        return
    text = state.prompt.text
    if 0 <= state.prompt.choice < len(found):
        text = found[state.prompt.choice]
    else:
        lower = [name.lower() for name in found]
        shared = os.path.commonprefix(lower)
        if all(name.startswith(text.lower()) for name in lower) and len(shared) > len(text):
            text = found[0][: len(shared)]
        else:
            text = found[0]
    state.prompt = _Prompt(state.prompt.kind, text)


def _cycle_kind(state: PagerState) -> None:
    """Move the kind filter to the next kind: all, then each of ``EVENT_KINDS``, then all again."""
    options = ("", *EVENT_KINDS)
    kinds = state.chronicle_filter.kinds
    current = options.index(kinds[0]) if len(kinds) == 1 else 0
    chosen = options[(current + 1) % len(options)]
    state.chronicle_filter = replace(state.chronicle_filter, kinds=(chosen,) if chosen else ())
    state.scroll = 0
    state.current = -1


def apply_action(world: World, config: Config, state: PagerState, action: Action, size: Size) -> None:
    """Apply ``action`` to ``state``; ``help``, ``resize`` and ``quit`` are the loop's, not handled here."""
    name = action[0]
    shown_rows = body_rows(size[1])
    state.message = ""
    if state.prompt is not None:
        prompt = state.prompt
        if name == "type":
            state.prompt = _Prompt(prompt.kind, prompt.text + action[1])
        elif name == "backspace":
            state.prompt = _Prompt(prompt.kind, prompt.text[:-1])
        elif name == "choice":
            slots = len(_suggestions_of(world, state)) + 1  # slot 0 is "none picked"
            prompt.choice = (prompt.choice + 1 + action[1]) % slots - 1
        elif name == "complete":
            _complete(world, state)
        elif name == "cancel":
            state.prompt = None
        elif name == "submit":
            _submit_prompt(world, config, state, size)
        return
    if name == "scroll":
        state.scroll = max(0, state.scroll + action[1])
    elif name == "page":
        state.scroll = max(0, state.scroll + action[1] * max(1, shown_rows - 1))
    elif name == "top":
        state.scroll = 0
    elif name == "bottom":
        state.scroll = 1 << 30  # clamped to the last page when the frame is composed
    elif name == "match":
        _go_to_match(state, _layout(world, config, state, size[0]), action[1], shown_rows)
    elif name == "cycle_kind":
        _cycle_kind(state)
        state.message = f"kind: {state.chronicle_filter.kinds[0] if state.chronicle_filter.kinds else 'all'}"
    elif name == "prompt":
        initial = {"search": state.query, "years": "", "realm": state.chronicle_filter.realm}[action[1]]
        state.prompt = _Prompt(action[1], initial)
    elif name == "clear":
        state.chronicle_filter = ChronicleFilter()
        state.query = ""
        state.scroll = 0
        state.current = -1
        state.message = "filters cleared"


def run_chronicle(
    world: World,
    config: Config,
    color_mode: str = "truecolor",
    chronicle_filter: Optional[ChronicleFilter] = None,
    *,
    reader: Optional[KeyReader] = None,
    out: Optional[TextIO] = None,
    get_size: Optional[Callable[[], Size]] = None,
) -> None:
    """Run the chronicle pager until the user quits.

    Args:
        world: The generated world.
        config: The merged configuration.
        color_mode: ``"truecolor"``, ``"256"`` or ``"none"``.
        chronicle_filter: The filter to start with (``--kind``, ``--from-year``, ...); its text also starts the search.
        reader: The key source (default: the platform reader on stdin); tests pass a scripted one.
        out: The output stream (default: stdout).
        get_size: Returns ``(columns, rows)``; default is the terminal size.
    """
    reader = reader if reader is not None else make_reader()
    writer = DiffWriter(out if out is not None else sys.stdout, color_mode)
    size_of = get_size if get_size is not None else _terminal_size
    state = PagerState(chronicle_filter=chronicle_filter or ChronicleFilter())
    state.query = state.chronicle_filter.text
    help_open = False
    with reader:
        writer.enter()
        try:
            while True:
                size = size_of()
                writer.draw(compose_pager_frame(world, config, state, size, help_open))
                action = resolve_pager_action(reader.read_key(), config, state.prompt is not None)
                if action[0] == "resize":
                    writer.invalidate()
                    continue
                if help_open:
                    help_open = False  # any key closes the help and does nothing else
                    continue
                if action[0] == "quit":
                    break
                if action[0] == "help":
                    help_open = True
                    continue
                apply_action(world, config, state, action, size)
        finally:
            writer.leave()


def _terminal_size() -> Size:
    size = shutil.get_terminal_size(fallback=(120, 36))
    return size.columns, size.lines

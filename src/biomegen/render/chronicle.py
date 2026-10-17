"""The chronicle as a coloured document: year, event type and text in three columns.

The event type takes its colour from ``history.colors``. A name in the text is coloured by what it names, with the same
colours as the political map: a realm, its ruler and its settlements in the realm's own colour, a fallen realm in its
own. A settlement is in the neutral ``settlement`` colour the first time the chronicle names it (and always when no
realm holds it); a mountain, sea, river or other named land is in the neutral ``place`` colour. The plain text of the
document equals :func:`biomegen.world.chronicle.chronicle_text`. :func:`layout_events` wraps the rows to a width (for
the scrolling pager) and marks the text a search matches.
"""

from __future__ import annotations

from typing import Optional, Sequence

from ..config.model import Config
from ..world.chronicle import KIND_WIDTH, chronicle_title, expression_terms, matches_expression, parse_expression
from ..world.entities import REF_FALLEN, REF_FEATURE, REF_POI, REF_PREDECESSOR, REF_REALM, REF_RULER, ChronicleEvent
from ..world.world import World
from .grid import RGB, Document, Span


def _palette(config: Config) -> dict[str, RGB]:
    """The ``history.colors`` entries as RGB triples."""
    return {name: (int(c[0]), int(c[1]), int(c[2])) for name, c in config.get("history.colors").items()}


def event_rows(world: World, config: Config) -> list[list[Span]]:
    """Return one row of styled spans per event of ``world.chronicle`` (year, kind, then the text with names coloured).

    Rows follow the chronicle's order, and a settlement is neutral only at its first mention in the whole chronicle, so
    a filtered view colours a name exactly as the full chronicle does.
    """
    palette = _palette(config)
    named: set[int] = set()  # settlements the chronicle has already named

    def name_color(kind: str, ref: int) -> RGB:
        if kind == REF_REALM:
            return world.realms[ref].color
        if kind == REF_RULER:  # a ruler is coloured as their realm
            return world.realms[world.rulers[ref].realm_id].color
        if kind == REF_FALLEN:
            return world.fallen_realms[ref].color
        if kind == REF_PREDECESSOR:
            return world.predecessors[ref].color
        if kind == REF_FEATURE:
            return palette["place"]
        assert kind == REF_POI
        poi = world.pois[ref]
        if config.get(f"tables.pois.{poi.kind}.bandit_strength", 0):  # a bandit tower or dungeon is its own colour
            return palette["hideout"]
        if not poi.civilized:  # a ruin, battlefield or other wild place belongs to no realm
            return palette["settlement"]
        first = ref not in named
        named.add(ref)
        realm = poi.realm_id
        return palette["settlement"] if first or realm < 0 else world.realms[realm].color

    rows: list[list[Span]] = []
    for event in world.chronicle:
        row = [
            Span(f"{event.year:>5}", palette["year"]),
            Span("  "),
            Span(f"{event.kind:<{KIND_WIDTH}}", palette[event.kind], bold=True),
            Span("  "),
        ]
        pos = 0
        for start, end, kind, ref in sorted(event.refs):
            if start > pos:
                row.append(Span(event.text[pos:start]))
            row.append(Span(event.text[start:end], name_color(kind, ref), bold=True))
            pos = end
        if pos < len(event.text):
            row.append(Span(event.text[pos:]))
        rows.append(row)
    return rows


def chronicle_document(world: World, config: Config, events: Optional[Sequence[ChronicleEvent]] = None) -> Document:
    """Return the title and the events (default: all) as rows of styled spans."""
    rows = event_rows(world, config)
    shown = rows if events is None else [rows[event.id] for event in events]
    return [[Span(chronicle_title(world), bold=True)], [], *shown]


def _wrap(cells: list[tuple[str, tuple]], width: int, indent: int) -> list[list[tuple[str, tuple]]]:
    """Break styled characters into lines of at most ``width`` at spaces; continuation lines start ``indent`` in."""
    lines: list[list[tuple[str, tuple]]] = []
    pad = [(" ", (None, None, False))] * indent
    line = list(cells)
    first = True
    while True:
        limit = width if first else width - indent
        if len(line) <= limit:
            lines.append(line if first else pad + line)
            return lines
        cut = limit
        for index in range(limit, 0, -1):  # the last space that still fits, else a hard break
            if line[index][0] == " ":
                cut = index
                break
        head, line = line[:cut], line[cut:]
        while line and line[0][0] == " ":
            line = line[1:]
        lines.append(head if first else pad + head)
        first = False


def _spans(cells: list[tuple[str, tuple]]) -> list[Span]:
    """Merge neighbouring characters of one style into spans."""
    spans: list[Span] = []
    run: list[str] = []
    style: Optional[tuple] = None
    for char, cell_style in cells:
        if cell_style != style and run:
            assert style is not None
            spans.append(Span("".join(run), style[0], style[1], style[2]))
            run = []
        style = cell_style
        run.append(char)
    if run and style is not None:
        spans.append(Span("".join(run), style[0], style[1], style[2]))
    return spans


def layout_events(
    world: World, config: Config, events: Sequence[ChronicleEvent], width: int, query: str = "", current: int = -1
) -> tuple[Document, list[int], list[int]]:
    """Wrap ``events`` to ``width`` columns and mark where ``query`` (any case; ``|`` or, ``&`` and) matches.

    Returns ``(lines, starts, matches)``: the wrapped lines of every event in turn (a continuation line is indented
    under the text column), the line each event starts on, and the indices into ``events`` of those the query matches.
    A matching run is drawn in the ``history.colors.match`` background, or ``match_current`` in the event at index
    ``current``.
    """
    rows = event_rows(world, config)
    palette = _palette(config)
    groups = parse_expression(query)
    terms = expression_terms(groups)
    indent = 5 + 2 + KIND_WIDTH + 2
    lines: Document = []
    starts: list[int] = []
    matches: list[int] = []
    for position, event in enumerate(events):
        cells = [(char, (span.fg, span.bg, span.bold)) for span in rows[event.id] for char in span.text]
        plain = "".join(char for char, _ in cells).lower()
        if groups and matches_expression(groups, [plain]):
            matches.append(position)
            for term in terms:  # every term of the expression is marked wherever it occurs
                hit = plain.find(term)
                while hit >= 0:
                    for index in range(hit, hit + len(term)):
                        char, (fg, _bg, bold) = cells[index]
                        cells[index] = (char, (fg, palette["match_current" if position == current else "match"], bold))
                    hit = plain.find(term, hit + len(term))
        starts.append(len(lines))
        lines.extend(_spans(line) for line in _wrap(cells, max(width, indent + 1), indent))
    return lines, starts, matches

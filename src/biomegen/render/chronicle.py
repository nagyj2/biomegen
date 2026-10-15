"""The chronicle as a coloured document: year, event type and text in three columns.

The event type takes its colour from ``history.colors``. A name in the text is coloured by what it names, with the same
colours as the political map: a realm, its ruler and its settlements in the realm's own colour, a fallen realm in its
own. A settlement is in the neutral ``settlement`` colour the first time the chronicle names it (and always when no
realm holds it); a mountain, sea, river or other named land is in the neutral ``place`` colour. The plain text of the
document equals :func:`biomegen.world.chronicle.chronicle_text`.
"""

from __future__ import annotations

from ..config.model import Config
from ..world.chronicle import KIND_WIDTH, chronicle_title
from ..world.entities import REF_FALLEN, REF_FEATURE, REF_POI, REF_REALM, REF_RULER
from ..world.world import World
from .grid import RGB, Document, Span


def _palette(config: Config) -> dict[str, RGB]:
    """The ``history.colors`` entries as RGB triples."""
    return {name: (int(c[0]), int(c[1]), int(c[2])) for name, c in config.get("history.colors").items()}


def chronicle_document(world: World, config: Config) -> Document:
    """Return the title and every event as rows of styled spans (year, kind, then the text with its names coloured)."""
    palette = _palette(config)
    named: set[int] = set()  # settlements the chronicle has already named

    def name_color(kind: str, ref: int) -> RGB:
        if kind in (REF_REALM, REF_RULER):
            return world.realms[ref].color
        if kind == REF_FALLEN:
            return world.fallen_realms[ref].color
        if kind == REF_FEATURE:
            return palette["place"]
        assert kind == REF_POI
        first = ref not in named
        named.add(ref)
        realm = world.pois[ref].realm_id
        return palette["settlement"] if first or realm < 0 else world.realms[realm].color

    document: Document = [[Span(chronicle_title(world), bold=True)], []]
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
        document.append(row)
    return document

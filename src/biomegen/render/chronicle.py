"""The chronicle as a coloured document: year, event type and text in three columns.

The event type takes its colour from ``history.colors``; a name in the text is coloured by what it names: a realm in its
own colour from the political map (lifted if too dark to read), a settlement, fallen realm or ruler in the fixed colour
of its kind. The plain text of the document equals :func:`biomegen.world.chronicle.chronicle_text`.
"""

from __future__ import annotations

from ..config.model import Config
from ..world.chronicle import KIND_WIDTH, chronicle_title
from ..world.world import World
from .grid import RGB, Document, Span

_MIN_LUMA = 130.0  # a realm colour darker than this is mixed with white until it reaches it


def legible(color: tuple[int, int, int]) -> RGB:
    """Return ``color``, or the nearest lighter mix of it with white that reads on a dark background."""
    red, green, blue = color
    luma = 0.299 * red + 0.587 * green + 0.114 * blue
    if luma >= _MIN_LUMA:
        return (red, green, blue)
    mix = (_MIN_LUMA - luma) / (255.0 - luma)
    return (round(red + (255 - red) * mix), round(green + (255 - green) * mix), round(blue + (255 - blue) * mix))


def _palette(config: Config) -> dict[str, RGB]:
    """The ``history.colors`` entries as RGB triples."""
    return {name: (int(c[0]), int(c[1]), int(c[2])) for name, c in config.get("history.colors").items()}


def chronicle_document(world: World, config: Config) -> Document:
    """Return the title and every event as rows of styled spans (year, kind, then the text with its names coloured)."""
    palette = _palette(config)
    realm_colors = {realm.id: legible(realm.color) for realm in world.realms}

    def name_color(kind: str, ref: int) -> RGB:
        return realm_colors[ref] if kind == "realm" else palette[kind]

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

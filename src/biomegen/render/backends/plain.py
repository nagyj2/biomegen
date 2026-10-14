"""Plain-text back-end: the glyphs of a document with no colour, trailing blanks trimmed."""

from __future__ import annotations

from ..grid import Document


def to_plain(document: Document) -> str:
    """Return the document's text, one line per row, with trailing whitespace removed."""
    return "\n".join("".join(span.text for span in row).rstrip() for row in document)

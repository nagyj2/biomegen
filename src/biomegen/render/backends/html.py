"""HTML back-end: a document as a self-contained page of coloured spans."""

from __future__ import annotations

import html

from ..grid import RGB, Document

_PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'><title>{title}</title></head>"
    "<body style='background:#111;color:#ddd;margin:16px'>"
    "<pre style=\"font-family:'DejaVu Sans Mono',Menlo,Consolas,monospace;font-size:13px;"
    'line-height:1.15">{rows}</pre></body></html>'
)


def _hex(color: RGB) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def to_html(document: Document, title: str) -> str:
    """Return the document as a standalone HTML page titled ``title``."""
    rows = []
    for row in document:
        parts = []
        for span in row:
            style = []
            if span.fg is not None:
                style.append(f"color:{_hex(span.fg)}")
            if span.bg is not None:
                style.append(f"background:{_hex(span.bg)}")
            if span.bold:
                style.append("font-weight:bold")
            text = html.escape(span.text)
            parts.append(f'<span style="{";".join(style)}">{text}</span>' if style else text)
        rows.append("".join(parts))
    return _PAGE.format(title=html.escape(title), rows="\n".join(rows))

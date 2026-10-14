"""Tests for the ANSI, plain and HTML back-ends."""

from __future__ import annotations

import re

import pytest

from biomegen.render.backends.ansi import rgb_to_256, to_ansi
from biomegen.render.backends.html import to_html
from biomegen.render.backends.plain import to_plain
from biomegen.render.grid import CellGrid, Span

ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _document() -> list[list[Span]]:
    return [
        [Span("ab", (255, 0, 0), (0, 0, 255), True), Span("c  ", (1, 2, 3), None)],
        [Span("  ")],
    ]


def test_plain_joins_spans_and_trims_trailing_blanks() -> None:
    assert to_plain(_document()) == "abc\n"


def test_ansi_stripped_of_escapes_equals_plain() -> None:
    # Back-end parity: colour adds escapes and nothing else.
    stripped = ESCAPE.sub("", to_ansi(_document()))
    assert "\n".join(line.rstrip() for line in stripped.split("\n")) == to_plain(_document())


def test_truecolor_uses_24_bit_codes() -> None:
    assert "38;2;255;0;0" in to_ansi(_document(), "truecolor") and "48;2;0;0;255" in to_ansi(_document(), "truecolor")


def test_256_mode_uses_palette_indices() -> None:
    assert "38;5;" in to_ansi(_document(), "256") and "38;2;" not in to_ansi(_document(), "256")


def test_ansi_emits_style_only_where_it_changes() -> None:
    document = [[Span("a", (1, 1, 1)), Span("b", (1, 1, 1)), Span("c", (2, 2, 2))]]
    assert to_ansi(document).count("38;2;") == 2


def test_every_ansi_line_ends_with_a_reset() -> None:
    assert all(line.endswith("\x1b[0m") for line in to_ansi(_document()).split("\n"))


def test_unknown_colour_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="colour mode"):
        to_ansi(_document(), "16")


def test_near_greys_map_to_the_grey_ramp() -> None:
    assert 232 <= rgb_to_256((128, 130, 126)) <= 255


def test_html_escapes_text_and_styles_spans() -> None:
    page = to_html([[Span("<a>", (255, 0, 0), None, True)]], "T & T")
    assert "&lt;a&gt;" in page and "color:#ff0000" in page and "font-weight:bold" in page and "T &amp; T" in page


def test_grid_document_round_trips_through_plain() -> None:
    grid = CellGrid(1, 3)
    grid.glyph[0] = list("hi!")
    assert to_plain(grid.to_document()) == "hi!"

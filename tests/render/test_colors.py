"""Tests for the colour maths and table-driven style lookups."""

from __future__ import annotations

import numpy as np

from biomegen.config import load_config
from biomegen.render.colors import biome_style, mix_colors, ramp_colors, relief_style, scale_colors
from biomegen.world.tile import Biome, Relief


def test_scale_colors_clamps_to_the_byte_range() -> None:
    assert scale_colors((200, 100, 10), 2.0).tolist() == [255, 200, 20]


def test_mix_colors_blends_per_cell() -> None:
    mixed = mix_colors(np.zeros((2, 3)), np.full((2, 3), 100.0), np.array([0.0, 0.5]))
    assert mixed.tolist() == [[0, 0, 0], [50, 50, 50]]


def test_ramp_colors_interpolates_between_stops() -> None:
    stops = [[0, [0, 0, 0]], [10, [100, 200, 50]]]
    assert ramp_colors(stops, np.array([5.0])).tolist() == [[50, 100, 25]]


def test_ramp_colors_holds_the_end_colours_outside_the_range() -> None:
    stops = [[0, [0, 0, 0]], [10, [100, 200, 50]]]
    assert ramp_colors(stops, np.array([-5.0, 99.0])).tolist() == [[0, 0, 0], [100, 200, 50]]


def test_biome_style_reads_the_table_row() -> None:
    config = load_config(None)
    row = config.get("tables.biomes.deep")
    style = biome_style(config)
    assert style.bg[int(Biome.DEEP)].tolist() == list(row["bg"]) and bool(style.water[int(Biome.DEEP)])


def test_ascii_style_uses_the_ascii_column() -> None:
    config = load_config(None)
    assert biome_style(config, ascii_only=True).glyph[int(Biome.FOREST)] == config.get("tables.biomes.forest.ascii")


def test_relief_none_has_a_blank_glyph() -> None:
    assert relief_style(load_config(None)).glyph[int(Relief.NONE)] == " "


def test_every_interior_cell_has_a_glyph_and_a_colour() -> None:
    # A new Cell value needs an entry in render.interior_glyphs and (unless void) render.interior_palette.
    from biomegen.config import load_config
    from biomegen.render.colors import interior_style
    from biomegen.world.tile import Cell

    style = interior_style(load_config(None))
    drawn = [int(cell) for cell in Cell if cell not in (Cell.VOID, Cell.RESERVED)]
    assert all(str(style.glyph[cell]) != "?" for cell in drawn) and all(style.bg[cell].any() for cell in drawn)


def test_ascii_interior_glyphs_are_7_bit() -> None:
    from biomegen.config import load_config
    from biomegen.render.colors import interior_style

    assert all(ord(glyph) < 128 for glyph in interior_style(load_config(None), True).glyph)


def test_the_wall_line_table_has_a_glyph_for_every_neighbour_mask() -> None:
    from biomegen.config import load_config
    from biomegen.render.colors import wall_glyph_table

    config = load_config(None)
    assert len(wall_glyph_table(config, False)) == 16 and all(ord(g) < 128 for g in wall_glyph_table(config, True))


def test_subtle_clutter_is_the_floor_colour_with_a_faint_glyph() -> None:
    # Rubble is filled like the floor and its glyph is only a little brighter than the fill.
    from biomegen.config import load_config
    from biomegen.render.colors import interior_style
    from biomegen.world.tile import Cell

    style = interior_style(load_config(None))
    rubble, floor = int(Cell.RUBBLE), int(Cell.FLOOR)
    assert (style.bg[rubble] == style.bg[floor]).all() and (style.fg[rubble] < style.fg[floor]).all()


def test_style_tables_are_built_once_and_read_only() -> None:
    # Every frame asks for the tables; they are built once per config, and no caller can change them.
    config = load_config(None)
    style = biome_style(config)
    assert biome_style(config) is style and not style.bg.flags.writeable

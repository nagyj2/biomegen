"""Tests for the interiors layer: POI plans stamped into their footprint at the detail scales."""

from __future__ import annotations

import numpy as np

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.interiors import build_interior, sample_rect, sample_rect_array
from biomegen.render.detail import SCALE_LOCAL, SCALE_ZOOM, DetailSampler
from biomegen.render.layers import build_grid
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.entities import POI
from biomegen.world.overlay import Overlay
from biomegen.world.tile import Biome, Cell, WaterType
from tests.render.conftest import make_world

WITH = View("t", ("terrain", "interiors"))
WITHOUT = View("t", ("terrain",))
ZOOM_CELLS = (10, 5)
LOCAL_CELLS = (18, 9)


def _crisp_config() -> Config:
    config = load_config(None)
    config.data["render"]["blend_strength"] = 0.0
    return config


def _world(kind: str = "tower", biome: Biome = Biome.GRASS):
    """A 10 x 10 world with one 3 x 3 tile POI of ``kind`` at (5, 5) (footprint tiles 4-6)."""
    world = make_world(10, 10, biome)
    floors = 2 if kind == "tower" else 1
    world.pois.append(POI(kind=kind, x=5, y=5, interior_seed=11, footprint=(3, 3), floor_count=floors))
    return world


def _draw(world, view=WITH, scale=SCALE_LOCAL, config=None, **kwargs):
    config = config or _crisp_config()
    cells = LOCAL_CELLS if scale == SCALE_LOCAL else ZOOM_CELLS
    sampler = DetailSampler(world, config, cells[0], cells[1], 0, 0, 10, 10, scale)
    return build_grid(world, config, view, sampler, **kwargs), sampler, config


def _footprint(sampler):
    """The (rows, cols) slices of the 3 x 3 tile footprint whose top-left tile is (4, 4)."""
    return (
        slice(4 * sampler.cell_h, 7 * sampler.cell_h),
        slice(4 * sampler.cell_w, 7 * sampler.cell_w),
    )


def test_sample_rect_array_matches_sample_rect() -> None:
    # The vectorised sampler maps the plan exactly as the generator-based one, including an off-screen start.
    plan = np.arange(36, dtype=np.uint8).reshape(6, 6)
    expected = {(r, c): v for r, c, v in sample_rect(plan, -2, 3, 9, 8, 7, 10)}
    rows, cols, values = sample_rect_array(plan, -2, 3, 9, 8, 7, 10)
    got = {
        (r, c): int(values[r - rows.start, c - cols.start])
        for r in range(rows.start, rows.stop)
        for c in range(cols.start, cols.stop)
    }
    assert got == expected


def test_sample_rect_array_misses_an_off_screen_rect() -> None:
    assert sample_rect_array(np.zeros((4, 4), dtype=np.uint8), 20, 0, 4, 4, 10, 10) is None


def test_interior_walls_are_drawn_in_the_footprint() -> None:
    grid, sampler, config = _draw(_world())
    assert config.get("render.interior_glyphs.wall") in grid.glyph[_footprint(sampler)]


def test_cells_outside_the_footprint_are_untouched() -> None:
    with_layer, sampler, _ = _draw(_world())
    without, _, _ = _draw(_world(), WITHOUT)
    outside = np.ones(with_layer.glyph.shape, dtype=bool)
    outside[_footprint(sampler)] = False
    assert (with_layer.glyph[outside] == without.glyph[outside]).all()


def test_void_cells_let_the_terrain_show_through() -> None:
    # VOID cells of the plan keep the terrain glyph and fill.
    world = _world("camp")
    grid, sampler, config = _draw(world)
    plain, _, _ = _draw(world, WITHOUT)
    plan = build_interior(world.pois[0], 0, config, world)
    rows, cols, cells = sample_rect_array(
        plan, 4 * sampler.cell_h, 4 * sampler.cell_w, 3 * sampler.cell_h, 3 * sampler.cell_w, sampler.rows, sampler.cols
    )
    void = cells == int(Cell.VOID)
    assert void.any() and (grid.glyph[rows, cols][void] == plain.glyph[rows, cols][void]).all()


def test_zoom_hides_furniture_that_local_shows() -> None:
    # A tower has tables and chests; zoom draws bare floor in their place, local draws them.
    zoom, _, config = _draw(_world(), scale=SCALE_ZOOM)
    local, _, _ = _draw(_world())
    furniture = {config.get("render.interior_glyphs.table"), config.get("render.interior_glyphs.chest")}
    assert (furniture & set(np.unique(zoom.glyph)), bool(furniture & set(np.unique(local.glyph)))) == (set(), True)


def test_floor_selects_which_level_of_a_tower_is_drawn() -> None:
    ground, _, _ = _draw(_world(), floor=0)
    upper, _, _ = _draw(_world(), floor=1)
    assert not (ground.glyph == upper.glyph).all()


def test_floor_is_clamped_to_the_towers_floors() -> None:
    top, _, _ = _draw(_world(), floor=1)
    beyond, _, _ = _draw(_world(), floor=9)
    assert (top.glyph == beyond.glyph).all()


def test_structure_is_not_laid_over_water() -> None:
    # Tiles of the footprint that are water keep the water drawing, whatever the plan says there.
    world = _world("camp")
    world.biome[5, 5] = int(Biome.LAKE)
    world.water_type[5, 5] = int(WaterType.FRESH)
    grid, sampler, _ = _draw(world)
    plain, _, _ = _draw(world, WITHOUT)
    block = (slice(5 * sampler.cell_h, 6 * sampler.cell_h), slice(5 * sampler.cell_w, 6 * sampler.cell_w))
    assert (grid.glyph[block] == plain.glyph[block]).all()


def test_boat_floats_on_water() -> None:
    # A boat is exempt from the water guard: its hull is drawn over the sea.
    world = _world("boat", Biome.SHALLOW)
    world.water_type[:] = int(WaterType.SALT)
    grid, sampler, config = _draw(world)
    assert config.get("render.interior_glyphs.wall") in grid.glyph[_footprint(sampler)]


def test_overlay_interior_edit_shows_in_the_drawing() -> None:
    # A chest placed on a floor cell of a camp appears; the camp has none of its own.
    world = _world("camp")
    config = _crisp_config()
    plan = build_interior(world.pois[0], 0, config, world)
    y, x = (int(v[0]) for v in np.nonzero(plan == int(Cell.FLOOR)))
    overlay = Overlay()
    overlay.set_interior(11, 0, x, y, int(Cell.CHEST))
    chest = config.get("render.interior_glyphs.chest")
    edited, _, _ = _draw(world, config=config, overlay=overlay)
    plain, _, _ = _draw(world, config=config)
    assert (chest in edited.glyph, chest in plain.glyph) == (True, False)


def test_interior_fill_is_the_palette_colour() -> None:
    grid, sampler, config = _draw(_world())
    wall = config.get("render.interior_palette.wall")
    assert (grid.bg[_footprint(sampler)] == np.asarray(wall, dtype=np.uint8)).all(axis=-1).any()


def test_map_scale_draws_no_interiors() -> None:
    world = _world()
    config = _crisp_config()
    with_layer = build_grid(world, config, WITH, Sampler.viewport(world, 10, 10))
    without = build_grid(world, config, WITHOUT, Sampler.viewport(world, 10, 10))
    assert (with_layer.glyph == without.glyph).all()

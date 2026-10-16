"""Tests for the sites layer: POI plans drawn into their extent at every scale."""

from __future__ import annotations

import numpy as np

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.layers import build_grid
from biomegen.render.views import View
from biomegen.sampling.detail import SCALE_LOCAL, SCALE_SITE, SCALE_ZOOM, DetailSampler
from biomegen.sampling.sampler import Sampler
from biomegen.sites import site_geometry, site_plan, window_sampler
from biomegen.world.entities import POI
from biomegen.world.overlay import Overlay
from biomegen.world.tile import Biome, Cell, WaterType
from tests.render.conftest import make_world

WITH = View("t", ("terrain", "sites"))
WITHOUT = View("t", ("terrain",))
ZOOM_CELLS = (10, 5)
LOCAL_CELLS = (18, 9)
WORLD = 10


def _crisp_config() -> Config:
    config = load_config(None)
    config.data["render"]["blend_strength"] = 0.0
    config.data["sites"]["size_jitter"] = 0.0
    return config


def _world(kind: str = "dungeon", biome: Biome = Biome.GRASS):
    """A 10 x 10 world with one POI of ``kind`` at (5, 5); a dungeon is 1.5 x 1.0 tiles, a camp half a tile."""
    world = make_world(WORLD, WORLD, biome)
    floors = {"dungeon": 2, "tower": 2}.get(kind, 1)
    lowest = -(floors - 1) if kind == "dungeon" else 0
    world.pois.append(POI(kind=kind, x=5, y=5, interior_seed=11, floor_count=floors, lowest_floor=lowest, pop=800))
    return world


def _draw(world, view=WITH, scale=SCALE_LOCAL, config=None, **kwargs):
    config = config or _crisp_config()
    cells = LOCAL_CELLS if scale == SCALE_LOCAL else ZOOM_CELLS
    sampler = DetailSampler(world, config, cells[0], cells[1], 0, 0, WORLD, WORLD, scale)
    return build_grid(world, config, view, sampler, **kwargs), sampler, config


def _draw_inside(world, config=None, **kwargs):
    """Draw the whole site window of the first POI at the site scale (floors and overlay edits show here)."""
    config = config or _crisp_config()
    geometry = site_geometry(world.pois[0], config)
    sampler = window_sampler(world, config, geometry)
    return build_grid(world, config, WITH, sampler, **kwargs), sampler, config


def _extent(sampler, world, config):
    """The (rows, cols) slices of the grid under the first POI's extent."""
    left, top, right, bottom = site_geometry(world.pois[0], config).extent
    col0, col1 = round((left + 0.5) * sampler.cell_w), round((right + 0.5) * sampler.cell_w)
    row0, row1 = round((top + 0.5) * sampler.cell_h), round((bottom + 0.5) * sampler.cell_h)
    return slice(row0, row1), slice(col0, col1)


def test_a_building_is_a_roof_seen_from_outside() -> None:
    world = _world()
    grid, sampler, config = _draw(world)
    # A dungeon's gatehouse is seen as its own roof, not a house roof.
    assert config.get("render.interior_glyphs.dungeon_roof") in grid.glyph[_extent(sampler, world, config)]


def test_cells_outside_the_extent_are_untouched() -> None:
    world = _world()
    with_layer, sampler, config = _draw(world)
    without, _, _ = _draw(world, WITHOUT)
    outside = np.ones(with_layer.glyph.shape, dtype=bool)
    outside[_extent(sampler, world, config)] = False
    assert (with_layer.glyph[outside] == without.glyph[outside]).all()


def test_void_cells_let_the_terrain_show_through() -> None:
    # Void cells of the plan keep the terrain glyph and fill.
    world = _world("camp")
    grid, sampler, config = _draw(world)
    plain, _, _ = _draw(world, WITHOUT)
    rows, cols = _extent(sampler, world, config)
    plan = site_plan(world.pois[0], 0, config, world)
    assert plan is not None and (plan.cells == int(Cell.VOID)).any()
    kept = grid.glyph[rows, cols] == plain.glyph[rows, cols]
    assert kept.any()


def test_furniture_is_seen_only_at_the_site_scale() -> None:
    # A tower has furniture inside; zoom and local show its roof, only the site view shows what is in it.
    world = _world("tower")
    config = _crisp_config()
    furniture = {config.get(f"render.interior_glyphs.{name}") for name in ("table", "chest", "shelf", "bed", "chair")}
    zoom, _, _ = _draw(world, scale=SCALE_ZOOM)
    local, _, _ = _draw(world)
    site, _, _ = _draw_inside(world)
    seen = [bool(furniture & set(np.unique(grid.glyph))) for grid in (zoom, local, site)]
    assert seen == [False, False, True]


def test_floor_selects_which_level_of_a_dungeon_is_drawn() -> None:
    world = _world()
    ground, _, _ = _draw_inside(world, floor=0)
    below, _, _ = _draw_inside(world, floor=-1)
    assert not (ground.glyph == below.glyph).all()


def test_floor_is_clamped_to_the_dungeons_floors() -> None:
    world = _world()
    bottom, _, _ = _draw_inside(world, floor=-1)
    beyond, _, _ = _draw_inside(world, floor=-9)
    assert (bottom.glyph == beyond.glyph).all()


def test_outside_views_show_the_surface_whatever_the_floor() -> None:
    world = _world()
    ground, _, _ = _draw(world, floor=0)
    below, _, _ = _draw(world, floor=-1)
    assert (ground.glyph == below.glyph).all()


def test_a_structure_is_not_laid_over_water() -> None:
    # A lake beside the dungeon: no wall or floor of the plan is drawn on the lake's cells.
    world = _world()
    world.biome[:, 6:] = int(Biome.LAKE)
    world.water_type[:, 6:] = int(WaterType.FRESH)
    grid, sampler, config = _draw(world)
    plain, _, _ = _draw(world, WITHOUT)
    lake = sampler.fx >= 6.0
    assert (grid.glyph[lake] == plain.glyph[lake]).all()


def test_a_boat_floats_on_water() -> None:
    world = _world("boat", Biome.SHALLOW)
    world.water_type[:] = int(WaterType.SALT)
    grid, sampler, config = _draw(world)
    assert config.get("render.interior_glyphs.hull") in grid.glyph[_extent(sampler, world, config)]


def test_an_overlay_edit_shows_in_the_drawing() -> None:
    # Chests placed over every floor cell of a camp appear (the plan is finer than the view, so one cell may not);
    # the camp has none of its own.
    world = _world("camp")
    config = _crisp_config()
    plan = site_plan(world.pois[0], 0, config, world)
    assert plan is not None
    overlay = Overlay()
    for y, x in np.argwhere(plan.cells == int(Cell.FLOOR)).tolist():
        overlay.set_interior(11, 0, x, y, int(Cell.CHEST))
    chest = config.get("render.interior_glyphs.chest")
    edited, _, _ = _draw_inside(world, config=config, overlay=overlay)
    plain, _, _ = _draw_inside(world, config=config)
    assert (chest in edited.glyph, chest in plain.glyph) == (True, False)


def test_the_overlay_does_not_change_the_cached_plan() -> None:
    world = _world("camp")
    config = _crisp_config()
    plan = site_plan(world.pois[0], 0, config, world)
    assert plan is not None
    before = plan.cells.copy()
    overlay = Overlay()
    overlay.set_interior(11, 0, 1, 1, int(Cell.CHEST))
    _draw(world, config=config, overlay=overlay)
    assert np.array_equal(site_plan(world.pois[0], 0, config, world).cells, before)  # type: ignore[union-attr]


def test_the_fill_is_the_palette_colour() -> None:
    world = _world()
    grid, sampler, config = _draw(world)
    roof = config.get("render.interior_palette.dungeon_roof")
    assert (grid.bg[_extent(sampler, world, config)] == np.asarray(roof, dtype=np.uint8)).all(axis=-1).any()


def test_the_map_scale_draws_no_plan() -> None:
    # A POI is a single marker tile on the world map: the sites layer changes no cell there.
    world = _world()
    config = _crisp_config()
    with_layer = build_grid(world, config, WITH, Sampler.viewport(world, WORLD, WORLD))
    without = build_grid(world, config, WITHOUT, Sampler.viewport(world, WORLD, WORLD))
    assert np.array_equal(with_layer.glyph, without.glyph)


def test_the_site_scale_draws_the_whole_window_one_plan_cell_per_cell() -> None:
    # At the site scale a sampler over the window shows the plan cell for cell; thin walls join into line glyphs.
    world = _world()
    config = _crisp_config()
    geometry = site_geometry(world.pois[0], config)
    plan = site_plan(world.pois[0], 0, config, world)
    assert geometry is not None and plan is not None
    sampler = window_sampler(world, config, geometry)
    grid = build_grid(world, config, WITH, sampler)
    walls = plan.window_cells() == int(Cell.WALL)
    lines = set(config.get("render.interior_walls.glyphs"))
    assert sampler.scale == SCALE_SITE and walls.any() and set(np.unique(grid.glyph[walls])) <= lines


def test_a_horizontal_wall_run_draws_as_a_line() -> None:
    world = _world("camp")
    config = _crisp_config()
    plan = site_plan(world.pois[0], 0, config, world)
    assert plan is not None
    cells = np.zeros((5, 9), dtype=np.uint8)
    cells[2, 2:7] = int(Cell.WALL)
    from biomegen.sites import wall_index

    index = wall_index(cells)
    assert int(index[2, 4]) == 10 and int(index[2, 2]) == 2 and int(index[0, 0]) == 255


def test_the_road_runs_on_through_the_site() -> None:
    # The world's road crosses the dungeon's tile: the plan leaves the road's cells void, so the bed shows inside it.
    road_view = View("t", ("terrain", "roads", "sites"))
    world = _world()
    world.road[5, 3:8] = 1
    config = _crisp_config()
    grid, sampler, _ = _draw(world, road_view, config=config)
    rows, cols = _extent(sampler, world, config)
    road_bg = np.asarray(config.get("render.detail_colors.road_bg"), dtype=np.uint8)
    assert (grid.bg[rows, cols] == road_bg).all(axis=-1).any()


def test_a_site_keeps_its_own_colours_under_a_data_tint() -> None:
    # The tint colours the ground round a plan; the plan's cells keep the colours they have in an untinted view.
    world = _world("dungeon")
    config = _crisp_config()
    tinted = View("t", ("terrain", "tint", "sites"), "elevation")
    bare = View("t", ("terrain", "tint"), "elevation")
    with_site, _, _ = _draw(world, tinted, config=config)
    without_site, _, _ = _draw(world, bare, config=config)
    plain, _, _ = _draw(world, WITH, config=config)
    plan = (with_site.bg != without_site.bg).any(axis=2)
    assert plan.any() and (with_site.bg[plan] == plain.bg[plan]).all()


def test_the_site_scale_draws_every_plan_row_exactly_once() -> None:
    # At the site scale the grid has the site's own cell size, so the extent must cover exactly the plan's box: a box a
    # row taller (a rounding mismatch) repeats a plan row, such as the top wall of a building. Sizes vary with the seed.
    from biomegen.render.layers.sites import _extent_cells

    config = load_config(None)
    for seed in range(1, 41):
        world = make_world(WORLD, WORLD, Biome.GRASS)
        world.pois.append(POI(kind="homestead", x=5, y=5, interior_seed=seed, style="lodge"))
        poi = world.pois[0]
        geometry = site_geometry(poi, config)
        sampler = window_sampler(world, config, geometry)
        plan = site_plan(poi, 0, config, world)
        assert geometry is not None and plan is not None
        _row0, _col0, rows, cols = _extent_cells(sampler, geometry)
        assert (rows, cols) == plan.cells.shape, seed

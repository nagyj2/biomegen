"""Tests for roads and bridges at the detail scales."""

from __future__ import annotations

import numpy as np

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.layers import build_grid
from biomegen.render.views import View
from biomegen.sampling.detail import SCALE_LOCAL, DetailSampler
from biomegen.sampling.sampler import Sampler
from biomegen.world.entities import POI
from biomegen.world.tile import Biome
from tests.render.conftest import make_world

ROADS = View("t", ("terrain", "roads"))
BRIDGES = View("t", ("terrain", "bridges"))


def _crisp_config(**render) -> Config:
    """A config with the biome warp and road wobble off, so blocks line up with the tile grid."""
    config = load_config(None)
    config.data["render"].update({"blend_strength": 0.0, "road_warp": 0.0, **render})
    return config


def _draw(world, view, config=None, cell=(10, 5), scale="zoom"):
    config = config or _crisp_config()
    sampler = DetailSampler(world, config, cell[0], cell[1], 0, 0, world.width, world.height, scale)
    return build_grid(world, config, view, sampler), sampler, config


def _is_color(grid, color) -> np.ndarray:
    return (grid.bg == np.asarray(color, dtype=np.uint8)).all(axis=-1)


def _bridge_world(lake_column: bool = False):
    world = make_world(5, 3, Biome.GRASS)
    if lake_column:
        world.biome[:, 2] = int(Biome.LAKE)
        world.elevation_m[:, 2] = -10.0
    world.pois.append(POI(kind="bridge", x=2, y=1, interior_seed=0, extra={"p0": [1, 1], "p1": [3, 1]}))
    return world


def test_straight_road_is_a_bed_a_fraction_of_a_tile_wide() -> None:
    # A road along tile row 1 with half width 0.3 covers the three cell rows within 0.3 tiles of its centre line.
    world = make_world(5, 3, Biome.GRASS)
    world.road[1, :] = 1
    grid, _, config = _draw(world, ROADS)
    rows = np.nonzero(_is_color(grid, config.get("render.detail_colors.road_bg"))[:, 25])[0].tolist()
    assert rows == [6, 7, 8]


def test_diagonal_road_link_is_continuous() -> None:
    # Two road tiles touching at a corner are joined: the cell between their centres is bed.
    world = make_world(2, 2, Biome.GRASS)
    world.road[0, 0] = world.road[1, 1] = 1
    grid, _, config = _draw(world, ROADS)
    assert _is_color(grid, config.get("render.detail_colors.road_bg"))[4, 9]


def test_road_bed_stops_at_water() -> None:
    # A wide bed beside a lake never paints lake cells.
    world = make_world(3, 3, Biome.GRASS)
    world.biome[:, 2] = int(Biome.LAKE)
    world.elevation_m[:, 2] = -10.0
    world.road[1, 1] = 1
    grid, sampler, config = _draw(world, ROADS, _crisp_config(road_half_width=0.8))
    lake_cells = sampler.fx >= 1.6
    assert not (_is_color(grid, config.get("render.detail_colors.road_bg")) & lake_cells).any()


def test_zero_half_width_draws_no_road() -> None:
    world = make_world(5, 3, Biome.GRASS)
    world.road[1, :] = 1
    grid, _, config = _draw(world, ROADS, _crisp_config(road_half_width=0.0))
    assert not _is_color(grid, config.get("render.detail_colors.road_bg")).any()


def test_zoom_and_local_draw_the_same_bed() -> None:
    # Cell c of a 10 x 5 grid and cell 3c+1 of a 30 x 15 grid share a world position, so with the default
    # warp the road bed there must agree: the wobble is a function of position, not of scale.
    world = make_world(6, 4, Biome.GRASS)
    world.road[1, :] = 1
    world.road[:, 3] = 1
    config = load_config(None)
    zoom, _, _ = _draw(world, ROADS, config, cell=(10, 5))
    local, _, _ = _draw(world, ROADS, config, cell=(30, 15), scale=SCALE_LOCAL)
    road_bg = config.get("render.detail_colors.road_bg")
    assert (_is_color(local, road_bg)[1::3, 1::3] == _is_color(zoom, road_bg)).all()


def test_local_scale_adds_fine_clutter_to_the_bed() -> None:
    # road_clutter_local glyphs appear along the bed at local scale only.
    world = make_world(12, 3, Biome.GRASS)
    world.road[1, :] = 1
    zoom, _, _ = _draw(world, ROADS, cell=(30, 15))
    local, _, _ = _draw(world, ROADS, cell=(30, 15), scale=SCALE_LOCAL)
    fine = {'"', ";"}
    assert (fine & set(np.unique(local.glyph)), fine & set(np.unique(zoom.glyph))) == ({'"', ";"}, set())


def test_bridge_deck_runs_between_its_span_ends() -> None:
    # A bridge from tile (1, 1) to (3, 1) paints three deck rows across the middle column.
    grid, _, config = _draw(_bridge_world(), BRIDGES)
    rows = np.nonzero(_is_color(grid, config.get("render.detail_colors.deck_bg"))[:, 25])[0].tolist()
    assert rows == [6, 7, 8]


def test_bridge_walls_flank_the_deck() -> None:
    grid, _, config = _draw(_bridge_world(), BRIDGES)
    wall = _is_color(grid, config.get("render.detail_colors.wall_bg"))
    assert wall[5, 25] and wall[9, 25]


def test_bridge_is_drawn_over_the_water_it_spans() -> None:
    # The deck replaces the lake's wave glyph in the cell at the middle of the span.
    grid, _, config = _draw(_bridge_world(lake_column=True), BRIDGES)
    assert grid.glyph[7, 25] == config.get("render.bridge_glyphs.deck")


def test_bridge_layer_draws_nothing_at_map_scale() -> None:
    # At map scale a bridge is a marker; the detail-only layer must leave the map untouched.
    world = _bridge_world()
    config = _crisp_config()
    with_layer = build_grid(world, config, BRIDGES, Sampler.viewport(world, 3, 5))
    without = build_grid(world, config, View("t", ("terrain",)), Sampler.viewport(world, 3, 5))
    assert (with_layer.glyph == without.glyph).all() and (with_layer.bg == without.bg).all()


def _bed_glyphs(grid, config) -> set[str]:
    return {str(g) for g in grid.glyph[_is_color(grid, config.get("render.detail_colors.road_bg"))]}


def test_diagonal_bed_is_drawn_with_slashes_not_colons() -> None:
    # A rising run of road tiles gets the rising-line glyph along its bed.
    world = make_world(4, 4, Biome.GRASS)
    world.road[3, 0] = world.road[2, 1] = world.road[1, 2] = world.road[0, 3] = 1
    grid, _, config = _draw(world, ROADS)
    assert "╱" in _bed_glyphs(grid, config) and ":" not in _bed_glyphs(grid, config)


def test_straight_bed_uses_the_horizontal_glyph() -> None:
    world = make_world(5, 3, Biome.GRASS)
    world.road[1, :] = 1
    grid, _, config = _draw(world, ROADS, _crisp_config(road_clutter={"glyphs": [], "density": 0.0}))
    assert _bed_glyphs(grid, config) == {"─"}


def test_ascii_bed_uses_ascii_glyphs() -> None:
    world = make_world(4, 4, Biome.GRASS)
    world.road[0, 0] = world.road[1, 1] = world.road[2, 2] = world.road[3, 3] = 1
    config = _crisp_config(road_clutter={"glyphs": [], "density": 0.0})
    sampler = DetailSampler(world, config, 10, 5, 0, 0, world.width, world.height, "zoom")
    grid = build_grid(world, config, ROADS, sampler, ascii_only=True)
    assert _bed_glyphs(grid, config) == {"\\"}

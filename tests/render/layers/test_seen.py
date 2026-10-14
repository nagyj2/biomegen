"""Tests for the record of what a draw put on screen (the explorer's legend source)."""

from __future__ import annotations

from biomegen.render.detail import DetailSampler
from biomegen.render.layers import Seen, build_grid
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, Cell
from tests.render.conftest import make_world

TERRAIN = View("t", ("terrain",))
INTERIORS = View("t", ("terrain", "interiors"))


def test_seen_lists_the_biomes_under_the_cells(config) -> None:
    world = make_world(4, 2, Biome.GRASS)
    world.biome[0, 0] = int(Biome.LAKE)
    seen = Seen()
    build_grid(world, config, TERRAIN, Sampler.viewport(world, 2, 4), seen=seen)
    assert seen.biomes == {int(Biome.GRASS), int(Biome.LAKE)}


def test_seen_ignores_cells_outside_the_world(config) -> None:
    world = make_world(2, 2, Biome.GRASS)
    seen = Seen()
    build_grid(world, config, TERRAIN, Sampler.viewport(world, 2, 5), seen=seen)
    assert seen.biomes == {int(Biome.GRASS)}


def test_seen_lists_the_interior_cells_drawn_at_detail_scale(config) -> None:
    world = make_world(10, 10, Biome.GRASS)
    world.pois.append(POI(kind="tower", x=5, y=5, interior_seed=11, footprint=(3, 3), floor_count=2))
    seen = Seen()
    build_grid(world, config, INTERIORS, DetailSampler(world, config, 18, 9, 0, 0, 10, 10, "local"), seen=seen)
    assert int(Cell.WALL) in seen.cells and int(Cell.VOID) not in seen.cells


def test_seen_is_empty_of_cells_without_structures(config) -> None:
    world = make_world(4, 4, Biome.GRASS)
    seen = Seen()
    build_grid(world, config, INTERIORS, Sampler.viewport(world, 4, 4), seen=seen)
    assert seen.cells == set()

"""Tests for the render surface helper: rivers draw as lake water, everything else as its biome."""

from __future__ import annotations

import numpy as np

from biomegen.render.surface import display_biome, display_biome_at, river_mask
from biomegen.world.tile import Biome, WaterType
from biomegen.world.world import World


def _world() -> World:
    """Grass with one river cell (fresh water over grass) and one lake cell."""
    world = World(4, 3, 1)
    world.biome[:] = int(Biome.GRASS)
    world.water_type[:] = int(WaterType.NONE)
    world.water_type[1, 1] = int(WaterType.FRESH)
    world.biome[1, 3] = int(Biome.LAKE)
    world.water_type[1, 3] = int(WaterType.FRESH)
    return world


def test_river_mask_is_fresh_water_over_land_only() -> None:
    mask = river_mask(_world())
    assert mask[1, 1] and int(mask.sum()) == 1


def test_display_biome_draws_rivers_as_lake() -> None:
    shown = display_biome(_world())
    assert int(shown[1, 1]) == int(Biome.LAKE) and int(shown[0, 0]) == int(Biome.GRASS)


def test_display_biome_leaves_the_world_unchanged() -> None:
    world = _world()
    display_biome(world)
    assert int(world.biome[1, 1]) == int(Biome.GRASS)


def test_scalar_and_array_forms_agree() -> None:
    world = _world()
    shown = display_biome(world)
    assert all(display_biome_at(world, x, y) == int(shown[y, x]) for y in range(3) for x in range(4))


def test_display_biome_keeps_dtype() -> None:
    assert display_biome(_world()).dtype == np.uint8

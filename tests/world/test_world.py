"""Tests for the World container: per-tile fields and km scale metadata."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.util.units import grid_scale
from biomegen.world.tile import Relief
from biomegen.world.world import World

PHYSICAL_FIELDS = ("elevation_m", "temperature_c", "rain_mm", "relief", "landmass_id")


def test_bare_world_has_unit_km_cells() -> None:
    # Without a scale, one cell is 1 km square.
    world = World(8, 4, seed=1)
    assert (world.km_per_col, world.km_per_row) == (1.0, 1.0)


def test_world_reads_metadata_through_its_scale() -> None:
    # The four metadata accessors are the GridScale's values.
    scale = grid_scale(8, 4, (800.0, 200.0), 30.0, 10.0)
    world = World(8, 4, seed=1, scale=scale)
    assert (world.km_per_col, world.km_per_row, world.lat_top, world.lon_left) == (
        scale.km_per_col,
        scale.km_per_row,
        scale.lat_top,
        scale.lon_left,
    )


def test_fingerprint_ignores_scale_metadata() -> None:
    # Scale is metadata, not a per-tile field: two otherwise equal worlds hash the same.
    plain = World(8, 4, seed=1)
    scaled = World(8, 4, seed=1, scale=grid_scale(8, 4, (6000.0, 3000.0), 45.0, 0.0))
    assert plain.fingerprint() == scaled.fingerprint()


def test_physical_fields_are_registered() -> None:
    # The phase-3 arrays are in FIELDS, so fingerprint() and generic field loops cover them.
    assert set(PHYSICAL_FIELDS) <= set(World.FIELDS)


def test_new_world_has_flat_relief_and_no_landmass() -> None:
    # Before generation: no relief anywhere and every cell outside any landmass.
    world = World(8, 4, seed=1)
    assert (world.relief == int(Relief.NONE)).all() and (world.landmass_id == -1).all()


@pytest.mark.parametrize("name", PHYSICAL_FIELDS)
def test_fingerprint_covers_physical_field(name: str) -> None:
    world = World(8, 4, seed=1)
    before = world.fingerprint()
    getattr(world, name)[0, 0] = 3
    assert world.fingerprint() != before


def test_view_reads_physical_fields() -> None:
    world = World(8, 4, seed=1)
    world.elevation_m[1, 2] = 1250.0
    world.temperature_c[1, 2] = -4.5
    world.rain_mm[1, 2] = 640.0
    world.relief[1, 2] = int(Relief.HILLS)
    world.landmass_id[1, 2] = 0
    tile = world.view(2, 1)
    assert (tile.elevation_m, tile.temperature_c, tile.rain_mm, tile.relief, tile.landmass_id) == (
        1250.0,
        -4.5,
        640.0,
        Relief.HILLS,
        0,
    )


def test_physical_field_shapes_match_grid() -> None:
    world = World(8, 4, seed=1)
    assert all(np.shape(getattr(world, name)) == (4, 8) for name in PHYSICAL_FIELDS)

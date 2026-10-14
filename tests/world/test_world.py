"""Tests for the World container's km scale metadata."""

from __future__ import annotations

from biomegen.util.units import grid_scale
from biomegen.world.world import World


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

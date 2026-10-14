"""Tests for the World data model and the Overlay composite contract."""

from __future__ import annotations

import numpy as np

from biomegen.world.overlay import Overlay
from biomegen.world.tile import Biome, Cell, WaterType
from biomegen.world.world import World


def test_world_allocates_expected_shapes_and_dtypes() -> None:
    w = World(width=8, height=5, seed=1)
    assert w.elevation_m.shape == (5, 8)
    assert w.biome.dtype == np.uint8
    assert w.region_id.dtype == np.int32
    # Defaults: all deep ocean, no region, no POI.
    assert (w.biome == int(Biome.DEEP)).all()
    assert (w.region_id == -1).all()
    assert (w.poi_index == -1).all()


def test_world_view_gathers_fields() -> None:
    w = World(width=4, height=4, seed=1)
    w.biome[2, 3] = int(Biome.FOREST)
    w.water_type[2, 3] = int(WaterType.NONE)
    w.elevation_m[2, 3] = 500.0
    view = w.view(3, 2)
    assert view.biome == Biome.FOREST
    assert view.x == 3 and view.y == 2
    assert view.elevation_m == 500.0


def test_fingerprint_changes_when_a_field_changes() -> None:
    w = World(width=6, height=6, seed=1)
    before = w.fingerprint()
    assert w.fingerprint() == before  # stable across calls
    w.biome[0, 0] = int(Biome.DESERT)
    assert w.fingerprint() != before


def test_overlay_interior_composite_does_not_mutate_base() -> None:
    base = np.full((5, 5), int(Cell.FLOOR), dtype=np.uint8)
    overlay = Overlay()
    overlay.set_interior(interior_seed=99, floor=0, x=2, y=3, cell=int(Cell.CHEST))

    composited = overlay.apply_interior(base, interior_seed=99, floor=0)
    assert composited[3, 2] == int(Cell.CHEST)  # overlay wins
    assert base[3, 2] == int(Cell.FLOOR)  # base untouched (a copy was made)

    # An interior with no edits returns the base object unchanged (no needless copy).
    untouched = overlay.apply_interior(base, interior_seed=1, floor=0)
    assert untouched is base


def test_overlay_surface_roundtrip_serialisation() -> None:
    overlay = Overlay()
    overlay.set_surface(1, 2, glyph="x", blocked=True)
    overlay.set_interior(7, -1, 0, 0, int(Cell.WALL))
    restored = Overlay.from_dict(overlay.to_dict())
    assert restored.get_surface(1, 2) == {"glyph": "x", "blocked": True}
    assert restored.get_interior_cell(7, -1, 0, 0) == int(Cell.WALL)

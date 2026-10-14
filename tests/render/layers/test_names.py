"""Tests for the labels layer (geography names)."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.entities import POI
from biomegen.world.tile import Biome
from tests.render.conftest import add_feature, make_world

VIEW = View("t", ("terrain", "markers", "labels"))


def _draw(world, config, **kwargs):
    return build_grid(world, config, VIEW, Sampler.viewport(world, world.height, world.width), **kwargs)


def _island():
    world = make_world(60, 12, Biome.DEEP, -2000.0)
    cells = [(x, y) for x in range(20, 40) for y in range(3, 9)]
    for x, y in cells:
        world.biome[y, x] = int(Biome.GRASS)
        world.elevation_m[y, x] = 200.0
        world.dist_to_ocean[y, x] = float(min(x - 19, 40 - x, y - 2, 9 - y))
    add_feature(world, "landmass", "Orlo", (30, 6), cells, area_km2=1000.0)
    return world


def _text(grid) -> str:
    return "\n".join("".join(row) for row in grid.glyph.tolist())


def test_landmass_name_is_drawn_in_spaced_capitals(config) -> None:
    assert "O R L O" in _text(_draw(_island(), config))


def test_labels_are_bold(config) -> None:
    assert bool(_draw(_island(), config).bold.any())


def test_no_labels_when_turned_off(config) -> None:
    assert "O R L O" not in _text(_draw(_island(), config, labels="none"))


def test_label_avoids_a_marker(config) -> None:
    # A POI on the best spot pushes the label elsewhere; the marker glyph survives.
    world = _island()
    world.pois.append(POI(kind="tower", x=30, y=5, interior_seed=1))
    world.poi_index[5, 30] = 0
    grid = _draw(world, config)
    assert grid.glyph[5, 30] == config.get("render.markers.tower")


def test_sea_name_is_placed_near_its_anchor(config) -> None:
    world = make_world(60, 12, Biome.DEEP, -2000.0)
    add_feature(world, "sea", "Calm Sea", (30, 6))
    assert "Calm Sea" in _text(_draw(world, config))


def test_label_does_not_run_off_the_grid(config) -> None:
    # A name longer than the grid is dropped rather than clipped.
    world = make_world(10, 5, Biome.DEEP, -2000.0)
    add_feature(world, "sea", "The Extremely Long Sea Name", (5, 2))
    assert "Extremely" not in _text(_draw(world, config))


def test_unnamed_features_are_skipped(config) -> None:
    world = _island()
    world.features[0].name = ""
    assert "O R L O" not in _text(_draw(world, config))

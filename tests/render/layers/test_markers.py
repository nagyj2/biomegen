"""Tests for the markers layer."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.entities import POI
from biomegen.world.overlay import Overlay
from biomegen.world.tile import Biome
from tests.render.conftest import make_world

VIEW = View("t", ("terrain", "markers"))


def _draw(world, config, overlay=None):
    return build_grid(world, config, VIEW, Sampler.viewport(world, world.height, world.width), overlay)


def _world_with_tower():
    world = make_world(3, 3, Biome.GRASS)
    world.pois.append(POI(kind="tower", x=1, y=1, interior_seed=5))
    world.poi_index[1, 1] = 0
    return world


def test_poi_anchor_draws_its_marker_glyph(config) -> None:
    assert _draw(_world_with_tower(), config).glyph[1, 1] == config.get("render.markers.tower")


def test_poi_marker_is_bold(config) -> None:
    assert bool(_draw(_world_with_tower(), config).bold[1, 1])


def test_poi_marker_uses_the_marker_colours(config) -> None:
    grid = _draw(_world_with_tower(), config)
    assert grid.bg[1, 1].tolist() == config.get("render.marker_style.bg")


def test_unknown_poi_kind_falls_back_to_a_question_mark(config) -> None:
    world = _world_with_tower()
    world.pois[0].kind = "obelisk"
    assert _draw(world, config).glyph[1, 1] == "?"


def test_overlay_glyph_edit_wins_over_the_terrain(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    overlay = Overlay()
    overlay.set_surface(2, 0, glyph="X")
    assert _draw(world, config, overlay).glyph[0, 2] == "X"


def test_world_without_pois_draws_nothing(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    assert not bool(_draw(world, config).bold.any())

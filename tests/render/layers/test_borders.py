"""Tests for the borders layer: realm borders and war fronts."""

from __future__ import annotations

import numpy as np

from biomegen.render.layers import LayerContext, build_grid
from biomegen.render.views import View
from biomegen.sampling.detail import DetailSampler
from biomegen.sampling.sampler import Sampler
from biomegen.world.entities import Realm
from biomegen.world.tile import Biome
from biomegen.world.world import World
from tests.render.conftest import make_world

WITH = View("p", ("terrain", "tint", "borders"), "realm")
WITHOUT = View("p", ("terrain", "tint"), "realm")


def _two_realms(left: int = 0, right: int = 1, liege: int = -1) -> World:
    """A 6x2 grassland: realm ``left`` in columns 0-2 and ``right`` in columns 3-5 (-1 = wild)."""
    world = make_world(6, 2, Biome.GRASS)
    world.realms = [
        Realm(id=0, kind="major", color=(200, 40, 40)),
        Realm(id=1, kind="major", color=(40, 40, 200), liege=liege),
    ]
    world.realm_id[:, :3], world.realm_id[:, 3:] = left, right
    return world


def _draw(world: World, config, view: View = WITH):
    return build_grid(world, config, view, Sampler.viewport(world, world.height, world.width))


def _changed_columns(world: World, config) -> list[int]:
    """The columns where drawing the borders changes the fill."""
    changed = (_draw(world, config).bg != _draw(world, config, WITHOUT).bg).any(axis=(0, 2))
    return np.flatnonzero(changed).tolist()


def test_a_border_is_one_cell_wide(config) -> None:
    # Only the cell of the larger realm id beside the border is marked.
    assert _changed_columns(_two_realms(), config) == [3]


def test_the_border_line_is_lighter_than_the_land(config) -> None:
    world = _two_realms()
    assert _draw(world, config).bg[0, 3].sum() > _draw(world, config, WITHOUT).bg[0, 3].sum()


def test_one_realm_has_no_border(config) -> None:
    assert _changed_columns(_two_realms(left=0, right=0), config) == []


def test_a_border_against_wild_land_marks_the_realms_cell(config) -> None:
    # Wild land counts as -1, so the realm's own cell carries the line.
    assert _changed_columns(_two_realms(left=-1, right=0), config) == [3]


def test_water_between_realms_has_no_border(config) -> None:
    world = _two_realms()
    world.biome[:, 2:4] = int(Biome.DEEP)
    assert _changed_columns(world, config) == []


def test_a_vassal_border_is_fainter(config) -> None:
    # The same border is lighter between independent realms than between a vassal and its overlord.
    independent = _draw(_two_realms(), config).bg[0, 3].astype(int).sum()
    vassal = _draw(_two_realms(liege=0), config).bg[0, 3].astype(int).sum()
    assert vassal < independent


def test_a_war_front_is_drawn_red(config) -> None:
    world = _two_realms()
    world.front[:, 2:4] = True
    red, green, _blue = _draw(world, config).bg[0, 3].astype(int)
    assert red > green + 100


def test_a_front_away_from_a_border_is_not_drawn(config) -> None:
    world = _two_realms(left=0, right=0)
    world.front[:] = True
    assert _changed_columns(world, config) == []


def test_a_world_without_realms_is_unchanged(config) -> None:
    world = make_world(6, 2, Biome.GRASS)
    assert (
        _draw(world, config, View("p", ("terrain", "borders"))).bg == _draw(world, config, View("p", ("terrain",))).bg
    ).all()


def _detail(world: World, config, cam_x: int) -> LayerContext:
    sampler = DetailSampler(world, config, 6, 3, cam_x, 0, 6, 2, "zoom")
    return LayerContext(world, config, WITH, sampler)


def test_the_realm_of_a_cell_depends_only_on_its_position(config) -> None:
    # Shifting the camera by one tile shifts the cells by one tile's width and leaves each cell's realm alone: this is
    # what makes the zoom and local scales draw the same wobbling border.
    world = make_world(14, 2, Biome.GRASS)
    world.realms = [Realm(id=0, kind="major"), Realm(id=1, kind="major")]
    world.realm_id[:, 7:] = 1
    first, second = _detail(world, config, 2), _detail(world, config, 3)
    assert (first.realm[:, 6:] == second.realm[:, :-6]).all()


def test_the_border_wobbles_with_the_biome_blend(config) -> None:
    # At the detail scale the border is not a straight tile edge: its cells vary in column from row to row.
    world = make_world(14, 6, Biome.GRASS)
    world.realms = [Realm(id=0, kind="major"), Realm(id=1, kind="major")]
    world.realm_id[:, 7:] = 1
    realm = LayerContext(world, config, WITH, DetailSampler(world, config, 6, 3, 2, 0, 10, 6, "zoom")).realm
    first_column = [int(np.argmax(row == 1)) for row in realm]
    assert len(set(first_column)) > 1


def test_a_detail_border_is_a_thin_line(config) -> None:
    # A zoom tile is six columns wide; the line is a cell or two across, not a block.
    world = make_world(14, 4, Biome.GRASS)
    world.realms = [
        Realm(id=0, kind="major", color=(200, 40, 40)),
        Realm(id=1, kind="major", color=(40, 40, 200)),
    ]
    world.realm_id[:, 7:] = 1
    sampler = DetailSampler(world, config, 6, 3, 2, 0, 10, 4, "zoom")
    with_lines = build_grid(world, config, WITH, sampler)
    without = build_grid(world, config, WITHOUT, sampler)
    marked = (with_lines.bg != without.bg).any(axis=2)
    assert 0 < marked.sum(axis=1).max() <= 3

"""Tests for the markers layer."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.views import View
from biomegen.sampling.detail import DetailSampler
from biomegen.sampling.sampler import Sampler
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


def _draw_detail(world, config, overlay=None):
    sampler = DetailSampler(world, config, 10, 5, 0, 0, world.width, world.height)
    return build_grid(world, config, VIEW, sampler, overlay)


def test_detail_marker_is_one_cell_in_the_tile_block(config) -> None:
    # A POI covers a 10 x 5 block of cells at zoom; only one glyph is drawn, not fifty.
    grid = _draw_detail(_world_with_tower(), config)
    assert int((grid.glyph == config.get("render.markers.tower")).sum()) == 1


def test_detail_marker_sits_at_the_centre_of_the_block(config) -> None:
    # Tile (1, 1) spans columns 10-19 and rows 5-9; its centre cell is column 15, row 7.
    grid = _draw_detail(_world_with_tower(), config)
    assert grid.glyph[7, 15] == config.get("render.markers.tower")


def test_detail_overlay_glyph_is_one_cell_in_the_tile_block(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    overlay = Overlay()
    overlay.set_surface(2, 0, glyph="X")
    assert int((_draw_detail(world, config, overlay).glyph == "X").sum()) == 1


def _world_with_town(kind: str = "town"):
    world = make_world(3, 3, Biome.GRASS)
    world.pois.append(POI(kind=kind, x=1, y=1, interior_seed=5, civilized=True))
    world.poi_index[1, 1] = 0
    return world


def test_settlement_marker_comes_from_its_tier_row(config) -> None:
    assert _draw(_world_with_town("capital"), config).glyph[1, 1] == config.get("tables.tiers.capital.glyph")


def test_settlement_marker_uses_the_tier_colours(config) -> None:
    grid = _draw(_world_with_town("capital"), config)
    assert grid.fg[1, 1].tolist() == config.get("tables.tiers.capital.fg")


def test_tier_without_a_background_keeps_the_terrain_background(config) -> None:
    # Towns have no bg in tiers.toml, so the cell keeps the grass fill.
    marked = _draw(_world_with_town("town"), config)
    bare = build_grid(
        _world_with_town("town"), config, View("t", ("terrain",)), Sampler.viewport(_world_with_town(), 3, 3)
    )
    assert marked.bg[1, 1].tolist() == bare.bg[1, 1].tolist()


def test_ascii_settlement_marker_uses_the_ascii_column(config) -> None:
    grid = build_grid(
        _world_with_town("city"), config, VIEW, Sampler.viewport(_world_with_town(), 3, 3), ascii_only=True
    )
    assert grid.glyph[1, 1] == config.get("tables.tiers.city.ascii")

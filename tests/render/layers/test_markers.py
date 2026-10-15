"""Tests for the markers layer."""

from __future__ import annotations

from biomegen.config import load_config
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


# --- which detail scales draw a POI marker ---------------------------------------------------------------------------


def _crisp():
    config = load_config(None)
    config.data["render"]["blend_strength"] = 0.0
    return config


def _town_world():
    world = make_world(10, 10, Biome.GRASS)
    world.pois.append(POI(kind="town", x=5, y=5, interior_seed=5, civilized=True, pop=800))
    world.poi_index[5, 5] = 0
    return world


def _scaled(world, config, scale, view_layers=("terrain", "sites", "markers")):
    cells = (10, 5) if scale == "zoom" else (18, 9)
    sampler = DetailSampler(world, config, cells[0], cells[1], 0, 0, world.width, world.height, scale)
    return build_grid(world, config, View("t", view_layers), sampler)


def test_the_zoom_scale_shows_the_settlement_marker_over_its_plan() -> None:
    # The marker is drawn after the sites layer, so the town's small plan does not hide it.
    config = _crisp()
    grid = _scaled(_town_world(), config, "zoom")
    assert int((grid.glyph == config.get("tables.tiers.town.glyph")).sum()) == 1


def test_the_local_scale_shows_no_marker() -> None:
    config = _crisp()
    grid = _scaled(_town_world(), config, "local")
    assert int((grid.glyph == config.get("tables.tiers.town.glyph")).sum()) == 0


def test_the_site_scale_shows_no_marker() -> None:
    from biomegen.sites import site_geometry, window_sampler

    config = _crisp()
    world = _town_world()
    geometry = site_geometry(world.pois[0], config)
    grid = build_grid(
        world, config, View("t", ("terrain", "sites", "markers")), window_sampler(world, config, geometry)
    )
    assert int((grid.glyph == config.get("tables.tiers.town.glyph")).sum()) == 0


def test_the_marker_scales_are_configurable() -> None:
    config = _crisp()
    config.data["render"]["detail_marker_scales"] = ["zoom", "local"]
    grid = _scaled(_town_world(), config, "local")
    assert int((grid.glyph == config.get("tables.tiers.town.glyph")).sum()) == 1


def test_the_default_tinted_and_terrain_views_draw_markers_after_sites() -> None:
    from biomegen.config.defaults import get_defaults

    for name, view in get_defaults()["render"]["views"].items():
        layers = view["detail_layers"]
        assert layers.index("sites") < layers.index("markers"), name


def test_hamlet_marker_is_hidden_at_the_map_scale(config) -> None:
    # The hamlet's tier row sets map_marker = false, so the map scale leaves its cell undrawn.
    assert not bool(_draw(_world_with_town("hamlet"), config).bold[1, 1])


def test_hamlet_marker_is_drawn_at_the_zoom_scale(config) -> None:
    grid = _draw_detail(_world_with_town("hamlet"), config)
    assert int((grid.glyph == config.get("tables.tiers.hamlet.glyph")).sum()) == 1


def _town_in_realm(realm_id: int):
    world = make_world(3, 3, Biome.GRASS)
    world.pois.append(POI(kind="town", x=1, y=1, interior_seed=5, civilized=True, realm_id=realm_id))
    world.poi_index[1, 1] = 0
    return world


def test_a_free_settlement_is_drawn_in_its_free_colour(config) -> None:
    grid = _draw(_town_in_realm(-1), config)
    assert grid.fg[1, 1].tolist() == config.get("tables.tiers.town.free_fg")


def test_a_held_settlement_keeps_its_ordinary_colour(config) -> None:
    grid = _draw(_town_in_realm(0), config)
    assert grid.fg[1, 1].tolist() == config.get("tables.tiers.town.fg")


def test_a_free_settlement_keeps_its_glyph(config) -> None:
    assert _draw(_town_in_realm(-1), config).glyph[1, 1] == config.get("tables.tiers.town.glyph")

"""Tests for the tint layer."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.render.layers import build_grid
from biomegen.render.views import View
from biomegen.sampling.sampler import Sampler
from biomegen.world.tile import Biome, Relief
from tests.render.conftest import make_world


def _draw(world, config, tint):
    view = View("t", ("terrain", "relief", "tint"), tint)
    return build_grid(world, config, view, Sampler.viewport(world, world.height, world.width))


def test_untinted_view_leaves_the_terrain_alone(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    plain = build_grid(world, config, View("t", ("terrain",)), Sampler.viewport(world, 3, 3))
    assert (_draw(world, config, "").bg == plain.bg).all()


def test_temperature_tint_colours_by_degrees(config) -> None:
    # A hot cell and a freezing cell get different fills from the temperature ramp.
    world = make_world(2, 1, Biome.GRASS)
    world.temperature_c[0] = [30.0, -20.0]
    grid = _draw(world, config, "temperature")
    assert grid.bg[0, 0].tolist() != grid.bg[0, 1].tolist()


def test_rainfall_tint_paints_water_with_the_water_colour(config) -> None:
    world = make_world(3, 3, Biome.DEEP, -500.0)
    assert _draw(world, config, "rainfall").bg[1, 1].tolist() == config.get("render.ramps.rainfall.water_color")


def test_tint_blanks_the_terrain_glyphs(config) -> None:
    world = make_world(3, 3, Biome.FOREST)
    assert set(_draw(world, config, "rainfall").glyph.ravel().tolist()) == {" "}


def test_elevation_tint_keeps_relief_glyphs(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.relief[1, 1] = int(Relief.MOUNTAIN)
    assert _draw(world, config, "elevation").glyph[1, 1] == config.get("tables.relief.mountain.glyph")


def test_a_ramp_can_read_any_world_field() -> None:
    # Ramps name their World array, so a user ramp over moisture needs no code.
    config = load_config(None)
    config.data["render"]["ramps"]["moisture"] = {"field": "moisture", "stops": [[0, [0, 0, 0]], [1, [200, 0, 0]]]}
    world = make_world(2, 1, Biome.GRASS)
    world.moisture[0] = [0.0, 1.0]
    grid = _draw(world, config, "moisture")
    assert grid.bg[0, 1, 0] > grid.bg[0, 0, 0]


# --- the realm tint -----------------------------------------------------------------------------------------------


def _realm_world(config):
    from biomegen.world.entities import Realm

    world = make_world(3, 1, Biome.GRASS)
    world.realms = [Realm(id=0, kind="major", color=(200, 0, 0)), Realm(id=1, kind="major", color=(0, 0, 200))]
    world.realm_id[0] = [0, 1, -1]
    return world


def test_realm_tint_colours_land_by_its_realm(config) -> None:
    grid = _draw(_realm_world(config), config, "realm")
    assert (grid.bg[0, 0, 0] > grid.bg[0, 0, 2]) and (grid.bg[0, 1, 2] > grid.bg[0, 1, 0])


def test_unclaimed_land_is_a_flat_grey(config) -> None:
    red, green, blue = _draw(_realm_world(config), config, "realm").bg[0, 2].tolist()
    assert red == green == blue


def test_realm_tint_leaves_water_alone(config) -> None:
    world = _realm_world(config)
    world.biome[0, 1] = int(Biome.DEEP)
    plain = build_grid(world, config, View("t", ("terrain", "relief")), Sampler.viewport(world, 1, 3))
    assert (_draw(world, config, "realm").bg[0, 1] == plain.bg[0, 1]).all()


def test_realm_tint_keeps_relief_glyphs(config) -> None:
    world = _realm_world(config)
    world.relief[0, 0] = int(Relief.MOUNTAIN)
    assert _draw(world, config, "realm").glyph[0, 0] == config.get("tables.relief.mountain.glyph")

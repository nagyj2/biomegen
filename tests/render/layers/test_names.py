"""Tests for the labels layer (geography names)."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.views import View
from biomegen.sampling.sampler import Sampler
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
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


def _sea(width: int, height: int):
    """A world of salt sea: the deep-water biome over salt water."""
    world = make_world(width, height, Biome.DEEP, -2000.0)
    world.water_type[:] = int(WaterType.SALT)
    return world


def test_sea_name_is_drawn_on_its_water(config) -> None:
    world = _sea(60, 12)
    add_feature(world, "sea", "Calm Sea", (30, 6))
    assert "Calm Sea" in _text(_draw(world, config))


def test_sea_name_sits_in_the_middle_of_its_water_not_at_its_anchor(config) -> None:
    # Land fills the top half; the anchor (farthest from land) is on the bottom edge. The name goes midway between
    # the coast and the edge, over water.
    world = _sea(60, 20)
    world.biome[:9] = int(Biome.GRASS)
    world.water_type[:9] = int(WaterType.NONE)
    world.elevation_m[:9] = 100.0
    add_feature(world, "sea", "Calm Sea", (30, 19))
    rows = [row for row, line in enumerate(_text(_draw(world, config)).splitlines()) if "Calm Sea" in line]
    assert rows and 12 <= rows[0] <= 16


def test_label_does_not_run_off_the_grid(config) -> None:
    # A name longer than the grid is dropped rather than clipped.
    world = _sea(10, 5)
    add_feature(world, "sea", "The Extremely Long Sea Name", (5, 2))
    assert "Extremely" not in _text(_draw(world, config))


def test_unnamed_features_are_skipped(config) -> None:
    world = _island()
    world.features[0].name = ""
    assert "O R L O" not in _text(_draw(world, config))


# --- realm names in the political view ---------------------------------------------------------------------------

POLITICAL = View("p", ("terrain", "tint", "markers", "labels"), "realm")


def _realms(*specs):
    """The island with realms over its land: each spec is (kind, short name, area km2, column range)."""
    from biomegen.world.entities import Realm

    world = _island()
    for index, (kind, short, area, columns) in enumerate(specs):
        world.realms.append(Realm(id=index, kind=kind, short=short, area_km2=area, color=(200, 40, 40)))
        world.realm_id[3:9, columns[0] : columns[1]] = index
    return world


def _draw_political(world, config, **kwargs):
    return build_grid(world, config, POLITICAL, Sampler.viewport(world, world.height, world.width), **kwargs)


def test_a_political_view_names_a_realm_in_capitals(config) -> None:
    assert "ALDOR" in _text(_draw_political(_realms(("major", "Aldor", 100000.0, (20, 40))), config))


def test_a_political_view_leaves_the_landmass_name_out(config) -> None:
    assert "O R L O" not in _text(_draw_political(_realms(("major", "Aldor", 100000.0, (20, 40))), config))


def test_a_terrain_view_does_not_name_realms(config) -> None:
    assert "ALDOR" not in _text(_draw(_realms(("major", "Aldor", 100000.0, (20, 40))), config))


def test_a_small_realm_is_not_named(config) -> None:
    assert "ALDOR" not in _text(_draw_political(_realms(("major", "Aldor", 1000.0, (20, 40))), config))


def test_a_city_state_is_not_named(config) -> None:
    assert "ALDOR" not in _text(_draw_political(_realms(("city_state", "Aldor", 100000.0, (20, 40))), config))


def test_each_big_realm_is_named_near_its_own_land(config) -> None:
    text = _text(
        _draw_political(_realms(("major", "Aldor", 100000.0, (20, 30)), ("major", "Brek", 90000.0, (30, 40))), config)
    )
    row = next(line for line in text.splitlines() if "ALDOR" in line)
    assert "BREK" in text and row.index("ALDOR") < next(line for line in text.splitlines() if "BREK" in line).index(
        "BREK"
    )


def test_a_realm_label_takes_a_lightened_realm_colour(config) -> None:
    grid = _draw_political(_realms(("major", "Aldor", 100000.0, (20, 40))), config)
    row = next(r for r, line in enumerate(grid.glyph.tolist()) if "ALDOR" in "".join(line))
    col = "".join(grid.glyph[row].tolist()).index("ALDOR")
    red, green, _ = grid.fg[row, col].astype(int)
    assert red > green > 40

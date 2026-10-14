"""Tests for the legend and gazetteer."""

from __future__ import annotations

from biomegen.render.backends.plain import to_plain
from biomegen.render.furniture.legend import build_legend
from biomegen.render.views import View
from biomegen.world.tile import Biome, Relief, WaterType
from tests.render.conftest import add_feature, make_world

TERRAIN = View("terrain", ("terrain",))
ELEVATION = View("elevation", ("terrain", "tint"), "elevation")


def _world():
    world = make_world(20, 10, Biome.GRASS, 100.0)
    world.biome[:, :5] = int(Biome.DEEP)
    world.relief[4, 10] = int(Relief.MOUNTAIN)
    world.water_type[2, 10] = int(WaterType.FRESH)
    world.temperature_c[:] = 12.0
    world.rain_mm[:] = 900.0
    peak = add_feature(world, "peak", "Mount Kel", (10, 4), elevation_m=2100.0)
    add_feature(world, "landmass", "Orlo", (12, 5), [(10, 4)], area_km2=2_000_000.0, summit=peak.id)
    add_feature(world, "sea", "Calm Sea", (2, 5), elevation_m=-3200.0)
    return world


def _text(config, view=TERRAIN, ascii_only=False) -> str:
    return to_plain(build_legend(_world(), config, view, 100, ascii_only))


def test_legend_lists_the_biomes_present(config) -> None:
    text = _text(config)
    assert config.get("tables.biomes.grass.label") in text and config.get("tables.biomes.desert.label") not in text


def test_legend_lists_rivers_and_relief_that_exist(config) -> None:
    assert "River" in _text(config) and config.get("tables.relief.mountain.label") in _text(config)


def test_legend_omits_roads_when_there_are_none(config) -> None:
    assert "Road" not in _text(config)


def test_geography_calls_a_large_landmass_a_continent(config) -> None:
    assert "Orlo - continent, 2.0 million km²" in _text(config)


def test_geography_names_the_summit(config) -> None:
    assert "highest point Mount Kel (2,100 m)" in _text(config)


def test_geography_gives_sea_depth(config) -> None:
    assert "Calm Sea - depths to 3,200 m" in _text(config)


def test_climate_reports_the_extremes(config) -> None:
    assert "Temperature 12 °C" in _text(config) and "900 mm/yr" in _text(config)


def test_data_view_adds_a_ramp_bar(config) -> None:
    assert "ELEVATION (m)" in _text(config, ELEVATION)


def test_data_view_hides_the_biome_swatches(config) -> None:
    assert config.get("tables.biomes.grass.label") not in _text(config, ELEVATION)


def test_ascii_legend_is_pure_ascii(config) -> None:
    assert _text(config, ascii_only=True).isascii()


def test_legend_wraps_within_the_width(config) -> None:
    assert max(len(line) for line in _text(config).split("\n")) <= 100 + 24

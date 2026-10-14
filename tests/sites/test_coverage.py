"""Tests for which cells and tiles a site covers."""

from __future__ import annotations

from biomegen.config.model import Config
from biomegen.sites import site_at, site_pois
from tests.sites.conftest import add_poi, flat_world


def test_site_pois_lists_only_kinds_with_a_site(config: Config) -> None:
    world = flat_world()
    add_poi(world, "village", 4, 4, pop=500)
    add_poi(world, "bridge", 8, 4)
    assert [poi.kind for poi, _geometry in site_pois(world, config)] == ["village"]


def test_site_at_finds_the_poi_under_a_tile(config: Config) -> None:
    world = flat_world()
    poi = add_poi(world, "capital", 7, 5, pop=50000)
    assert site_at(world, config, 8, 5) is poi


def test_site_at_is_none_away_from_every_site(config: Config) -> None:
    world = flat_world()
    add_poi(world, "tower", 7, 5)
    assert site_at(world, config, 2, 2) is None


def test_the_nearest_anchor_wins_an_overlap(config: Config) -> None:
    world = flat_world()
    add_poi(world, "capital", 5, 5, pop=50000)
    near = add_poi(world, "tower", 7, 5)
    assert site_at(world, config, 7, 5) is near

"""Tests for which cells and tiles a site covers."""

from __future__ import annotations

from biomegen.config.model import Config
from biomegen.sampling.sampler import Sampler
from biomegen.sites import extent_mask, site_at, site_pois
from tests.sites.conftest import add_poi, flat_world


def test_site_pois_lists_only_kinds_with_a_site(config: Config) -> None:
    world = flat_world()
    add_poi(world, "village", 4, 4, pop=500)
    add_poi(world, "bridge", 8, 4)
    assert [poi.kind for poi, _geometry in site_pois(world, config)] == ["village"]


def test_extent_mask_covers_the_cells_under_the_extent(config: Config) -> None:
    # A tower extent is half a tile wide, so on a one-cell-per-tile grid only its own tile's cell is covered.
    world = flat_world()
    add_poi(world, "tower", 4, 4)
    mask = extent_mask(world, config, Sampler.viewport(world, world.height, world.width))
    assert bool(mask[4, 4]) and int(mask.sum()) == 1


def test_a_wide_site_covers_several_cells(config: Config) -> None:
    world = flat_world()
    add_poi(world, "capital", 7, 5, pop=50000)
    mask = extent_mask(world, config, Sampler.viewport(world, world.height, world.width))
    assert int(mask.sum()) >= 6


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

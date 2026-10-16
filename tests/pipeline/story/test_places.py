"""Tests for the locality helpers: the nearest qualifying feature of a kind, for the places a reason may name."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story.places import nearest_feature
from biomegen.util.units import grid_scale
from biomegen.world.entities import GeoFeature, River
from biomegen.world.tile import Biome, WaterType
from biomegen.world.world import World


@pytest.fixture()
def cfg() -> Config:
    config = load_config(None)
    config.data["politics"]["reason_near_km"] = 100.0
    return config


@pytest.fixture()
def world() -> World:
    """A 40 x 10 land strip of 30 km cells on one landmass (cells 0..39 east), no features yet."""
    made = World(40, 10, 1, grid_scale(40, 10, (1200.0, 300.0), 30.0, 0.0))
    made.water_type[:] = int(WaterType.NONE)
    made.biome[:] = int(Biome.GRASS)
    made.landmass_id[:] = 0
    made.dist_to_ocean[:] = 1000.0
    return made


def _river(world: World, name: str, cells: list[tuple[int, int]]) -> GeoFeature:
    world.rivers.append(River(id=len(world.rivers), path=cells))
    feature = GeoFeature(
        id=len(world.features), kind="river", anchor=cells[0], ref=len(world.rivers) - 1, name=name, cells=[]
    )
    world.features.append(feature)
    return feature


def test_a_river_near_the_points_qualifies(world: World, cfg: Config) -> None:
    river = _river(world, "Near", [(5, y) for y in range(10)])
    assert nearest_feature(world, cfg, "river", [(7, 4)]) == river.id


def test_a_river_beyond_the_cap_does_not(world: World, cfg: Config) -> None:
    # 100 km is 3.3 cells: a river 10 cells away is out of reach.
    _river(world, "Far", [(20, y) for y in range(10)])
    assert nearest_feature(world, cfg, "river", [(7, 4)]) == -1


def test_the_nearer_of_two_rivers_wins(world: World, cfg: Config) -> None:
    _river(world, "Second", [(10, y) for y in range(10)])
    near = _river(world, "First", [(8, y) for y in range(10)])
    assert nearest_feature(world, cfg, "river", [(7, 4)]) == near.id


def test_a_river_on_another_landmass_does_not_qualify(world: World, cfg: Config) -> None:
    _river(world, "Island", [(5, y) for y in range(10)])
    world.landmass_id[:, 5] = 1
    assert nearest_feature(world, cfg, "river", [(7, 4)]) == -1


def test_a_range_is_measured_by_its_cells(world: World, cfg: Config) -> None:
    world.features.append(GeoFeature(id=0, kind="range", anchor=(30, 5), name="Hills", cells=[(8, 4), (9, 4)]))
    assert nearest_feature(world, cfg, "range", [(7, 4)]) == 0


def test_a_sea_qualifies_when_a_point_is_near_the_coast(world: World, cfg: Config) -> None:
    world.features.append(GeoFeature(id=0, kind="sea", anchor=(39, 5), name="Deep"))
    world.dist_to_ocean[4, 7] = 30.0
    assert nearest_feature(world, cfg, "sea", [(7, 4)]) == 0


def test_a_sea_does_not_qualify_inland(world: World, cfg: Config) -> None:
    world.features.append(GeoFeature(id=0, kind="sea", anchor=(39, 5), name="Deep"))
    assert nearest_feature(world, cfg, "sea", [(7, 4)]) == -1


def test_no_points_name_nothing(world: World, cfg: Config) -> None:
    _river(world, "Near", [(5, y) for y in range(10)])
    assert nearest_feature(world, cfg, "river", []) == -1


def test_only_the_kind_asked_for_is_returned(world: World, cfg: Config) -> None:
    _river(world, "Near", [(5, y) for y in range(10)])
    assert nearest_feature(world, cfg, "range", [(7, 4)]) == -1


def test_a_hamlet_is_never_the_nearest_settlement(world: World, cfg: Config) -> None:
    # near_target is false on the hamlet tier: a village farther off is named rather than a hamlet next door.
    from biomegen.pipeline.story.places import nearest_settlement
    from biomegen.world.entities import POI

    world.pois.append(POI(kind="village", x=12, y=5, interior_seed=1, civilized=True, pop=300))
    world.pois.append(POI(kind="hamlet", x=6, y=5, interior_seed=2, civilized=True, pop=30))
    assert nearest_settlement(world, cfg, 5, 5) == 0


def test_a_town_next_door_is_the_nearest_settlement(world: World, cfg: Config) -> None:
    from biomegen.pipeline.story.places import nearest_settlement
    from biomegen.world.entities import POI

    world.pois.append(POI(kind="village", x=12, y=5, interior_seed=1, civilized=True, pop=300))
    world.pois.append(POI(kind="village", x=6, y=5, interior_seed=2, civilized=True, pop=300))
    assert nearest_settlement(world, cfg, 5, 5) == 1

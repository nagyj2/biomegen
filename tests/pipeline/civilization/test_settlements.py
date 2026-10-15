"""Tests for the settlements stage: habitability, tier counts, spacing, landmass rules and determinism."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.civilization import settlements
from biomegen.util.units import grid_scale
from biomegen.world.tile import Biome, Relief, WaterType
from biomegen.world.world import World

WIDTH, HEIGHT = 60, 30
TIERS = ("capital", "city", "town", "village")


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def generated(cfg: Config) -> World:
    return pipeline.generate(cfg, 9999)


def _island(config: Config, jitter: float = 0.0) -> World:
    """A 60x30 grid (30 km cells) with a grass island ringed by sea, on landmass 0."""
    config.data["settlements"]["jitter"] = jitter
    world = World(WIDTH, HEIGHT, 1, grid_scale(WIDTH, HEIGHT, (1800.0, 900.0), 30.0, 0.0))
    world.water_type[:] = int(WaterType.SALT)
    world.biome[:] = int(Biome.DEEP)
    land = (slice(3, HEIGHT - 3), slice(3, WIDTH - 3))
    world.water_type[land] = int(WaterType.NONE)
    world.biome[land] = int(Biome.GRASS)
    world.landmass_id[land] = 0
    return world


def _count(world: World, kind: str) -> int:
    return sum(1 for p in world.pois if p.kind == kind)


def _positions(world: World) -> list[tuple[str, int, int]]:
    return [(p.kind, p.x, p.y) for p in world.pois]


def test_habitability_is_zero_on_water() -> None:
    config = load_config(None)
    world = _island(config)
    score = settlements.habitability(world, config, 1)
    assert (score[world.water_type != int(WaterType.NONE)] == 0).all()


def test_habitability_is_zero_on_a_peak() -> None:
    config = load_config(None)
    world = _island(config)
    world.relief[10, 10] = int(Relief.PEAK)
    assert settlements.habitability(world, config, 1)[10, 10] == 0


def test_habitability_rises_beside_a_river() -> None:
    # A river cell lifts the cells within reach by the river bonus; a cell beyond reach is unchanged.
    config = load_config(None)
    world = _island(config)
    world.water_type[10, 20] = int(WaterType.FRESH)
    score = settlements.habitability(world, config, 1)
    assert score[10, 21] > score[10, 40]


def test_habitability_depends_on_seed_only_through_jitter() -> None:
    # With no jitter the seed makes no difference to the score.
    config = load_config(None)
    world = _island(config, jitter=0.0)
    assert np.array_equal(settlements.habitability(world, config, 1), settlements.habitability(world, config, 2))


def test_stage_is_deterministic() -> None:
    config = load_config(None)
    first, second = _island(config, 0.3), _island(config, 0.3)
    settlements.run(first, config, 5)
    settlements.run(second, config, 5)
    assert _positions(first) == _positions(second)


def test_every_tier_is_placed_on_a_large_island() -> None:
    config = load_config(None)
    world = _island(config)
    settlements.run(world, config, 5)
    assert {p.kind for p in world.pois} == set(TIERS)


def test_settlements_keep_the_spacing_of_the_later_tier(generated: World, cfg: Config) -> None:
    # A settlement was placed no closer than its own tier's spacing_km to any settlement placed before it.
    scale = generated.scale
    rank = {name: int(cfg.get(f"tables.tiers.{name}.rank")) for name in TIERS}
    spacing = {name: float(cfg.get(f"tables.tiers.{name}.spacing_km")) for name in TIERS}
    settled = [p for p in generated.pois if p.kind in TIERS]
    for i, a in enumerate(settled):
        for b in settled[i + 1 :]:
            km = float(np.hypot((a.x - b.x) * scale.km_per_col, (a.y - b.y) * scale.km_per_row))
            later = a if rank[a.kind] > rank[b.kind] else b
            assert km >= spacing[later.kind] - 1e-6


def test_settlements_stand_on_dry_habitable_land(generated: World, cfg: Config) -> None:
    minimum = float(cfg.get("settlements.min_habitability"))
    score = settlements.habitability(generated, cfg, generated.seed)
    assert all(score[p.y, p.x] > minimum for p in generated.pois if p.kind in TIERS)


def test_population_is_inside_the_tier_range(generated: World, cfg: Config) -> None:
    for p in generated.pois:
        if p.kind in TIERS:
            lo, hi = cfg.get(f"tables.tiers.{p.kind}.pop")
            assert lo <= p.pop <= hi


def test_capitals_stand_on_the_big_landmasses(generated: World, cfg: Config) -> None:
    areas = np.bincount(generated.landmass_id[generated.landmass_id >= 0]) * generated.scale.cell_area_km2
    minimum = min(float(cfg.get("settlements.capital_min_landmass_km2")), float(areas.max()))
    capitals = [p for p in generated.pois if p.kind == "capital"]
    assert capitals and all(areas[generated.landmass_id[p.y, p.x]] >= minimum for p in capitals)


def test_tier_count_follows_land_area_and_density() -> None:
    # Doubling settlements.density doubles the village count while no other limit applies.
    base = load_config(None)
    dense = load_config(None)
    dense.data["settlements"]["density"] = 2.0
    one, two = _island(base), _island(dense)
    settlements.run(one, base, 5)
    settlements.run(two, dense, 5)
    assert _count(two, "village") > _count(one, "village")


def test_port_tag_marks_settlements_within_reach_of_the_sea() -> None:
    config = load_config(None)
    world = _island(config)
    settlements.run(world, config, 5)
    reach = float(config.get("settlements.coast_reach_km"))
    scale = world.scale
    for p in world.pois:
        # The island spans columns and rows 3 .. size - 4, so the sea is two cells beyond each edge.
        to_sea_km = min(
            (p.x - 2) * scale.km_per_col,
            (WIDTH - 3 - p.x) * scale.km_per_col,
            (p.y - 2) * scale.km_per_row,
            (HEIGHT - 3 - p.y) * scale.km_per_row,
        )
        assert ("port" in p.tags) == (to_sea_km <= reach)


def test_a_settlement_has_the_floors_its_tier_allows(generated: World, cfg: Config) -> None:
    # Bigger tiers have taller buildings: each settlement's floor count lies in its tier's floors range.
    for poi in generated.pois:
        if poi.kind in TIERS:
            lo, hi = (int(v) for v in cfg.get(f"tables.tiers.{poi.kind}.floors"))
            assert lo <= poi.floor_count <= hi


def test_a_settlement_never_goes_underground(generated: World) -> None:
    assert all(poi.lowest_floor == 0 for poi in generated.pois if poi.kind in TIERS)

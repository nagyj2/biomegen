"""Tests for the pure style scorer: eligibility, the score terms in km, the held-land rule, overrides and counts."""

from __future__ import annotations

import numpy as np

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story import poi_styles
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
from biomegen.world.world import World


def _island(width: int = 60, height: int = 30, km_per_col: float = 30.0, km_per_row: float = 30.0) -> World:
    """A grass island (100 m high, one realm holds it all) ringed by sea; cells are ``km_per_col`` by ``km_per_row``."""
    scale = grid_scale(width, height, (width * km_per_col, height * km_per_row), 30.0, 0.0)
    world = World(width, height, 1, scale)
    world.water_type[:] = int(WaterType.SALT)
    world.biome[:] = int(Biome.SHALLOW)
    world.dist_to_ocean[:] = 1000.0
    land = (slice(3, height - 3), slice(3, width - 3))
    world.water_type[land] = int(WaterType.NONE)
    world.biome[land] = int(Biome.GRASS)
    world.elevation_m[land] = 100.0
    world.realm_id[land] = 0
    return world


def _config(style: str = "farm", **row: object) -> Config:
    """Defaults with the noise off and ``style`` reduced to the given row keys over grass (plus its required texts)."""
    cfg = load_config(None)
    cfg.data["poi"]["jitter"] = 0.0
    base = cfg.data["tables"]["poi_styles"][style]
    keep = {
        key: base[key] for key in ("generated", "dynamic", "min_spacing_km", "names", "hooks_homestead") if key in base
    }
    cfg.data["tables"]["poi_styles"][style] = {"min_score": 0.0, "biomes": ["grass"], **keep, **row}
    return cfg


def _village(world: World, x: int, y: int) -> None:
    world.pois.append(POI(kind="village", x=x, y=y, interior_seed=1, civilized=True, pop=300))
    world.poi_index[y, x] = len(world.pois) - 1


def test_scoring_is_deterministic() -> None:
    world, cfg = _island(), load_config(None)
    a = poi_styles.style_score(world, cfg, 7, "farm")
    assert np.array_equal(a, poi_styles.style_score(world, cfg, 7, "farm"))


def test_water_and_other_biomes_are_never_eligible() -> None:
    # Farms stand on land of their biomes only: the sea ring and a desert patch score -inf.
    world, cfg = _island(), load_config(None)
    world.biome[10:14, 10:14] = int(Biome.DESERT)
    score = poi_styles.style_score(world, cfg, 7, "farm")
    assert not np.isfinite(score[0, 0]) and not np.isfinite(score[11, 11]) and np.isfinite(score[15, 30])


def test_a_homestead_needs_held_land_and_a_hamlet_does_not() -> None:
    world, cfg = _island(), load_config(None)
    world.realm_id[:, :30] = -1
    homestead = poi_styles.style_score(world, cfg, 7, "farm", "homestead")
    hamlet = poi_styles.style_score(world, cfg, 7, "farm", "hamlet")
    assert (np.isfinite(homestead[15, 10]), np.isfinite(hamlet[15, 10]), np.isfinite(homestead[15, 40])) == (
        False,
        True,
        True,
    )


def test_a_realm_override_replaces_the_worlds_ownership() -> None:
    # A simulation passes its live ownership: only the cells it says are held score for a homestead.
    world, cfg = _island(), load_config(None)
    held = np.full(world.realm_id.shape, -1, dtype=world.realm_id.dtype)
    held[:, 30:] = 2
    score = poi_styles.style_score(world, cfg, 7, "farm", realm_id=held)
    assert not np.isfinite(score[15, 20]) and np.isfinite(score[15, 40])


def test_a_road_override_moves_the_road_term() -> None:
    # The near_road term follows the grid it is given, not the world's road array.
    world = _island()
    cfg = _config(near_road=1.0, near_road_km=60.0)
    road = np.zeros(world.road.shape, dtype=bool)
    road[15, 10] = True
    score = poi_styles.style_score(world, cfg, 7, "farm", road=road)
    assert score[15, 11] > score[15, 40]


def test_a_settlement_pulls_a_style_that_weights_it_by_km() -> None:
    world = _island()
    _village(world, 30, 15)
    cfg = _config(near_settlement=1.0, near_settlement_km=100.0)
    score = poi_styles.style_score(world, cfg, 7, "farm")
    assert score[15, 32] > score[15, 50]


def test_a_hamlet_is_not_a_settlement_for_the_distance_terms() -> None:
    # near_target is false on the hamlet tier, so a hamlet does not pull farms towards itself.
    world = _island()
    world.pois.append(POI(kind="hamlet", x=30, y=15, interior_seed=1, civilized=True, pop=30))
    world.poi_index[15, 30] = 0
    fields = poi_styles.style_fields(world, load_config(None), 7)
    assert not np.isfinite(fields.settlement_km).any()


def test_distances_are_km_on_an_anisotropic_grid() -> None:
    # Cells 30 km wide and 60 km tall: two columns and one row away are the same 60 km, so they score the same.
    world = _island(km_per_col=30.0, km_per_row=60.0)
    _village(world, 30, 15)
    cfg = _config(near_settlement=1.0, near_settlement_km=100.0)
    score = poi_styles.style_score(world, cfg, 7, "farm")
    assert np.isclose(score[15, 32], score[16, 30])


def test_fertility_follows_the_habitability_grid() -> None:
    # A style that weights only fertility scores a fertile biome above a barren one (both listed as eligible).
    world = _island()
    world.biome[10:20, 10:20] = int(Biome.DESERT)
    cfg = _config(biomes=["grass", "desert"], fertility=1.0)
    score = poi_styles.style_score(world, cfg, 7, "farm")
    assert score[15, 40] > score[15, 15]


def test_roughness_scores_hills_above_flat_land() -> None:
    from biomegen.world.tile import Relief

    world = _island()
    world.relief[10:20, 10:20] = int(Relief.MOUNTAIN)
    cfg = _config("mine", relief=1.0)
    score = poi_styles.style_score(world, cfg, 7, "mine")
    assert score[15, 15] > score[15, 40]


def test_forest_cover_raises_the_forest_term() -> None:
    world = _island()
    world.biome[8:22, 8:22] = int(Biome.FOREST)
    cfg = _config("lodge", biomes=["grass", "forest"], forest=1.0)
    score = poi_styles.style_score(world, cfg, 7, "lodge")
    assert score[15, 15] > score[15, 50]


def test_a_style_that_needs_fresh_water_is_eligible_only_near_it() -> None:
    world = _island()
    world.water_type[:, 30] = int(WaterType.FRESH)
    cfg = _config("mill", needs_freshwater_km=40.0)
    score = poi_styles.style_score(world, cfg, 7, "mill")
    assert np.isfinite(score[15, 31]) and not np.isfinite(score[15, 45])


def test_a_style_that_needs_the_coast_is_eligible_only_near_it() -> None:
    world = _island()
    world.dist_to_ocean[:] = np.abs(np.arange(world.width)[None, :] - 3) * 30.0
    cfg = _config("fishery", needs_coast_km=60.0)
    score = poi_styles.style_score(world, cfg, 7, "fishery")
    assert np.isfinite(score[15, 5]) and not np.isfinite(score[15, 40])


def test_a_growing_style_keeps_room_for_the_larger_plan() -> None:
    # The footprint is the larger of the homestead site and the tier it grows into, each way.
    cfg = load_config(None)
    farm = poi_styles.style_footprint(cfg, "farm")
    hamlet = poi_styles.pois.max_footprint(cfg, "hamlet")
    homestead = poi_styles.pois.max_footprint(cfg, "homestead", "farm")
    assert farm is not None and hamlet is not None and homestead is not None
    assert farm == (max(hamlet[0], homestead[0]), max(hamlet[1], homestead[1]))


def test_suited_land_scores_at_least_min_score() -> None:
    world = _island()
    _village(world, 30, 15)
    cfg = _config(near_settlement=1.0, near_settlement_km=100.0, min_score=0.5)
    score = poi_styles.style_score(world, cfg, 7, "farm")
    suited = poi_styles.suited_mask(cfg, "farm", score)
    assert suited[15, 31] and not suited[15, 55]


def test_count_is_suited_land_over_km2_per_poi() -> None:
    world = _island()
    cfg = _config(homestead_km2_per_poi=100000.0)
    score = poi_styles.style_score(world, cfg, 7, "farm")
    land_km2 = float(np.isfinite(score).sum()) * world.scale.cell_area_km2
    assert poi_styles.style_count(world, cfg, "farm", "homestead", score) == round(land_km2 / 100000.0)


def test_density_multiplies_the_count() -> None:
    world = _island()
    cfg = _config(homestead_km2_per_poi=100000.0)
    score = poi_styles.style_score(world, cfg, 7, "farm")
    raw = float(np.isfinite(score).sum()) * world.scale.cell_area_km2 / 100000.0
    cfg.data["poi"]["density"] = 2.0
    assert poi_styles.style_count(world, cfg, "farm", "homestead", score) == round(2.0 * raw)


def test_a_kind_the_style_does_not_make_has_no_count() -> None:
    # Mine has no hamlet_km2_per_poi: it makes no hamlets at generation.
    world, cfg = _island(), load_config(None)
    score = poi_styles.style_score(world, cfg, 7, "mine", "hamlet")
    assert poi_styles.style_count(world, cfg, "mine", "hamlet", score) == 0

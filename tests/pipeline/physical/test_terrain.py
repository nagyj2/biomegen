"""Tests for the terrain stage: styles, rank-based sea level, metres and the ocean frame."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.defaults import get_defaults
from biomegen.config.model import Config
from biomegen.config.validate import ConfigError, validate
from biomegen.pipeline.physical import terrain
from biomegen.util import rng
from biomegen.util.units import grid_scale
from biomegen.world.tile import WaterType
from biomegen.world.world import World

WIDTH, HEIGHT = 96, 48


def _config(**terrain_keys: object) -> Config:
    cfg = load_config(None)
    cfg.data["terrain"].update(terrain_keys)
    return cfg


def _run(cfg: Config, seed: int = 42) -> World:
    world = World(WIDTH, HEIGHT, seed, grid_scale(WIDTH, HEIGHT, (6000.0, 3000.0), 35.0, 0.0))
    terrain.run(world, cfg, seed)
    return world


@pytest.fixture(scope="module")
def world() -> World:
    return _run(load_config(None))


@pytest.mark.parametrize("style", ["continents", "pangaea", "archipelago", "islands"])
def test_land_fraction_matches_style(style: str) -> None:
    # Rank-based sea level: with no jitter, the land share is the style's land_fraction (within one cell).
    cfg = _config(style=style, land_fraction_jitter=0.0)
    target = cfg.get(f"tables.styles.{style}.land_fraction")
    assert terrain.land_fraction(_run(cfg)) == pytest.approx(target, abs=1.0 / (WIDTH * HEIGHT))


def test_terrain_is_deterministic() -> None:
    cfg = load_config(None)
    assert _run(cfg, 7).fingerprint() == _run(cfg, 7).fingerprint()


def test_map_edges_are_sea(world: World) -> None:
    # The ocean frame pushes every border cell below sea level.
    land = world.water_type == int(WaterType.NONE)
    assert not (land[0, :].any() or land[-1, :].any() or land[:, 0].any() or land[:, -1].any())


def test_land_is_above_and_sea_below_zero_metres(world: World) -> None:
    land = world.water_type == int(WaterType.NONE)
    assert (world.elevation_m[land] > 0).all() and (world.elevation_m[~land] < 0).all()


def test_summit_and_deepest_sea_fall_in_configured_ranges(world: World) -> None:
    cfg = load_config(None)
    lo, hi = cfg.get("terrain.max_elevation_m")
    deep_lo, deep_hi = cfg.get("terrain.max_depth_m")
    assert lo <= world.elevation_m.max() <= hi and deep_lo <= -world.elevation_m.min() <= deep_hi


def test_median_land_height_follows_hypsometric_curve(world: World) -> None:
    # The curve puts rank 0.4 at 180 m and rank 0.65 at 420 m, so the median land cell lies between.
    land = world.water_type == int(WaterType.NONE)
    assert 180.0 <= float(np.median(world.elevation_m[land])) <= 420.0


def test_dist_to_ocean_is_zero_at_sea_and_positive_on_land(world: World) -> None:
    land = world.water_type == int(WaterType.NONE)
    assert (world.dist_to_ocean[~land] == 0).all() and (world.dist_to_ocean[land] > 0).all()


def test_dist_to_ocean_is_in_km(world: World) -> None:
    # A land cell beside the sea is one cell away, so the smallest land distance is the shorter cell side in km.
    land = world.water_type == int(WaterType.NONE)
    shortest_cell_km = min(world.scale.km_per_col, world.scale.km_per_row)
    assert float(world.dist_to_ocean[land].min()) == pytest.approx(shortest_cell_km, rel=1e-4)


def test_pinned_style_is_used() -> None:
    assert _run(_config(style="islands")).terrain_style == "islands"


def test_seed_style_never_draws_zero_weight_rows() -> None:
    cfg = _config(style="seed")
    for name in ("continents", "pangaea", "archipelago"):
        cfg.data["tables"]["styles"][name]["weight"] = 0.0
    assert {terrain.pick_style(cfg, rng.derive(s, "terrain")) for s in range(40)} == {"islands"}


def test_seed_style_draws_several_styles() -> None:
    cfg = load_config(None)
    assert len({terrain.pick_style(cfg, rng.derive(s, "terrain")) for s in range(40)}) > 1


def test_unknown_style_is_rejected() -> None:
    cfg = get_defaults()
    cfg["terrain"]["style"] = "atolls"
    with pytest.raises(ConfigError, match="terrain.style"):
        validate(cfg)


def test_seed_style_needs_a_positive_weight() -> None:
    cfg = get_defaults()
    for row in cfg["tables"]["styles"].values():
        row["weight"] = 0.0
    with pytest.raises(ConfigError, match="weight > 0"):
        validate(cfg)

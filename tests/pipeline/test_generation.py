"""Golden-world + sanity tests for the generation pipeline.

The "golden" guarantee is expressed as a *property* rather than a brittle hard-coded digest: the same
seed must produce a byte-identical world (a) on repeated calls and (b) across processes with
different ``PYTHONHASHSEED`` (proving nothing in generation leaks Python's salted ``hash()`` or set
ordering). This stays valid as later phases add fields, while still catching accidental nondeterminism.
"""

from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.util.units import KM_PER_DEGREE
from biomegen.world.tile import WATER_BIOMES, Biome, WaterType
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def test_generation_is_deterministic_in_process(cfg: Config) -> None:
    assert pipeline.generate(cfg, 12345).fingerprint() == pipeline.generate(cfg, 12345).fingerprint()


def test_generation_independent_of_pythonhashseed() -> None:
    """The golden test: the world fingerprint for a fixed seed is invariant to PYTHONHASHSEED."""
    code = (
        "from biomegen.config import load_config;"
        "from biomegen import pipeline;"
        "print(pipeline.generate(load_config(None), 12345).fingerprint())"
    )
    fingerprints = []
    for hashseed in ("0", "1", "98765"):
        env = dict(os.environ, PYTHONHASHSEED=hashseed)
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        fingerprints.append(result.stdout.strip())
    assert len(set(fingerprints)) == 1, f"world varied with PYTHONHASHSEED: {fingerprints}"


def test_different_seeds_produce_different_worlds(cfg: Config) -> None:
    fps = {pipeline.generate(cfg, s).fingerprint() for s in (1, 2, 3, 4, 5)}
    assert len(fps) == 5


def test_world_has_land_and_ocean_and_regions(cfg: Config) -> None:
    world = pipeline.generate(cfg, 777)
    land = world.water_type == int(WaterType.NONE)
    ocean = world.water_type == int(WaterType.SALT)
    assert land.mean() >= float(cfg.get("world.min_land_fraction"))
    assert ocean.any()
    assert len(world.regions) > 0
    # Every land tile carries a valid region id except none should be left at the ocean sentinel
    # unless it is genuinely water.
    assert (world.region_id[land] >= 0).all()


def test_water_classification_salt_vs_fresh(cfg: Config) -> None:
    world = pipeline.generate(cfg, 9999)
    sea = np.isin(world.biome, [int(Biome.DEEP), int(Biome.SHALLOW)])
    lake = world.biome == int(Biome.LAKE)
    # Open sea is salt; lakes are fresh.
    assert (world.water_type[sea] == int(WaterType.SALT)).all()
    if lake.any():
        assert (world.water_type[lake] == int(WaterType.FRESH)).all()


def test_beaches_only_border_the_ocean(cfg: Config) -> None:
    world = pipeline.generate(cfg, 9999)
    beach = world.biome == int(Biome.BEACH)
    # Beaches touch the sea (an 8-neighbour is salt water), so they never ring a lake or sit inland.
    salt = np.pad(world.water_type == int(WaterType.SALT), 1)
    h, w = beach.shape
    near_sea = np.zeros_like(beach)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            near_sea |= salt[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    assert beach.any() and near_sea[beach].all()


def test_small_world_generates(cfg: Config) -> None:
    small = load_config(None)
    small.data["world"]["width"] = 48
    small.data["world"]["height"] = 30
    world = pipeline.generate(small, 5)
    assert world.width == 48 and world.height == 30
    assert (world.water_type == int(WaterType.SALT)).any()


def test_stats_reports_expected_keys(cfg: Config) -> None:
    st = pipeline.stats(pipeline.generate(cfg, 1))
    for key in ("size", "land_fraction", "biomes", "regions", "rivers", "lakes", "fingerprint"):
        assert key in st


def _count_islands(world: World) -> int:
    from scipy import ndimage

    from biomegen.world.tile import WaterType

    land = world.water_type == int(WaterType.NONE)
    labels, _ = ndimage.label(land, structure=np.ones((3, 3)))  # type: ignore[misc]
    sizes = np.bincount(labels.ravel())[1:]
    return int((sizes >= 8).sum())


def test_archipelago_can_produce_multiple_islands(cfg: Config) -> None:
    """With archipelago shaping on, at least some seeds yield more than one sizeable landmass."""
    counts = [_count_islands(pipeline.generate(cfg, s)) for s in (1, 2, 3, 9999, 2024)]
    assert max(counts) >= 2


def test_deserts_appear_for_some_seeds(cfg: Config) -> None:
    """The drier climate produces desert somewhere across a handful of seeds."""
    any_desert = any((pipeline.generate(cfg, s).biome == int(Biome.DESERT)).any() for s in (2, 9999, 123456, 88, 2024))
    assert any_desert


def _max_river_run(world: World) -> int:
    """Return the widest contiguous run of river tiles along any row (a width proxy)."""
    river = (world.water_type == int(WaterType.FRESH)) & ~np.isin(world.biome, sorted(WATER_BIOMES))
    best = 0
    for row in river:
        run = 0
        for v in row.tolist():
            run = run + 1 if v else 0
            best = max(best, run)
    return best


def test_rivers_can_span_multiple_tiles(cfg: Config) -> None:
    """Great rivers widen with drainage area, so at least some seeds have multi-tile-wide rivers."""
    assert max(_max_river_run(pipeline.generate(cfg, s)) for s in (1, 42, 55, 2024)) >= 2


def test_invalid_biome_name_in_config_raises() -> None:
    from biomegen.config.defaults import get_defaults
    from biomegen.config.validate import ConfigError, validate

    bad = get_defaults()
    bad["biomes"]["bands"][3]["biome"] = "frest"  # typo
    with pytest.raises(ConfigError) as exc:
        validate(bad)
    assert "unknown biome" in str(exc.value) and "frest" in str(exc.value)


def test_generate_sizes_cells_from_size_km() -> None:
    # world.size_km spread over the grid sets the World's cell size.
    small = load_config(None)
    small.data["world"].update({"width": 48, "height": 30, "size_km": [960.0, 900.0]})
    world = pipeline.generate(small, 5)
    assert (world.km_per_col, world.km_per_row) == (20.0, 30.0)


def test_generate_places_map_at_center_lat() -> None:
    # The top edge sits half the map's latitude span above world.center_lat.
    small = load_config(None)
    small.data["world"].update({"width": 48, "height": 30, "size_km": [960.0, 900.0], "center_lat": -20.0})
    world = pipeline.generate(small, 5)
    assert world.lat_top == pytest.approx(-20.0 + 450.0 / KM_PER_DEGREE)


def test_center_lat_number_pins_the_latitude(cfg: Config) -> None:
    pinned = load_config(None)
    pinned.data["world"]["center_lat"] = 12.5
    assert pipeline.center_lat(pinned, 1) == 12.5


def test_center_lat_seed_is_reproducible(cfg: Config) -> None:
    assert pipeline.center_lat(cfg, 777) == pipeline.center_lat(cfg, 777)


def test_center_lat_seed_stays_in_range(cfg: Config) -> None:
    # "seed" draws |latitude| from world.center_lat_range_deg (default 18..48).
    lo, hi = cfg.get("world.center_lat_range_deg")
    assert all(lo <= abs(pipeline.center_lat(cfg, s)) <= hi for s in range(200))


def test_center_lat_seed_uses_both_hemispheres(cfg: Config) -> None:
    signs = {pipeline.center_lat(cfg, s) > 0 for s in range(50)}
    assert signs == {True, False}


def test_timings_cover_every_stage_without_changing_the_world() -> None:
    # scripts/bench.sh reads per-stage seconds from generate(timings=...); timing never alters the world.
    small = load_config(None)
    small.data["world"].update({"width": 48, "height": 24})
    timings: dict[str, float] = {}
    timed = pipeline.generate(small, 3, timings)
    stages = {"terrain", "climate", "hydrology", "biomes", "geography", "regions"}
    assert stages <= set(timings) and all(v >= 0 for v in timings.values())
    assert timed.fingerprint() == pipeline.generate(small, 3).fingerprint()

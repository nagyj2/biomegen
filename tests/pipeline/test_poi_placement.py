"""Tests for POI placement (counts, spacing, region references, determinism)."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.world.tile import WaterType


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    return pipeline.generate(cfg, 9999)


# --------------------------------------------------------------------------- POI placement
def test_poi_counts_within_target(world, cfg):
    from collections import Counter

    counts = Counter(p.kind for p in world.pois)
    for kind, raw in cfg.get("poi.types").items():
        assert counts.get(kind, 0) <= int(raw["count"])  # spacing may reduce, never exceed


def test_poi_index_and_region_refs_consistent(world):
    for i, p in enumerate(world.pois):
        assert int(world.poi_index[p.y, p.x]) == i  # anchor points back at the POI
        if p.region_id >= 0:
            assert i in world.regions[p.region_id].poi_indices  # region knows its POI


def test_no_duplicate_region_poi_indices(world):
    for r in world.regions:
        assert len(r.poi_indices) == len(set(r.poi_indices))  # single-writer => no dupes


def test_land_pois_on_land_boats_on_water(world):
    for p in world.pois:
        if p.kind == "boat":
            assert world.water_type[p.y, p.x] != int(WaterType.NONE)
        elif p.kind != "bridge":
            assert world.water_type[p.y, p.x] == int(WaterType.NONE)


def test_min_spacing_respected_per_kind(world, cfg):
    types = cfg.get("poi.types")
    by_kind = {}
    for p in world.pois:
        by_kind.setdefault(p.kind, []).append((p.x, p.y))
    for kind, pts in by_kind.items():
        spacing = int(types[kind]["min_spacing"]) if kind in types else 0
        for a in range(len(pts)):
            for b in range(a + 1, len(pts)):
                d2 = (pts[a][0] - pts[b][0]) ** 2 + (pts[a][1] - pts[b][1]) ** 2
                assert d2 >= spacing**2 - 1e-6


def test_placement_deterministic(cfg):
    a = [(p.kind, p.x, p.y) for p in pipeline.generate(cfg, 4242).pois]
    b = [(p.kind, p.x, p.y) for p in pipeline.generate(cfg, 4242).pois]
    assert a == b


# --------------------------------------------------------------------------- elevation limits in metres
def test_pois_respect_their_metre_elevation_limits(world, cfg):
    # Every placed POI anchor sits within its kind's elevation_min_m / elevation_max_m band.
    for p in world.pois:
        rule = cfg.get(f"poi.types.{p.kind}", {})
        height = float(world.elevation_m[p.y, p.x])
        assert height >= rule.get("elevation_min_m", float("-inf"))
        assert height <= rule.get("elevation_max_m", float("inf"))


def test_eligibility_mask_applies_elevation_m():
    # A rule capped at 500 m rejects the cells above it on an east-rising slope.
    import numpy as np

    from biomegen.pipeline.poi_rules import eligibility_mask, parse_rule
    from biomegen.world.tile import Biome
    from biomegen.world.world import World

    world = World(10, 3, 1)
    world.water_type[:] = int(WaterType.NONE)
    world.biome[:] = int(Biome.GRASS)
    world.elevation_m[:] = 100.0 * np.arange(10)[None, :]
    rule = parse_rule("village", {"count": 1, "biomes": ["grass"], "elevation_max_m": 500.0})
    mask = eligibility_mask(rule, world)
    assert mask[:, :6].all() and not mask[:, 6:].any()

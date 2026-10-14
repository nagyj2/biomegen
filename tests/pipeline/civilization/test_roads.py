"""Tests for road generation and bridges (ocean spans, bridge geometry, A* bounds, determinism)."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.util import geometry as geo
from biomegen.world.tile import WaterType


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    return pipeline.generate(cfg, 9999)


# --------------------------------------------------------------------------- roads + bridges
def test_roads_never_cross_long_ocean_spans(cfg):
    # Short coastal hops (≤ _MAX_OCEAN_BRIDGE tiles) are allowed; longer open-ocean crossings are not.
    from biomegen.pipeline.civilization.roads import _MAX_OCEAN_BRIDGE

    for s in (1, 9999, 2024, 55):
        w = pipeline.generate(cfg, s)
        ocean_road = (w.road != 0) & (w.water_type == int(WaterType.SALT))
        if not ocean_road.any():
            continue
        labels, _ = geo.label_by_value(ocean_road.astype(np.uint8), connectivity=4)
        component_sizes = np.bincount(labels.ravel())
        # component 0 is background; check all foreground runs
        max_run = int(component_sizes[1:].max()) if len(component_sizes) > 1 else 0
        assert max_run <= _MAX_OCEAN_BRIDGE, (
            f"seed {s}: ocean road run of {max_run} tiles exceeds limit of {_MAX_OCEAN_BRIDGE}"
        )


def test_bridges_sit_on_water_and_are_flagged_road(world):
    for p in world.pois:
        if p.kind == "bridge":
            assert world.water_type[p.y, p.x] != int(WaterType.NONE)
            assert world.road[p.y, p.x] != 0


def test_roads_deterministic(cfg):
    assert np.array_equal(pipeline.generate(cfg, 55).road, pipeline.generate(cfg, 55).road)


def test_astar_max_expansions_bails(cfg):
    w, h = 40, 40

    def nbrs(n):
        return geo.neighbors8(n[0], n[1], w, h)

    def cost(a, b):
        return 1.0

    # Uncapped: a path exists.
    assert geo.astar((0, 0), (39, 39), nbrs, cost) is not None
    # Tiny cap: the search bails out and returns None.
    assert geo.astar((0, 0), (39, 39), nbrs, cost, max_expansions=5) is None


def test_bridges_have_span_geometry(world):
    # Every bridge stores the two road pieces it joins (p0/p1) so the renderer can draw a straight deck.
    bridges = [p for p in world.pois if p.kind == "bridge"]
    for b in bridges:
        assert "p0" in b.extra and "p1" in b.extra
        assert len(b.extra["p0"]) == 2 and len(b.extra["p1"]) == 2


def test_bridges_do_not_overlap():
    # Two roads fording the same water must not stack overlapping bridge decks: every bridge's spanned
    # water tiles (run + straight deck line) are disjoint from every other bridge's.
    from biomegen.pipeline.civilization.roads import _bresenham

    cfg = load_config(None)
    w = pipeline.generate(cfg, 12636298121517995018)  # the seed that exhibited stacked bridges
    seen: set = set()
    for b in (p for p in w.pois if p.kind == "bridge"):
        p0, p1 = tuple(b.extra["p0"]), tuple(b.extra["p1"])
        water = {
            (x, y) for (x, y) in _bresenham(p0, p1) if w.in_bounds(x, y) and w.water_type[y, x] != int(WaterType.NONE)
        }
        assert not (water & seen), f"bridge at {(b.x, b.y)} overlaps an existing bridge deck"
        seen |= water

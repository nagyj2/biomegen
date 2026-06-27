"""Tests for Phase 4: POI placement, roads + bridges, naming + lore, and detail-view markers."""

from __future__ import annotations

import random

import numpy as np
import pytest
from biomegen import pipeline
from biomegen.config import load_config
from biomegen.pipeline import naming
from biomegen.render.state import ViewState, edge_pan
from biomegen.render.zoom_view import build_detail_frame, detail_cell_size
from biomegen.util import geometry as geo
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


# --------------------------------------------------------------------------- roads + bridges
def test_roads_never_cross_long_ocean_spans(cfg):
    # Short coastal hops (≤ _MAX_OCEAN_BRIDGE tiles) are allowed; longer open-ocean crossings are not.
    from biomegen.pipeline.roads import _MAX_OCEAN_BRIDGE

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


# --------------------------------------------------------------------------- naming + lore
def test_island_and_regions_named(world):
    assert world.island_name
    assert all(r.name for r in world.regions)


def test_region_lore_nonempty(world, cfg):
    lore_min = int(cfg.get("naming.lore_min"))
    for r in world.regions:
        assert len(r.lore) >= lore_min


def test_named_pois_have_names_bridges_unnamed(world):
    for p in world.pois:
        if p.kind == "bridge":
            assert p.name == ""
        else:
            assert p.name


def test_naming_is_order_invariant(cfg):
    """Shuffling the entity lists before naming must not change any name (identity-keyed)."""
    w = pipeline.generate(cfg, 777)
    before = (w.island_name, {r.id: r.name for r in w.regions}, {(p.x, p.y): p.name for p in w.pois})
    w2 = pipeline.generate(cfg, 777)
    random.Random(1).shuffle(w2.regions)
    random.Random(2).shuffle(w2.pois)
    naming.run(w2, cfg, w2.seed)
    after = (w2.island_name, {r.id: r.name for r in w2.regions}, {(p.x, p.y): p.name for p in w2.pois})
    assert before == after


def test_naming_does_not_change_fingerprint(cfg):
    """Names live on entities, not arrays, so re-running naming must not alter the world fingerprint."""
    w = pipeline.generate(cfg, 321)
    fp = w.fingerprint()
    naming.run(w, cfg, w.seed)
    assert w.fingerprint() == fp


# --------------------------------------------------------------------------- detail-view markers
def test_detail_view_stamps_poi_marker(world, cfg):
    # A marker-only POI (a bridge has no interior builder) still shows its glyph at the detail scale.
    # Interior-bearing POIs (settlements, dungeons, ...) intentionally replace their marker with the
    # rendered interior at this scale - that is covered in test_interiors, not here.
    poi = next(p for p in world.pois if p.kind == "bridge")
    aw, ah = 80, 24
    cw, ch = detail_cell_size("local", cfg, aw, ah)
    vs = ViewState(cx=poi.x, cy=poi.y, scale="local")
    vs.cam_x = edge_pan(0, vs.cx, max(1, aw // cw), world.width)
    vs.cam_y = edge_pan(0, vs.cy, max(1, ah // ch), world.height)
    frame = build_detail_frame(world, cfg, vs, aw, ah, cw, ch)
    glyphs_drawn = {g for row in frame.cells for (g, _b) in row}
    assert cfg.get("render.markers")[poi.kind] in glyphs_drawn


# --------------------------------------------------------------------------- road / bridge rendering
def _detail_frame_at(world, cfg, x, y, scale="local", aw=120, ah=48):
    cw, ch = detail_cell_size(scale, cfg, aw, ah)
    vs = ViewState(cx=x, cy=y, scale=scale, mode="onetoone")
    vs.cam_x = edge_pan(0, x, max(1, aw // cw), world.width)
    vs.cam_y = edge_pan(0, y, max(1, ah // ch), world.height)
    return build_detail_frame(world, cfg, vs, aw, ah, cw, ch), cw, ch, vs


def test_bridges_have_span_geometry(world):
    # Every bridge stores the two road pieces it joins (p0/p1) so the renderer can draw a straight deck.
    bridges = [p for p in world.pois if p.kind == "bridge"]
    for b in bridges:
        assert "p0" in b.extra and "p1" in b.extra
        assert len(b.extra["p0"]) == 2 and len(b.extra["p1"]) == 2


def test_bridges_do_not_overlap():
    # Two roads fording the same water must not stack overlapping bridge decks: every bridge's spanned
    # water tiles (run + straight deck line) are disjoint from every other bridge's.
    from biomegen.pipeline.roads import _bresenham

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


def test_road_bed_is_thin_not_full_tile():
    # A road renders as a thin bed (a fraction of a tile), not a marker filling the whole tile block.
    from biomegen.world.tile import COLOR_ROAD, Biome
    from biomegen.world.world import World

    cfg = load_config(None)
    w = World(12, 9, 7)
    w.biome[:] = int(Biome.GRASSLAND)
    w.road[4, 1:11] = 1  # a straight horizontal road on tile-row 4
    frame, cw, ch, vs = _detail_frame_at(w, cfg, 5, 4, scale="zoom", aw=12 * 8, ah=9 * 8)
    # Inspect the detail-cell block of road tile (5, 4): it must contain road cells but not be filled.
    r0, c0 = (4 - vs.cam_y) * ch, (5 - vs.cam_x) * cw
    block = [frame.cells[r][c][1] == COLOR_ROAD for r in range(r0, r0 + ch) for c in range(c0, c0 + cw)]
    assert any(block), "road tile should render some road bed"
    assert not all(block), "road bed must not occupy the entire tile"


def test_road_and_bridge_overlay_colours_render():
    # A view over a bridge shows the road bed, the brown deck and its flanking walls (distinct colours).
    from biomegen.world.tile import COLOR_BRIDGE_DECK, COLOR_BRIDGE_WALL, COLOR_ROAD

    cfg = load_config(None)
    w = pipeline.generate(cfg, 1)  # seed 1 reliably has road-connected bridges
    bridge = next(p for p in w.pois if p.kind == "bridge")
    frame, _cw, _ch, _vs = _detail_frame_at(w, cfg, bridge.x, bridge.y, scale="local")
    ids = {cid for row in frame.cells for (_g, cid) in row}
    assert COLOR_ROAD in ids  # road bed leading to the bridge
    assert COLOR_BRIDGE_DECK in ids  # brown deck
    assert COLOR_BRIDGE_WALL in ids  # flanking walls

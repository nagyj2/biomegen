"""Tests for detail-view (zoom/local) rendering of markers, roads and bridges."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.render.state import ViewState, edge_pan
from biomegen.render.zoom_view import build_detail_frame, detail_cell_size


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    return pipeline.generate(cfg, 9999)


# --------------------------------------------------------------------------- detail-view markers
def test_detail_view_stamps_poi_marker(world, cfg):
    # A marker-only POI (a bridge has no interior builder) still shows its glyph at the detail scale.
    # Interior-bearing POIs (settlements, dungeons, ...) intentionally replace their marker with the
    # rendered interior at this scale - that is covered in test_interiors, not here. A bridge inside a
    # neighbouring settlement's footprint is drawn by that interior, so any bridge showing it suffices.
    aw, ah = 80, 24
    cw, ch = detail_cell_size("local", cfg, aw, ah)

    def marker_drawn(poi) -> bool:
        vs = ViewState(cx=poi.x, cy=poi.y, scale="local")
        vs.cam_x = edge_pan(0, vs.cx, max(1, aw // cw), world.width)
        vs.cam_y = edge_pan(0, vs.cy, max(1, ah // ch), world.height)
        frame = build_detail_frame(world, cfg, vs, aw, ah, cw, ch)
        return cfg.get("render.markers")[poi.kind] in {g for row in frame.cells for (g, _b) in row}

    assert any(marker_drawn(p) for p in world.pois if p.kind == "bridge")


# --------------------------------------------------------------------------- road / bridge rendering
def _detail_frame_at(world, cfg, x, y, scale="local", aw=120, ah=48):
    cw, ch = detail_cell_size(scale, cfg, aw, ah)
    vs = ViewState(cx=x, cy=y, scale=scale, mode="onetoone")
    vs.cam_x = edge_pan(0, x, max(1, aw // cw), world.width)
    vs.cam_y = edge_pan(0, y, max(1, ah // ch), world.height)
    return build_detail_frame(world, cfg, vs, aw, ah, cw, ch), cw, ch, vs


def test_road_bed_is_thin_not_full_tile():
    # A road renders as a thin bed (a fraction of a tile), not a marker filling the whole tile block.
    from biomegen.world.tile import COLOR_ROAD, Biome
    from biomegen.world.world import World

    cfg = load_config(None)
    w = World(12, 9, 7)
    w.biome[:] = int(Biome.GRASS)
    w.road[4, 1:11] = 1  # a straight horizontal road on tile-row 4
    frame, cw, ch, vs = _detail_frame_at(w, cfg, 5, 4, scale="zoom", aw=12 * 8, ah=9 * 8)
    # Inspect the detail-cell block of road tile (5, 4): it must contain road cells but not be filled.
    r0, c0 = (4 - vs.cam_y) * ch, (5 - vs.cam_x) * cw
    block = [frame.cells[r][c][1] == COLOR_ROAD for r in range(r0, r0 + ch) for c in range(c0, c0 + cw)]
    assert any(block), "road tile should render some road bed"
    assert not all(block), "road bed must not occupy the entire tile"


def test_road_and_bridge_overlay_colours_render():
    # A view over a bridge shows the road bed, the brown deck and its flanking walls (distinct colours).
    from biomegen.world.tile import COLOR_BRIDGE_DECK, COLOR_ROAD

    cfg = load_config(None)
    w = pipeline.generate(cfg, 1)  # seed 1 has road-connected bridges

    def colour_ids(bridge) -> set:
        frame, _cw, _ch, _vs = _detail_frame_at(w, cfg, bridge.x, bridge.y, scale="local")
        return {cid for row in frame.cells for (_g, cid) in row}

    # Some bridge view shows both the road bed leading to it and the brown deck.
    assert any({COLOR_ROAD, COLOR_BRIDGE_DECK} <= colour_ids(p) for p in w.pois if p.kind == "bridge")

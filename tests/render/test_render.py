"""Tests for the pure (curses-free) rendering logic: camera, frame construction, preview."""

from __future__ import annotations

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.render import preview
from biomegen.render.map_view import build_biome_frame, fit_blocks
from biomegen.render.state import ViewState, clamp, edge_pan
from biomegen.render.zoom_view import build_detail_frame, detail_cell_size


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(20, 0, 10) == 10
    assert clamp(5, 10, 0) == 10  # degenerate range returns lo


def test_edge_pan_holds_until_edge_then_scrolls():
    # World 100 wide, viewport 10, margin 1. Cursor near the middle of the viewport => no scroll.
    assert edge_pan(0, 5, 10, 100, margin=1) == 0
    # Cursor at the right edge => scroll right.
    cam = edge_pan(0, 9, 10, 100, margin=1)
    assert cam > 0
    # Clamped at the world's right edge.
    assert edge_pan(90, 99, 10, 100, margin=1) == 90


def test_edge_pan_centers_small_world():
    # World smaller than the viewport => negative origin to centre with letterboxing.
    assert edge_pan(0, 2, 20, 6, margin=1) == -((20 - 6) // 2)


def test_fit_blocks_dimensions():
    bw, bh, cols, rows = fit_blocks(192, 44, 96, 40)
    assert bw == 2 and bh == 2
    assert cols == 96 and rows == 22


def test_build_biome_frame_fit(small_world, cfg):
    vs = ViewState(cx=small_world.width // 2, cy=small_world.height // 2, mode="fit")
    frame = build_biome_frame(small_world, vs, area_w=40, area_h=20)
    assert frame.rows <= 20 and frame.cols <= 40
    # Cursor maps to a valid screen cell.
    assert frame.cursor is not None
    cc, cr = frame.cursor
    assert 0 <= cc < frame.cols and 0 <= cr < frame.rows


def test_build_biome_frame_onetoone_bounds_and_cursor(small_world):
    # Viewport wider/taller than the (60x40) world so out-of-bounds cells exist at the far edge.
    vs = ViewState(cx=5, cy=5, mode="onetoone", cam_x=0, cam_y=0)
    frame = build_biome_frame(small_world, vs, area_w=80, area_h=50)
    assert frame.cols == 80 and frame.rows == 50
    # The cursor tile sits at (5, 5) in screen space when the camera is at the origin.
    assert frame.cursor == (5, 5)
    # A cell mapping inside the world resolves to a coord; one past the world edge is None.
    assert frame.tiles[0][0] == (0, 0)
    assert frame.tiles[0][small_world.width] is None


def test_build_zoom_frame_magnifies_and_marks_cursor(small_world, cfg):
    cw, ch = detail_cell_size("zoom", cfg, 40, 20)
    vs = ViewState(cx=10, cy=8, scale="zoom", cam_x=8, cam_y=6)
    frame = build_detail_frame(small_world, cfg, vs, 40, 20, cw, ch)
    # The detail grid is a whole number of magnified tiles.
    assert frame.cols == frame.tiles_w * cw
    assert frame.rows == frame.tiles_h * ch
    # Cursor rectangle is one tile's worth of detail cells.
    assert frame.cursor_rect is not None
    x0, y0, x1, y1 = frame.cursor_rect
    assert (x1 - x0) == cw and (y1 - y0) == ch


def test_blend_lookup_is_world_position_function(small_world):
    """The biome blend is a deterministic function of world position (so zoom & local agree)."""
    import numpy as np

    from biomegen.config import load_config
    from biomegen.render.zoom_view import _blended_lookup

    fx = np.linspace(2.0, 8.0, 60).reshape(6, 10)
    fy = np.linspace(2.0, 6.0, 60).reshape(6, 10)

    on = load_config(None)  # blend_strength default > 0
    bx1, by1 = _blended_lookup(small_world, on, fx, fy)
    bx2, by2 = _blended_lookup(small_world, on, fx, fy)
    assert np.array_equal(bx1, bx2) and np.array_equal(by1, by2)  # deterministic

    off = load_config(None)
    off.data["render"]["blend_strength"] = 0.0
    bx0, by0 = _blended_lookup(small_world, off, fx, fy)
    # With blending off the lookup is exactly floor(fx)/floor(fy)...
    assert np.array_equal(bx0, np.clip(np.floor(fx).astype(np.int64), 0, small_world.width - 1))
    # ...and turning it on warps at least some lookups across tile boundaries.
    assert not (np.array_equal(bx1, bx0) and np.array_equal(by1, by0))


def test_water_blend_bridges_diagonal_tiles():
    """Two diagonally-adjacent water tiles connect through the shared corner (no checkerboard)."""
    import numpy as np

    from biomegen.render.zoom_view import _water_blend
    from biomegen.world.tile import Biome, WaterType
    from biomegen.world.world import World

    w = World(5, 5, 1)
    w.biome[:] = int(Biome.GRASS)
    w.water_type[:] = int(WaterType.NONE)
    w.water_type[1, 1] = int(WaterType.FRESH)  # river tile (x=1, y=1): fresh water over grass
    w.water_type[2, 2] = int(WaterType.FRESH)  # tile (x=2, y=2) - only corner-touches the first

    # Sample the shared corner (world 2.0, 2.0) and a neighbouring land-tile centre (2.5, 1.5).
    fx = np.array([[2.0, 2.5]])
    fy = np.array([[2.0, 1.5]])
    is_water, water_biome = _water_blend(w, fx, fy, 0.42)
    assert bool(is_water[0, 0]) is True  # diagonal gap is bridged -> water
    assert int(water_biome[0, 0]) == int(Biome.LAKE)  # rivers draw as lake water until phase 4
    assert bool(is_water[0, 1]) is False  # a land tile centre stays land


def test_local_scale_is_more_magnified_than_zoom(cfg):
    # Verifies local-scale cells are larger than zoom-scale cells in both dimensions.
    cw_zoom, ch_zoom = detail_cell_size("zoom", cfg, 120, 40)
    cw_local, ch_local = detail_cell_size("local", cfg, 120, 40)
    assert cw_local > cw_zoom and ch_local > ch_zoom


def test_local_scale_aspect_correction_widens_cells():
    # Verifies that cell_aspect > 1 produces cells wider than tall (terminal aspect correction).
    cfg = load_config(None)
    cfg.data["render"]["cell_aspect"] = 2.0
    cw, ch = detail_cell_size("local", cfg, 120, 40)
    assert cw > ch


def test_preview_outputs_are_nonempty(small_world, cfg):
    biome_txt = preview.render_biome_ascii(small_world, cfg, area_w=60, area_h=20)
    zoom_txt = preview.render_zoom_ascii(small_world, cfg, area_w=40, area_h=20)
    assert biome_txt.count("\n") >= 1 and len(biome_txt) > 0
    assert zoom_txt.count("\n") >= 1 and len(zoom_txt) > 0


# --- shared fixtures ---
import pytest  # noqa: E402


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def small_world(cfg):
    c = load_config(None)
    c.data["world"]["width"] = 60
    c.data["world"]["height"] = 40
    return pipeline.generate(c, 4321)

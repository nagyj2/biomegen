"""Tests for Phase 5: lazy POI interiors, the dungeon builder, and detail-view rendering."""

from __future__ import annotations

import numpy as np
import pytest
from biomegen import pipeline
from biomegen.config import load_config
from biomegen.pipeline import poi_interiors
from biomegen.render.state import ViewState, edge_pan
from biomegen.render.zoom_view import build_detail_frame, detail_cell_size
from biomegen.world.interiors import STRUCTURAL, ZOOM_VISIBLE, build_interior, footprint_cells, footprint_origin
from biomegen.world.overlay import Overlay
from biomegen.world.tile import INTERIOR_COLOR_BASE, Cell


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    # Seed 1 reliably produces several dungeons (verified across the seed-robustness sweep).
    return pipeline.generate(cfg, 1)


@pytest.fixture(scope="module")
def dungeon(world):
    return next(p for p in world.pois if p.kind == "dungeon" and p.floor_count >= 3)


def _interior_color_ids(frame):
    """Collect the interior Cell ints that appear in a rendered detail frame."""
    return [cid - INTERIOR_COLOR_BASE for row in frame.cells for (_g, cid) in row if cid >= INTERIOR_COLOR_BASE]


def _detail_frame(world, cfg, poi, scale, floor, overlay=None, aw=120, ah=40):
    """Build a detail frame centred on ``poi`` at ``scale``/``floor`` (mirrors the app's camera math)."""
    cw, ch = detail_cell_size(scale, cfg, aw, ah)
    vs = ViewState(cx=poi.x, cy=poi.y, scale=scale, floor=floor)
    vs.cam_x = edge_pan(0, vs.cx, max(1, aw // cw), world.width)
    vs.cam_y = edge_pan(0, vs.cy, max(1, ah // ch), world.height)
    return build_detail_frame(world, cfg, vs, aw, ah, cw, ch, overlay)


# --------------------------------------------------------------------------- builder determinism
def test_build_interior_is_deterministic(dungeon, cfg):
    # Verifies the same (POI, floor) regenerates a byte-identical grid (lazy but reproducible).
    a = build_interior(dungeon, 0, cfg)
    b = build_interior(dungeon, 0, cfg)
    assert np.array_equal(a, b)


def test_build_interior_is_cached_to_same_object(dungeon, cfg):
    # Verifies the LRU cache returns the very same array object, so re-opening a POI is free.
    assert build_interior(dungeon, 0, cfg) is build_interior(dungeon, 0, cfg)


def test_cached_base_is_read_only(dungeon, cfg):
    # Verifies the cached base grid is immutable, so callers can only mutate via the Overlay.
    assert build_interior(dungeon, 0, cfg).flags.writeable is False


def test_no_builder_returns_none(cfg, world):
    # Verifies a POI kind without a registered builder has no interior (renders as its marker).
    boat = next(p for p in world.pois if p.kind == "boat")
    assert build_interior(boat, 0, cfg) is None


# --------------------------------------------------------------------------- floor / stair model
def test_top_floor_has_entrance_door_not_stairs_up(dungeon, cfg):
    # Verifies the ground/entry floor shows a surface DOOR and never STAIRS_UP.
    top = dungeon.lowest_floor + dungeon.floor_count - 1
    grid = build_interior(dungeon, top, cfg)
    assert int(Cell.DOOR) in grid
    assert int(Cell.STAIRS_UP) not in grid


def test_deepest_floor_has_stairs_up_not_down(dungeon, cfg):
    # Verifies the deepest floor can only go up (no STAIRS_DOWN below it).
    grid = build_interior(dungeon, dungeon.lowest_floor, cfg)
    assert int(Cell.STAIRS_UP) in grid
    assert int(Cell.STAIRS_DOWN) not in grid


def _stairs(grid, cell):
    ys, xs = np.where(grid == int(cell))
    return set(zip(xs.tolist(), ys.tolist(), strict=True))


def test_adjacent_floor_stairs_match(dungeon, cfg):
    # Verifies floor f's down-stairs land on the same cell as floor f-1's up-stairs (you descend onto them).
    floors = range(dungeon.lowest_floor, dungeon.lowest_floor + dungeon.floor_count)
    grids = {f: build_interior(dungeon, f, cfg) for f in floors}
    for f in range(dungeon.lowest_floor + 1, dungeon.lowest_floor + dungeon.floor_count):
        assert _stairs(grids[f], Cell.STAIRS_DOWN) == _stairs(grids[f - 1], Cell.STAIRS_UP)


def test_stair_pairs_are_not_all_the_same_cell(dungeon, cfg):
    # Verifies different floor-pairs use DIFFERENT stair cells (stairs aren't pinned to one column).
    links = set()
    for f in range(dungeon.lowest_floor + 1, dungeon.lowest_floor + dungeon.floor_count):
        links |= _stairs(build_interior(dungeon, f, cfg), Cell.STAIRS_DOWN)
    assert len(links) == dungeon.floor_count - 1  # one distinct cell per adjacent floor pair


# --------------------------------------------------------------------------- placement metadata
def test_stage_sets_footprint_and_bbox(world, cfg):
    # Verifies the poi_interiors stage gives dungeons a (size-jittered) footprint and a clamped bbox.
    d = next(p for p in world.pois if p.kind == "dungeon")
    bw, bh = cfg.get("interiors.footprints")["dungeon"]
    jit = float(cfg.get("interiors.size_jitter"))
    fw, fh = d.footprint
    assert max(3, round(bw * (1 - jit))) <= fw <= round(bw * (1 + jit))
    assert max(3, round(bh * (1 - jit))) <= fh <= round(bh * (1 + jit))
    x0, y0, x1, y1 = d.bbox
    assert 0 <= x0 <= x1 < world.width and 0 <= y0 <= y1 < world.height


def test_footprint_size_jitter_is_deterministic(world, cfg):
    # Verifies the per-POI footprint jitter is a reproducible function of the POI's interior_seed.
    from biomegen.util import rng

    bw, bh = cfg.get("interiors.footprints")["dungeon"]
    jit = float(cfg.get("interiors.size_jitter"))
    for d in (p for p in world.pois if p.kind == "dungeon"):
        sr = rng.derive(d.interior_seed, "interior.footprint")
        ew = max(3, round(bw * sr.uniform(1 - jit, 1 + jit)))
        eh = max(3, round(bh * sr.uniform(1 - jit, 1 + jit)))
        assert d.footprint == (ew, eh)


def test_dungeons_have_two_to_five_floors(world):
    # Verifies dungeons descend between 2 and 5 floors (config-driven floor count).
    counts = [p.floor_count for p in world.pois if p.kind == "dungeon"]
    assert counts and all(2 <= c <= 5 for c in counts)


# --------------------------------------------------------------------------- water avoidance
def _footprint_tiles(poi, world):
    """The on-map tiles a POI's footprint covers (centred on the anchor, clamped to the map)."""
    fw, fh = poi.footprint
    tx0, ty0 = poi.x - fw // 2, poi.y - fh // 2
    return [
        (tx, ty)
        for ty in range(max(0, ty0), min(world.height, ty0 + fh))
        for tx in range(max(0, tx0), min(world.width, tx0 + fw))
    ]


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 42, 100])
def test_no_dungeon_footprint_overlaps_water(seed, cfg):
    # Verifies that across seeds, no tile of any dungeon's footprint sits on ocean/lake/river water.
    from biomegen.world.tile import WaterType

    w = pipeline.generate(cfg, seed)
    dungeons = [p for p in w.pois if p.kind == "dungeon"]
    for d in dungeons:
        wet = [(tx, ty) for tx, ty in _footprint_tiles(d, w) if w.water_type[ty, tx] != int(WaterType.NONE)]
        assert not wet, f"dungeon at {(d.x, d.y)} (seed {seed}) covers water tiles {wet}"


def test_water_free_footprint_mask_excludes_window_around_water():
    # Verifies the SAT-based mask is False exactly for tiles whose centred 3x3 window covers a water tile.
    from types import SimpleNamespace

    from biomegen.pipeline.poi_rules import water_free_footprint_mask
    from biomegen.world.tile import WaterType

    water_type = np.full((5, 5), int(WaterType.NONE), dtype=np.int16)
    water_type[2, 2] = int(WaterType.SALT)  # single water tile at (x=2, y=2)
    mask = water_free_footprint_mask(SimpleNamespace(water_type=water_type), 3, 3)
    expected = np.ones((5, 5), dtype=bool)
    expected[1:4, 1:4] = False  # every tile whose 3x3 centred window reaches (2,2) is rejected
    assert np.array_equal(mask, expected)


def test_entrance_stays_at_anchor(world):
    # Verifies entrance is left at the anchor so the roads stage (which routes to it) is unaffected.
    assert all(p.entrance == (p.x, p.y) for p in world.pois)


def test_stage_does_not_change_fingerprint(cfg):
    # Verifies metadata-only stage writes no per-tile arrays (re-running it leaves the world identical).
    w = pipeline.generate(cfg, 321)
    fp = w.fingerprint()
    poi_interiors.run(w, cfg, w.seed)
    assert w.fingerprint() == fp


def test_footprint_geometry(dungeon, cfg):
    # Verifies canonical resolution = footprint tiles x cells_per_tile, centred on the anchor.
    cpt = int(cfg.get("interiors.cells_per_tile"))
    assert footprint_cells(dungeon, cfg) == (dungeon.footprint[0] * cpt, dungeon.footprint[1] * cpt)
    assert footprint_origin(dungeon) == (dungeon.x - dungeon.footprint[0] // 2, dungeon.y - dungeon.footprint[1] // 2)


# --------------------------------------------------------------------------- detail-view rendering
def test_local_renders_full_interior_with_furniture(world, cfg, dungeon):
    # Verifies the local scale draws floors, walls AND furniture (the full interior).
    frame = _detail_frame(world, cfg, dungeon, "local", floor=0)
    drawn = {Cell(c).name for c in _interior_color_ids(frame)}
    assert {"WALL", "FLOOR"} <= drawn
    assert drawn & {"RUBBLE", "BARREL", "CHEST"}  # at least some furniture


def test_zoom_draws_filled_shell_without_furniture(world, cfg, dungeon):
    # Verifies the zoom scale fills the dungeon in (walls AND floor) but suppresses furniture/clutter.
    frame = _detail_frame(world, cfg, dungeon, "zoom", floor=0)
    drawn_ints = set(_interior_color_ids(frame))
    assert {int(Cell.WALL), int(Cell.FLOOR)} <= drawn_ints  # filled-in shell, not just an outline
    assert drawn_ints <= ZOOM_VISIBLE  # but nothing outside the shell set (no furniture)
    furniture = {int(Cell.RUBBLE), int(Cell.CHEST), int(Cell.BARREL), int(Cell.TABLE), int(Cell.SHELF)}
    assert not (drawn_ints & furniture)  # furniture stays a local-only detail


def test_zoom_dungeon_shows_no_terrain_inside_the_shape(world, cfg, dungeon):
    # Verifies that at zoom every NON-VOID interior cell renders as an interior cell (furniture -> floor),
    # so no biome clutter leaks onto the floorplan. VOID cells outside the organic shape still show
    # terrain (the world around the dungeon), so we only check the structure's own cells.
    floor = 0  # entry floor carries furniture in its rooms
    aw, ah = 120, 40
    cw, ch = detail_cell_size("zoom", cfg, aw, ah)
    vs = ViewState(cx=dungeon.x, cy=dungeon.y, scale="zoom", floor=floor)
    vs.cam_x = edge_pan(0, vs.cx, max(1, aw // cw), world.width)
    vs.cam_y = edge_pan(0, vs.cy, max(1, ah // ch), world.height)
    frame = build_detail_frame(world, cfg, vs, aw, ah, cw, ch)

    grid = build_interior(dungeon, floor, cfg)
    gh, gw = grid.shape
    fw, fh = dungeon.footprint
    tx0, ty0 = footprint_origin(dungeon)
    base_row, base_col = (ty0 - vs.cam_y) * ch, (tx0 - vs.cam_x) * cw
    leaks = []
    for dr in range(fh * ch):
        r = base_row + dr
        if not (0 <= r < frame.rows):
            continue
        sy = min(dr * gh // (fh * ch), gh - 1)
        for dc in range(fw * cw):
            c = base_col + dc
            if not (0 <= c < frame.cols):
                continue
            sx = min(dc * gw // (fw * cw), gw - 1)
            if int(grid[sy, sx]) == int(Cell.VOID):
                continue  # VOID is allowed to show terrain (it's outside the structure)
            if frame.cells[r][c][1] < INTERIOR_COLOR_BASE:
                leaks.append((sy, sx))
    assert not leaks  # no non-void interior cell fell back to a terrain (biome) colour


def test_biome_map_marker_is_not_overwritten_by_outline(world, cfg, dungeon):
    # Verifies the dungeon's anchor cell is left un-stamped on the overview so its POI marker wins.
    from biomegen.render.map_view import build_biome_frame

    aw, ah = 50, 30
    vs = ViewState(cx=dungeon.x, cy=dungeon.y, mode="onetoone")
    vs.cam_x = edge_pan(0, vs.cx, aw, world.width)
    vs.cam_y = edge_pan(0, vs.cy, ah, world.height)
    frame = build_biome_frame(world, vs, aw, ah, cfg)
    assert frame.overrides is not None
    acol, arow = dungeon.x - vs.cam_x, dungeon.y - vs.cam_y
    assert 0 <= acol < aw and 0 <= arow < ah
    assert frame.overrides[arow][acol] is None  # marker cell clear -> POI glyph takes precedence
    assert any(s is not None for row in frame.overrides for s in row)  # outline still stamped elsewhere


def test_dungeon_marker_is_replaced_by_interior_at_local(world, cfg, dungeon):
    # Verifies a dungeon shows its interior (not its 'D' map marker) at the detail scale.
    frame = _detail_frame(world, cfg, dungeon, "local", floor=0)
    marker = cfg.get("render.markers")["dungeon"]
    glyphs_on_footprint = {g for row in frame.cells for (g, cid) in row if cid >= INTERIOR_COLOR_BASE}
    assert marker not in glyphs_on_footprint


def test_overlay_edit_is_composited_into_render(world, cfg, dungeon):
    # Verifies runtime Overlay interior edits show up in the rendered frame (base + overlay).
    base = build_interior(dungeon, 0, cfg)
    gh, gw = base.shape
    overlay = Overlay()
    # Rewrite a central block to CHEST so the edit is large enough to survive sampling.
    for yy in range(gh // 2 - 1, gh // 2 + 2):
        for xx in range(gw // 2 - 1, gw // 2 + 2):
            overlay.set_interior(dungeon.interior_seed, 0, xx, yy, int(Cell.CHEST))
    plain = _detail_frame(world, cfg, dungeon, "local", floor=0, overlay=None)
    edited = _detail_frame(world, cfg, dungeon, "local", floor=0, overlay=overlay)
    n_plain = sum(1 for c in _interior_color_ids(plain) if c == int(Cell.CHEST))
    n_edited = sum(1 for c in _interior_color_ids(edited) if c == int(Cell.CHEST))
    assert n_edited > n_plain


def test_top_floor_door_is_on_the_exterior_wall(dungeon, cfg):
    # Verifies the entry door is punched through the outer wall (next to exterior void / the edge).
    top = dungeon.lowest_floor + dungeon.floor_count - 1
    grid = build_interior(dungeon, top, cfg)
    h, w = grid.shape
    doors = list(zip(*np.where(grid == int(Cell.DOOR))[::-1], strict=True))  # (x, y) pairs
    assert doors  # at least one exterior door
    for x, y in doors:
        on_edge = x == 0 or y == 0 or x == w - 1 or y == h - 1
        neigh = [(y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)]
        touches_void = any(0 <= ny < h and 0 <= nx < w and grid[ny, nx] == int(Cell.VOID) for ny, nx in neigh)
        touches_floor = any(0 <= ny < h and 0 <= nx < w and grid[ny, nx] == int(Cell.FLOOR) for ny, nx in neigh)
        assert (on_edge or touches_void) and touches_floor


def _border_reachable_void(grid):
    """Return the boolean mask of VOID cells reachable from the grid border (4-connectivity)."""
    void = grid == int(Cell.VOID)
    h, w = grid.shape
    seen = np.zeros_like(void)
    stack = [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)]
    stack += [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]
    while stack:
        y, x = stack.pop()
        if not (0 <= y < h and 0 <= x < w) or seen[y, x] or not void[y, x]:
            continue
        seen[y, x] = True
        stack += [(y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)]
    return seen


def test_enclosed_void_is_filled_with_wall(dungeon, cfg):
    # Verifies no VOID pocket is walled off: every VOID cell is reachable from outside (else it's wall).
    grid = build_interior(dungeon, 0, cfg)
    void = grid == int(Cell.VOID)
    assert np.array_equal(void, _border_reachable_void(grid))  # all remaining void is exterior


def test_corridors_and_doorways_stay_passable(dungeon, cfg):
    # Verifies every stair/door is mutually reachable over passable cells (furniture never blocks them).
    passable = {int(Cell.FLOOR), int(Cell.RUBBLE), int(Cell.DOOR), int(Cell.STAIRS_UP), int(Cell.STAIRS_DOWN)}
    for f in range(dungeon.lowest_floor, dungeon.lowest_floor + dungeon.floor_count):
        grid = build_interior(dungeon, f, cfg)
        h, w = grid.shape
        marks = [int(Cell.DOOR), int(Cell.STAIRS_UP), int(Cell.STAIRS_DOWN)]
        special = list(zip(*np.where(np.isin(grid, marks))[::-1], strict=True))
        if len(special) < 2:
            continue
        seen = np.zeros((h, w), dtype=bool)
        sx, sy = special[0]
        stack = [(sy, sx)]
        while stack:
            y, x = stack.pop()
            if not (0 <= y < h and 0 <= x < w) or seen[y, x] or int(grid[y, x]) not in passable:
                continue
            seen[y, x] = True
            stack += [(y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)]
        assert all(seen[y, x] for x, y in special)  # all entrances/stairs connected


def test_more_loot_deeper(world, cfg):
    # Verifies "more loot at the bottom": chests are more numerous on deepest floors than entry floors.
    deepest = top = 0
    for d in (p for p in world.pois if p.kind == "dungeon"):
        entry = d.lowest_floor + d.floor_count - 1
        top += int(np.count_nonzero(build_interior(d, entry, cfg) == int(Cell.CHEST)))
        deepest += int(np.count_nonzero(build_interior(d, d.lowest_floor, cfg) == int(Cell.CHEST)))
    assert deepest > top


def test_furniture_has_variety(dungeon, cfg):
    # Verifies rooms hold more than just rubble/barrel/chest (tables, chairs, beds, etc. appear).
    seen = set()
    for f in range(dungeon.lowest_floor, dungeon.lowest_floor + dungeon.floor_count):
        seen |= set(np.unique(build_interior(dungeon, f, cfg)).tolist())
    variety = {int(Cell.TABLE), int(Cell.CHAIR), int(Cell.SHELF), int(Cell.BED), int(Cell.HEARTH), int(Cell.CRATE)}
    assert len(seen & variety) >= 3  # at least a few distinct furniture kinds beyond the basics


def test_biome_map_stamps_dungeon_outline(world, cfg, dungeon):
    # Verifies the overview map draws a scaled structural outline of the dungeon (not just terrain).
    from biomegen.render.map_view import build_biome_frame
    from biomegen.render.state import ViewState, edge_pan

    aw, ah = 50, 30
    vs = ViewState(cx=dungeon.x, cy=dungeon.y, mode="onetoone")
    vs.cam_x = edge_pan(0, vs.cx, aw, world.width)
    vs.cam_y = edge_pan(0, vs.cy, ah, world.height)
    frame = build_biome_frame(world, vs, aw, ah, cfg)
    assert frame.overrides is not None
    stamped = {s[1] - INTERIOR_COLOR_BASE for row in frame.overrides for s in row if s is not None}
    assert stamped  # at least one interior cell was stamped onto the map
    assert stamped <= STRUCTURAL  # the overview shows only the structural outline (walls/doors/stairs)


def test_biome_map_without_config_has_no_overrides(world):
    # Verifies the terrain-only frame path (no config) is unchanged - no interior stamping.
    from biomegen.render.map_view import build_biome_frame
    from biomegen.render.state import ViewState

    vs = ViewState(cx=world.width // 2, cy=world.height // 2, mode="fit")
    assert build_biome_frame(world, vs, 60, 30).overrides is None


def test_overlay_does_not_mutate_cached_base(dungeon, cfg):
    # Verifies compositing an edit over the read-only cached base leaves the base untouched.
    base = build_interior(dungeon, 0, cfg)
    before = base.copy()
    overlay = Overlay()
    overlay.set_interior(dungeon.interior_seed, 0, 1, 1, int(Cell.CHEST))
    overlay.apply_interior(base, dungeon.interior_seed, 0)
    assert np.array_equal(base, before)


# --------------------------------------------------------------------------- dynamic dungeon shapes
def _mask_components(mask):
    """Count the 4-connected True components of a boolean mask (for connectivity assertions)."""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    n = 0
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or seen[sy, sx]:
                continue
            n += 1
            stack = [(sy, sx)]
            while stack:
                y, x = stack.pop()
                if not (0 <= y < h and 0 <= x < w) or seen[y, x] or not mask[y, x]:
                    continue
                seen[y, x] = True
                stack += [(y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)]
    return n


def test_shapes_registry_has_the_expected_algorithms():
    # Verifies the swappable shape registry exposes the documented organic/geometric algorithms.
    from biomegen.world.interiors import SHAPES

    assert {"rectangle", "blob", "cellular", "drunkard", "diamond", "cross"} <= set(SHAPES.names())


@pytest.mark.parametrize("name", ["blob", "cellular", "drunkard", "diamond", "cross"])
def test_each_shape_is_connected_nonempty_and_organic(name, cfg):
    # Verifies every non-rectangle shape yields a single connected region, inset from the border, that
    # leaves some VOID (i.e. is genuinely non-square) - the contract the builder relies on.
    from biomegen.util import rng
    from biomegen.world.interiors import SHAPES

    gw, gh = 40, 32
    mask = SHAPES.get(name)(rng.derive(123, "interior.shape"), gw, gh)
    assert mask.shape == (gh, gw)
    assert mask.any()  # non-empty
    assert _mask_components(mask) == 1  # one connected region
    assert not mask[0, :].any() and not mask[:, 0].any()  # inset: never touches the border
    assert not mask.all()  # leaves VOID -> not the full rectangle


def test_dungeon_outline_is_not_rectangular(dungeon, cfg):
    # Verifies the dungeon is dynamically shaped: its structure does not fill the footprint rectangle
    # (an organic outline leaves VOID/terrain around it), so it is not a square block.
    grid = build_interior(dungeon, dungeon.lowest_floor + dungeon.floor_count - 1, cfg)
    assert float((grid == int(Cell.VOID)).mean()) > 0.1


def test_mixed_shape_varies_across_dungeons(cfg):
    # Verifies "mixed" picks different shapes per dungeon (so they aren't all the same / all square).
    from biomegen.world.interiors.grid import InteriorCtx, resolve_shape

    signatures = set()
    for seed in range(40):
        ctx = InteriorCtx("dungeon", seed, 0, -2, 3, 42, 36, 4, 10, 0.1, "bsp", "mixed")
        signatures.add(resolve_shape(ctx, 42, 36).tobytes())
    assert len(signatures) >= 5  # a good spread of distinct shapes/instances


def test_dungeon_shape_is_floor_independent(cfg):
    # Verifies a dungeon's boundary shape is chosen once per dungeon (not per floor), so every floor
    # shares one building footprint even though the room layout inside it varies floor to floor.
    from biomegen.world.interiors.grid import InteriorCtx, resolve_shape

    masks = set()
    for f in range(-2, 1):  # different floors, same dungeon (interior_seed)
        ctx = InteriorCtx("dungeon", 999, f, -2, 3, 42, 36, 4, 10, 0.1, "bsp", "mixed")
        masks.add(resolve_shape(ctx, 42, 36).tobytes())
    assert len(masks) == 1  # identical boundary shape on every floor

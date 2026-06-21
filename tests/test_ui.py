"""Tests for input mapping and the curses drawing loops.

The drawing functions are exercised against an in-memory fake screen + palette so the per-cell draw
logic (indexing, cursor highlight, zoom magnification, status panel) is covered without a real TTY.
Interactive behaviour still needs a terminal, but every code path that touches the world arrays runs
here.
"""

from __future__ import annotations

import curses

import pytest
from biomegen import pipeline
from biomegen.config import load_config
from biomegen.render import app
from biomegen.render.glyphs import Glyphs
from biomegen.render.input import resolve_action
from biomegen.render.state import ViewState
from biomegen.world.overlay import Overlay


class FakeScreen:
    """Minimal stand-in for a curses window that records addstr calls."""

    def __init__(self, height: int, width: int) -> None:
        self.h = height
        self.w = width
        self.calls: list = []

    def getmaxyx(self):
        return (self.h, self.w)

    def addstr(self, y, x, text, attr=0):
        if y >= self.h or x >= self.w or y < 0 or x < 0:
            raise curses.error("out of bounds")
        self.calls.append((y, x, text, attr))

    def erase(self):
        pass

    def refresh(self):
        pass

    def keypad(self, _flag):
        pass


class FakePalette:
    """A palette that returns neutral attributes (mode independent)."""

    mode = "mono"
    marker_attr = 0
    cursor_attr = curses.A_REVERSE

    def tile_attr(self, world, x, y):
        return 0

    def biome_attr(self, biome_int):
        return 0

    def interior_attr(self, cell_int):
        return 0

    def zoom_attr(self, color_id):
        return 0


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    c = load_config(None)
    c.data["world"]["width"] = 60
    c.data["world"]["height"] = 40
    return pipeline.generate(c, 4321)


def test_resolve_action_arrows_and_keys(cfg):
    assert resolve_action(curses.KEY_LEFT, cfg) == ("move", -1, 0)
    assert resolve_action(curses.KEY_RIGHT, cfg) == ("move", 1, 0)
    assert resolve_action(ord(" "), cfg) == ("zoom",)
    assert resolve_action(ord("f"), cfg) == ("toggle_scale",)
    assert resolve_action(ord("z"), cfg) == ("local",)
    assert resolve_action(ord("r"), cfg) == ("refresh",)
    assert resolve_action(ord("q"), cfg) == ("quit",)
    assert resolve_action(27, cfg) == ("quit",)  # ESC
    assert resolve_action(ord("e"), cfg) == ("export", "view")
    assert resolve_action(ord("E"), cfg) == ("export", "world")
    assert resolve_action(curses.KEY_RESIZE, cfg) == ("resize",)
    assert resolve_action(ord("?"), cfg) == ("none",)  # unbound


def test_resolve_action_fast_move(cfg):
    step = int(cfg.get("controls.fast_step"))
    # Capital WASD/HJKL = fast step.
    assert resolve_action(ord("D"), cfg) == ("move", step, 0)
    assert resolve_action(ord("W"), cfg) == ("move", 0, -step)
    assert resolve_action(ord("K"), cfg) == ("move", 0, -step)
    # Shifted left/right arrows (always available) = fast step.
    assert resolve_action(curses.KEY_SLEFT, cfg) == ("move", -step, 0)
    assert resolve_action(curses.KEY_SRIGHT, cfg) == ("move", step, 0)


def test_initial_cursor_is_on_land(world):
    cx, cy = app._initial_cursor(world)
    assert world.in_bounds(cx, cy)
    from biomegen.world.tile import WaterType

    assert world.water_type[cy, cx] == int(WaterType.NONE)


def test_interesting_cursor_picks_top_land_feature(world):
    """The new-world cursor lands on a top-priority land feature (never on open water)."""
    import numpy as np
    from biomegen.render import map_view
    from biomegen.world.tile import WaterType

    cx, cy = app._interesting_cursor(world)
    assert world.water_type[cy, cx] == int(WaterType.NONE)  # on land

    land = world.water_type == int(WaterType.NONE)
    max_biome = int(world.biome.max()) + 1
    lut = np.zeros(max_biome, dtype=float)
    for b, p in map_view._BIOME_PRIORITY.items():
        if b < max_biome:
            lut[b] = p
    prio = lut[world.biome]
    prio[~land] = -1.0
    prio[world.road != 0] = map_view._ROAD_PRIORITY
    prio[world.poi_index >= 0] = map_view._POI_PRIORITY
    assert prio[cy, cx] == prio.max()  # chosen tile is among the most interesting


@pytest.mark.parametrize(
    "mode,scale",
    [
        ("fit", "biome"),
        ("onetoone", "biome"),
        ("fit", "zoom"),
        ("fit", "local"),
    ],
)
def test_draw_does_not_crash_and_paints(world, cfg, mode, scale):
    screen = FakeScreen(height=30, width=80)
    palette = FakePalette()
    glyphs = Glyphs(cfg)
    vs = ViewState(mode=mode, scale=scale)
    vs.cx, vs.cy = app._initial_cursor(world)
    overlay = Overlay()
    # Should render a full frame (map + status) without raising, in every scale.
    app._draw(screen, world, cfg, vs, glyphs, palette, overlay)  # type: ignore[arg-type]
    assert len(screen.calls) > 0


def test_real_curses_loop_smoke(world, cfg):
    """Drive the actual curses app loop with scripted input (skips if no console is available)."""
    keys = iter(
        [
            curses.KEY_RIGHT,
            ord("D"),
            curses.KEY_SRIGHT,  # normal + fast moves
            ord(" "),  # biome -> zoom
            ord("z"),
            curses.KEY_DOWN,  # zoom -> local, move in local
            ord(" "),  # local -> zoom (step out)
            ord(" "),  # zoom -> biome
            ord("f"),
            curses.KEY_LEFT,  # 1:1 view + move
            ord("r"),  # regenerate world (new seed, rebuild palette)
            ord("q"),
        ]
    )

    def target(stdscr):
        app._main(stdscr, world, cfg, get_key=lambda: next(keys))

    try:
        curses.wrapper(target)
    except curses.error as exc:
        pytest.skip(f"no curses-capable terminal available: {exc}")


def test_legend_lists_only_given_biomes():
    from biomegen.render.glyphs import Glyphs
    from biomegen.render.status import _legend_entries
    from biomegen.world.tile import Biome

    glyphs = Glyphs(load_config(None))
    entries = _legend_entries({int(Biome.OCEAN), int(Biome.FOREST)}, glyphs)
    names = [name for _g, name, _b in entries]
    assert names == ["ocean", "forest"]  # sorted by biome int (ocean=0 before forest)


def test_interior_legend_skips_void_and_sorts():
    # Verifies that VOID is excluded and remaining entries are sorted by cell int.
    from biomegen.render.glyphs import Glyphs
    from biomegen.render.status import _interior_legend_entries
    from biomegen.world.tile import Cell

    glyphs = Glyphs(load_config(None))
    cell_ints = {int(Cell.VOID), int(Cell.FLOOR), int(Cell.WALL), int(Cell.CHEST)}
    entries = _interior_legend_entries(cell_ints, glyphs)
    names = [name for _g, name, _c in entries]
    assert "void" not in names
    assert names == sorted(names, key=lambda n: next(c for c in Cell if c.name.lower() == n))


def test_zoom_enter_centers_cursor(world, cfg):
    """Toggling into zoom sets recenter, and the first zoom draw centres the camera on the cursor."""
    screen = FakeScreen(height=30, width=80)
    palette = FakePalette()
    glyphs = Glyphs(cfg)
    vs = ViewState(scale="zoom", recenter=True)
    vs.cx, vs.cy = 30, 20
    app._draw(screen, world, cfg, vs, glyphs, palette, Overlay())  # type: ignore[arg-type]
    # Derive the viewport tile-count the same way _draw does (status panel reduces the map height).
    from biomegen.render.state import center_cam
    from biomegen.render.zoom_view import detail_cell_size

    status_h = max(3, min(int(cfg.get("render.status_height")), 30 - 2))
    cell_w, _ = detail_cell_size("zoom", cfg, 80, 30 - status_h)
    tiles_w = max(1, 80 // cell_w)
    # Camera should be centred on the cursor (within clamping), not left at 0.
    assert vs.cam_x == center_cam(30, tiles_w, world.width)
    assert vs.recenter is False  # consumed


def test_overlay_glyph_override_is_drawn(world, cfg):
    glyphs = Glyphs(cfg)
    vs = ViewState(mode="onetoone")
    vs.cx, vs.cy = app._initial_cursor(world)
    overlay = Overlay()
    overlay.set_surface(vs.cx, vs.cy, glyph="@")
    # The overlay edit should win over the base biome glyph at that tile.
    assert app._tile_glyph(world, glyphs, overlay, vs.cx, vs.cy) == "@"

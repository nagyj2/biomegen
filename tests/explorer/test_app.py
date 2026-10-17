"""Tests for the explorer: frame composition and the whole loop, run with a scripted key source."""

from __future__ import annotations

import re
from pathlib import Path
from types import TracebackType
from typing import Optional

import numpy as np

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.app import compose_frame, history_start, run
from biomegen.explorer.state import ViewState, move_cursor, pan_view, step_in
from biomegen.sampling.detail import SCALE_LOCAL, SCALE_SITE, SCALE_ZOOM
from biomegen.sites import site_geometry
from biomegen.world.entities import POI, ChronicleEvent
from biomegen.world.overlay import Overlay
from biomegen.world.tile import Biome
from tests.explorer.replay import RecordingOut
from tests.render.conftest import make_world

SIZE = (100, 40)


class ScriptedKeys:
    """A key source that plays back a fixed list of tokens, then presses q for ever."""

    def __init__(self, *tokens: str) -> None:
        self._tokens = list(tokens)

    def __enter__(self) -> "ScriptedKeys":
        return self

    def __exit__(
        self, kind: Optional[type[BaseException]], value: Optional[BaseException], trace: Optional[TracebackType]
    ) -> None:
        return None

    def read_key(self) -> str:
        return self._tokens.pop(0) if self._tokens else "q"

    def pending(self) -> bool:
        return False  # one key per frame: every token is drawn


class BurstKeys(ScriptedKeys):
    """A key source whose tokens all arrive at once, as a held key's repeats do while a frame is drawn."""

    def pending(self) -> bool:
        return bool(self._tokens)


def _world(tower: bool = False):
    world = make_world(40, 20, Biome.GRASS)
    world.island_name = "Testland"
    if tower:
        world.pois.append(POI(kind="tower", x=20, y=10, interior_seed=3, floor_count=2))
        world.poi_index[10, 20] = 0
    return world


def _village_world():
    """A 40 x 20 world with one village (pop 800) at (20, 10), where the explorer's cursor starts."""
    world = make_world(40, 20, Biome.GRASS)
    world.island_name = "Testland"
    world.pois.append(POI(kind="village", x=20, y=10, interior_seed=3, pop=800, name="Dunmere", tags=("river",)))
    world.poi_index[10, 20] = 0
    return world


def _site_state(world, config: Config) -> ViewState:
    state = ViewState(scale=SCALE_ZOOM, cx=20, cy=10, recenter=True)
    step_in(world, config, state)
    return state


def _run(world, config: Config, *tokens: str, color: str = "none", get_size=None, keys=ScriptedKeys) -> RecordingOut:
    """Run the loop on a scripted keyboard; the result holds every frame as screen text (``.frames``)."""
    out = RecordingOut(SIZE[1], SIZE[0])
    run(world, config, color, reader=keys(*tokens), out=out, get_size=get_size or (lambda: SIZE))
    return out


def _screen(out: RecordingOut) -> str:
    """The last frame drawn, as text."""
    return "\n".join(out.frames[-1])


def _shown(out: RecordingOut, text: str) -> bool:
    """Whether any frame drawn had ``text`` on screen."""
    return any(text in "\n".join(frame) for frame in out.frames)


def _frame(world, config: Config, state: ViewState | None = None, **kwargs):
    return compose_frame(world, config, state or ViewState(cx=20, cy=10), Overlay(), kwargs.pop("size", SIZE), **kwargs)


def test_waiting_moves_are_drawn_once(config: Config) -> None:
    # Three moves that arrive together draw one frame, not three: two fewer frames than one key at a time.
    one_by_one = _run(_world(), config, "right", "right", "down")
    together = _run(_world(), config, "right", "right", "down", keys=BurstKeys)
    assert len(one_by_one.frames) - len(together.frames) == 2


def test_waiting_moves_end_where_single_moves_end(config: Config) -> None:
    # The skipped frames change nothing but the drawing: the last frame is the same, and a key after the moves acts.
    one_by_one = _run(_world(), config, "right", "right", "down", "v")
    together = _run(_world(), config, "right", "right", "down", "v", keys=BurstKeys)
    assert _screen(together) == _screen(one_by_one)


def test_frame_is_the_size_of_the_terminal(config: Config) -> None:
    screen = _frame(_world(), config).screen
    assert (screen.cols, screen.rows) == SIZE


def test_the_panel_sits_under_the_map(config: Config) -> None:
    # The island line is the second row of the 12-row panel at the bottom of a 40-row screen.
    screen = _frame(_world(), config).screen
    assert "Testland" in "".join(screen.glyph[40 - 15 + 1])


def test_cursor_cell_is_drawn_in_reverse_video(config: Config) -> None:
    frame = _frame(_world(), config)
    assert (frame.screen.bg[10, 20] == frame.map_grid.fg[10, 20]).all() and (
        frame.screen.fg[10, 20] == frame.map_grid.bg[10, 20]
    ).all()


def test_the_exported_map_has_no_cursor(config: Config) -> None:
    # map_grid is what `e` writes: the cursor highlight must not be in it.
    frame = _frame(_world(), config)
    assert not (frame.map_grid.bg[10, 20] == frame.map_grid.fg[10, 20]).all()


def test_zoom_highlights_the_whole_tile_block(config: Config) -> None:
    # An 8 x 4 zoom block is reversed: 32 cells differ from the map as drawn.
    state = ViewState(cx=20, cy=10, scale=SCALE_ZOOM, recenter=True)
    frame = _frame(_world(), config, state)
    rows = frame.map_grid.rows
    differs = (frame.screen.bg[:rows, : frame.map_grid.cols] != frame.map_grid.bg).any(axis=-1)
    assert int(differs.sum()) == 32


def test_zoom_centres_the_camera_on_the_cursor(config: Config) -> None:
    state = ViewState(cx=20, cy=10, scale=SCALE_ZOOM, recenter=True)
    _frame(_world(), config, state)
    assert (state.cam_x, state.recenter) == (14, False)


def test_one_to_one_map_pans_with_the_cursor(config: Config) -> None:
    state = ViewState(cx=39, cy=10, mode="onetoone", recenter=False)
    _frame(_world(), config, state, size=(30, 20))
    assert state.cam_x > 0


def test_pan_carries_the_cursor_with_the_viewport(config: Config) -> None:
    # Panning right from a centred camera moves the camera and the cursor by the same amount (clamped to the margin).
    world = _world()
    state = ViewState(cx=15, cy=10, mode="onetoone", cam_x=5, cam_y=0, recenter=False)
    _frame(world, config, state, size=(20, 20))
    state.pan_x = 12
    _frame(world, config, state, size=(20, 20))
    assert (state.cam_x, state.cx) == (17, 27)


def test_pan_on_the_fit_map_moves_the_cursor(config: Config) -> None:
    # The fit map shows the whole world, so there is no viewport to scroll.
    world = _world()
    state = ViewState(cx=5, cy=5)
    pan_view(world, config, state, 1, 0)
    assert (state.cx, state.pan_x) == (6, 0)


def test_tiny_terminal_shows_a_notice(config: Config) -> None:
    assert "too small" in "".join(_frame(_world(), config, size=(60, 3)).screen.glyph[0])


def test_loop_enters_and_leaves_the_alternate_screen(config: Config) -> None:
    out = _run(_world(), config).getvalue()
    assert out.startswith("\x1b[?1049h") and out.rstrip().endswith("\x1b[?1049l")


def test_first_frame_shows_the_island_and_seed(config: Config) -> None:
    screen = _screen(_run(_world(), config))
    assert "Testland" in screen and "seed 1" in screen


def test_zoom_key_changes_the_panel(config: Config) -> None:
    assert "view ZOOM" in _screen(_run(_world(), config, " "))


def test_local_key_goes_in_a_scale(config: Config) -> None:
    assert "view LOCAL" in _screen(_run(_world(), config, "z", "z"))


def test_view_key_cycles_to_the_next_view(config: Config) -> None:
    assert "view: political" in _screen(_run(_world(), config, "v"))


def test_view_key_goes_on_to_the_data_views(config: Config) -> None:
    assert "view: elevation" in _screen(_run(_world(), config, "v", "v"))


def test_fit_key_toggles_to_fit(config: Config) -> None:
    assert "view FIT" in _screen(_run(_world(), config, "f"))


def test_arrow_keys_move_the_cursor(config: Config) -> None:
    # The cursor starts wherever initial_cursor puts it; one step right adds one to its column.
    out = _run(_world(), config, "right")
    columns = [
        int(re.search(r"cursor \((\d+),", "\n".join(frame)).group(1)) for frame in (out.frames[1], out.frames[-1])
    ]
    assert columns[1] == columns[0] + 1


def test_help_opens_and_any_key_closes_it(config: Config) -> None:
    out = _run(_world(), config, "?", "x")
    assert (_shown(out, "step out"), "step out" in _screen(out)) == (True, False)


def test_help_key_does_not_act_while_the_help_is_open(config: Config) -> None:
    # The key that closes the help is swallowed: space must not also zoom.
    assert "view ZOOM" not in _screen(_run(_world(), config, "?", " "))


def test_floor_keys_change_floor_on_a_structure(config: Config) -> None:
    assert "floor 1" in _screen(_run(_world(tower=True), config, ">"))


def test_end_of_input_quits(config: Config) -> None:
    out = _run(_world(), config, "eof").getvalue()
    assert out.rstrip().endswith("\x1b[?1049l")


def test_resize_repaints_at_the_new_size(config: Config) -> None:
    sizes = iter([(100, 40), (80, 24), (80, 24)])
    out = _run(_world(), config, "resize", get_size=lambda: next(sizes)).getvalue()
    assert out.count("\x1b[2J") >= 2


def test_view_export_writes_the_screen_map(config: Config, tmp_path: Path) -> None:
    config.data["export"].update({"dir": str(tmp_path / "out"), "png": False})
    _run(_world(), config, "e")
    assert [p.suffix for p in (tmp_path / "out").iterdir()] == [".svg"]


def test_world_export_names_the_world(config: Config, tmp_path: Path) -> None:
    config.data["export"].update({"dir": str(tmp_path / "out"), "png": False})
    _run(_world(), config, "E")
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["Testland_1_world.svg"]


def test_export_failure_is_reported_not_raised(config: Config, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    config.data["export"].update({"dir": str(blocker / "sub"), "png": False})
    assert "export failed" in _screen(_run(_world(), config, "e"))


def test_loop_restores_the_terminal_after_an_error(config: Config) -> None:
    class Exploding(ScriptedKeys):
        def read_key(self) -> str:
            raise RuntimeError("boom")

    out = RecordingOut(SIZE[1], SIZE[0])
    try:
        run(_world(), config, "none", reader=Exploding(), out=out, get_size=lambda: SIZE)
    except RuntimeError:
        pass
    assert out.getvalue().rstrip().endswith("\x1b[?1049l")


def test_composed_frames_are_repeatable(config: Config) -> None:
    first = _frame(_world(), config).screen
    second = _frame(_world(), config).screen
    assert (first.glyph == second.glyph).all() and np.array_equal(first.bg, second.bg)


def test_default_config_is_untouched_by_the_loop() -> None:
    config = load_config(None)
    before = repr(config.data)
    _run(_world(), config, " ", "v", "f")
    assert repr(config.data) == before


def test_zooming_in_twice_on_a_poi_opens_its_site(config: Config) -> None:
    assert "view SITE" in _screen(_run(_village_world(), config, "z", "z"))


def test_the_panel_describes_the_poi_in_a_site(config: Config) -> None:
    assert "Dunmere (village, pop 800, river)" in _screen(_run(_village_world(), config, "z", "z"))


def test_the_site_cursor_is_one_cell(config: Config) -> None:
    world = _village_world()
    frame = _frame(world, config, _site_state(world, config))
    rows, cols = frame.map_grid.rows, frame.map_grid.cols
    differs = (frame.screen.bg[:rows, :cols] != frame.map_grid.bg).any(axis=-1)
    assert int(differs.sum()) == 1


def test_the_site_cursor_moves_one_cell(config: Config) -> None:
    world = _village_world()
    state = _site_state(world, config)
    before = _frame(world, config, state).screen
    move_cursor(world, config, state, 1, 0)
    after = _frame(world, config, state).screen
    assert not np.array_equal(before.bg, after.bg)


def test_the_site_camera_follows_the_cursor(config: Config) -> None:
    # Walking far enough east scrolls the camera instead of running the cursor off screen.
    world = _village_world()
    state = _site_state(world, config)
    geometry = site_geometry(world.pois[0], config)
    assert geometry is not None
    start = state.site_cam_x
    for _ in range(60):
        move_cursor(world, config, state, 1, 0)
        _frame(world, config, state)
        if state.scale != SCALE_SITE:
            break
    assert state.site_cam_x > start or state.scale == SCALE_LOCAL


def test_the_zoom_key_leaves_a_site(config: Config) -> None:
    assert "view ZOOM" in _screen(_run(_village_world(), config, "z", "z", " "))


def test_walking_off_the_site_leaves_for_local(config: Config) -> None:
    world = _village_world()
    state = _site_state(world, config)
    geometry = site_geometry(world.pois[0], config)
    assert geometry is not None
    state.px = geometry.cols - 1
    move_cursor(world, config, state, 1, 0)
    screen = "".join("".join(row) for row in _frame(world, config, state).screen.glyph)
    assert state.scale == SCALE_LOCAL and "view LOCAL" in screen


def test_a_site_smaller_than_the_screen_is_centred_with_blank_margins(config: Config) -> None:
    world = _village_world()
    state = _site_state(world, config)
    geometry = site_geometry(world.pois[0], config)
    assert geometry is not None
    frame = _frame(world, config, state, size=(geometry.cols + 60, 40))
    assert state.site_cam_x < 0 and frame.map_grid.glyph[0, 0] == " "


def test_the_site_frame_is_repeatable(config: Config) -> None:
    world = _village_world()
    state = _site_state(world, config)
    first = _frame(world, config, state).screen
    second = _frame(world, config, state).screen
    assert np.array_equal(first.glyph, second.glyph) and np.array_equal(first.bg, second.bg)


def _village_with_events():
    """The village world with two events at the village (years 90 and 120, the later in month 5) and one elsewhere."""
    world = _village_world()
    world.year = 300
    world.chronicle = [
        ChronicleEvent(0, 90, "settling", poi_ids=[0], text="Dunmere is settled.", month=2),
        ChronicleEvent(1, 100, "war", location=(3, 3), text="A far war.", month=1),
        ChronicleEvent(2, 120, "succession", poi_ids=[0], text="Dunmere crowns a new lord.", month=5),
    ]
    return world


def test_the_history_key_opens_the_viewer_and_q_returns_to_the_explorer(config: Config) -> None:
    out = _run(_village_world(), config, "t", "q")
    assert _shown(out, "History of Testland") and "History of" not in _screen(out)


def test_the_history_viewer_opens_at_the_latest_event_at_the_cursor(config: Config) -> None:
    out = _run(_village_with_events(), config, "t", "q")
    assert _shown(out, "year 120, month 5")


def test_with_no_event_at_the_cursor_the_viewer_opens_at_the_present(config: Config) -> None:
    world = _village_with_events()
    state = ViewState(cx=3, cy=5)
    assert history_start(world, config, state) == (300, config.get("history.months_per_year"))


def test_the_history_start_is_the_latest_event_here(config: Config) -> None:
    assert history_start(_village_with_events(), config, ViewState(cx=20, cy=10)) == (120, 5)

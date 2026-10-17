"""Tests for the history viewer: moments, key resolution, stepping, frame composition and the whole loop."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.history_viewer import (
    HistoryState,
    apply_history_action,
    change_moments,
    compose_history_frame,
    initial_state,
    moment_summary,
    resolve_history_action,
    run_history,
    stop_index,
)
from biomegen.world.world import World
from tests.explorer.replay import RecordingOut
from tests.explorer.test_app import ScriptedKeys

SIZE = (120, 36)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, 42)


def _text(world: World, cfg: Config, state: HistoryState) -> list[str]:
    return ["".join(row).rstrip() for row in compose_history_frame(world, cfg, state, SIZE).glyph]


def _press(world: World, cfg: Config, state: HistoryState, *tokens: str) -> None:
    for token in tokens:
        compose_history_frame(world, cfg, state, SIZE)  # as the loop does, so the scroll follows
        apply_history_action(world, cfg, state, resolve_history_action(token, cfg, state.prompt is not None), SIZE)


def test_the_moments_are_distinct_and_ordered(world: World) -> None:
    moments = change_moments(world)
    assert moments == sorted(set(moments)) and len(moments) > 10


def test_the_moments_include_every_territory_change_and_conquest(world: World) -> None:
    moments = set(change_moments(world))
    assert {c.moment for c in world.territory} <= moments
    assert {(e.year, e.month) for e in world.chronicle if e.kind == "conquest"} <= moments


def test_the_viewer_opens_at_the_first_change(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    assert state.at == state.moments[0]


def test_a_start_year_opens_at_the_end_of_that_year(world: World, cfg: Config) -> None:
    assert initial_state(world, cfg, 500).at == (500, cfg.get("history.months_per_year"))


def test_a_start_moment_is_kept(world: World, cfg: Config) -> None:
    assert initial_state(world, cfg, (300, 4)).at == (300, 4)


def test_next_and_previous_step_between_changes(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "]", "]", "[")
    assert state.at == state.moments[1]


def test_stepping_back_from_the_first_change_stays_and_says_so(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "[")
    assert state.at == state.moments[0] and state.message == "no earlier change"


def test_the_present_key_goes_to_the_last_change(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "\\")
    assert state.at == state.moments[-1]


def test_stepping_past_the_last_change_says_so(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "end", "]")
    assert state.at == state.moments[-1] and state.message == "no later change"


def test_the_year_keys_skip_to_another_year(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    year = state.at[0]
    _press(world, cfg, state, "}")
    assert state.at[0] > year
    _press(world, cfg, state, "{")
    assert state.at[0] == year


def test_go_to_a_year_shows_the_map_at_the_end_of_it(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "g", "7", "0", "0", "\r")
    assert state.at == (700, cfg.get("history.months_per_year")) and state.prompt is None


def test_an_unreadable_year_is_refused(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    before = state.at
    _press(world, cfg, state, "g", "x", "\r")
    assert state.at == before and state.message.startswith("year:")


def test_escape_closes_the_year_prompt(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "g", "esc")
    assert state.prompt is None


def test_stop_index_is_minus_one_before_the_first_change() -> None:
    assert stop_index([(10, 1), (20, 2)], (5, 1)) == -1 and stop_index([(10, 1), (20, 2)], (10, 1)) == 0


def test_the_frame_has_the_year_in_its_title(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg, (300, 4))
    assert _text(world, cfg, state)[0].startswith("History of") and "year 300, month 4" in _text(world, cfg, state)[0]


def test_the_map_changes_between_the_first_and_the_last_change(world: World, cfg: Config) -> None:
    first, last = initial_state(world, cfg), initial_state(world, cfg)
    last.at = last.moments[-1]
    a, b = compose_history_frame(world, cfg, first, SIZE), compose_history_frame(world, cfg, last, SIZE)
    assert (a.bg[1:20, :60] != b.bg[1:20, :60]).any()


def test_the_present_map_shows_the_largest_realm_in_the_powers_list(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    state.at = state.moments[-1]
    largest = max(world.realms, key=lambda r: int((world.realm_id == r.id).sum()))
    assert any(largest.short in line for line in _text(world, cfg, state))


def test_events_of_the_current_moment_are_highlighted(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    state.at = next(m for m in state.moments if any((e.year, e.month) == m for e in world.chronicle))
    grid = compose_history_frame(world, cfg, state, SIZE)
    highlight = np.array(cfg.get("history.viewer.current_bg"), dtype=np.uint8)
    assert (grid.bg[:, 80] == highlight).all(axis=1).any()


def test_the_status_line_describes_the_change(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    state.at = next(c.moment for c in world.territory if c.kind == "expansion")
    status = _text(world, cfg, state)[SIZE[1] - 2]
    assert status.strip().startswith(moment_summary(world, state.at)[:30])


def test_a_small_terminal_gets_a_message(world: World, cfg: Config) -> None:
    grid = compose_history_frame(world, cfg, initial_state(world, cfg), (40, 10))
    assert "terminal too small" in "".join(grid.glyph[0])


def test_the_help_box_lists_the_keys(world: World, cfg: Config) -> None:
    grid = compose_history_frame(world, cfg, initial_state(world, cfg), SIZE, help_open=True)
    assert any("History keys" in "".join(row) for row in grid.glyph)


def _run(world: World, cfg: Config, *tokens: str, start=None) -> RecordingOut:
    out = RecordingOut(SIZE[1], SIZE[0])
    run_history(world, cfg, "none", start, reader=ScriptedKeys(*tokens), out=out, get_size=lambda: SIZE)
    return out


def test_the_loop_draws_then_quits_on_q(world: World, cfg: Config) -> None:
    out = _run(world, cfg)
    assert out.frames[-1][0].startswith("History of")


def test_the_loop_steps_with_the_keys(world: World, cfg: Config) -> None:
    moments = change_moments(world)
    out = _run(world, cfg, "]", "]")
    assert f"year {moments[2][0]}, month {moments[2][1]}" in out.frames[-1][0]

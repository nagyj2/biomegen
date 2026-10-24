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
    event_focus,
    initial_state,
    moment_summary,
    resolve_history_action,
    run_history,
    stop_index,
)
from biomegen.explorer.history_viewer import (
    present_moment as present_stop,
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


def test_the_moments_are_distinct_and_ordered(world: World, cfg: Config) -> None:
    moments = change_moments(world, cfg)
    assert moments == sorted(set(moments)) and len(moments) > 10


def test_the_moments_include_every_territory_change_and_conquest(world: World, cfg: Config) -> None:
    moments = set(change_moments(world, cfg))
    assert {c.key for c in world.territory} <= moments
    assert {(e.year, e.month, e.id) for e in world.chronicle if e.kind == "conquest"} <= moments


def test_the_viewer_opens_at_the_first_change(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    assert state.at == state.moments[0]


def test_a_start_year_opens_at_the_end_of_that_year(world: World, cfg: Config) -> None:
    assert initial_state(world, cfg, 500).at[:2] == (500, cfg.get("history.months_per_year"))


def test_a_start_moment_is_kept(world: World, cfg: Config) -> None:
    assert initial_state(world, cfg, (300, 4)).at[:2] == (300, 4)


def test_next_and_previous_step_between_changes(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "]", "]", "[")
    assert state.at == state.moments[1]


def test_stepping_back_from_the_first_change_stays_and_says_so(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "[")
    assert state.at == state.moments[0] and state.message == "nothing earlier"


def test_the_present_key_goes_to_the_last_change(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "\\")
    assert state.at == state.moments[-1]


def test_stepping_past_the_last_change_says_so(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "end", "]")
    assert state.at == state.moments[-1] and state.message == "nothing later"


def test_go_to_a_year_shows_the_map_at_the_end_of_it(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "g", "7", "0", "0", "\r")
    assert state.at[:2] == (700, cfg.get("history.months_per_year")) and state.prompt is None


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
    state.at = next(m for m in state.moments if any((e.year, e.month, e.id) == m for e in world.chronicle))
    grid = compose_history_frame(world, cfg, state, SIZE)
    highlight = np.array(cfg.get("history.viewer.current_bg"), dtype=np.uint8)
    assert (grid.bg[:, 80] == highlight).all(axis=1).any()


def test_the_status_line_describes_the_change(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    state.at = next(c.key for c in world.territory if c.kind == "expansion")
    status = _text(world, cfg, state)[SIZE[1] - 2]
    assert status.strip().startswith(moment_summary(world, cfg, state.at)[:30])


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
    moments = change_moments(world, cfg)
    out = _run(world, cfg, "]", "]")
    assert f"year {moments[2][0]}, month {moments[2][1]}" in out.frames[-1][0]


# --- event markers on the map -------------------------------------------------------------------------------------


def _marked(world: World, cfg: Config, at: tuple[int, int]):
    """The fitted map at ``at`` of a world with a battle at (60, 20) in year 300, month 6 and a founding at (60, 30)."""
    from biomegen.world.entities import ChronicleEvent

    marked = pipeline.generate(cfg, 42)
    marked.chronicle = [
        ChronicleEvent(0, 280, "founding", [0], location=(60, 30), month=2),
        ChronicleEvent(1, 300, "battle", [0, 1], location=(60, 20), month=6),
        ChronicleEvent(2, 301, "peace", [0, 1], location=(100, 20), month=1),
        ChronicleEvent(3, 300, "succession", [0], month=7),
        ChronicleEvent(4, 200, "war", [0, 1], location=(20, 10), month=1),
    ]
    marked.territory = []
    state = initial_state(marked, cfg, at)
    state.moments = [(300, 6, 1)]
    return marked, state, compose_history_frame(marked, cfg, state, SIZE)


def _cell(world: World, cfg: Config, tile: tuple[int, int]) -> tuple[int, int]:
    """The ``(row, column)`` of the frame cell showing ``tile`` (the map starts under the title row)."""
    from biomegen.explorer.history_viewer import _POWER_ROWS, _geometry
    from biomegen.render.fit import FitSampler

    map_cols, _ = _geometry(cfg, SIZE[0])
    sampler = FitSampler(world, cfg, map_cols, SIZE[1] - 3 - _POWER_ROWS)
    col, row = sampler.cell_coords(*tile)
    return row + 1, col


def test_an_event_of_the_current_moment_is_marked_in_bold(world: World, cfg: Config) -> None:
    _, _, frame = _marked(world, cfg, (300, 6, 1))  # at the battle itself
    row, col = _cell(world, cfg, (60, 20))
    assert frame.glyph[row, col] == "x" and bool(frame.bold[row, col])


def test_an_earlier_event_is_marked_faded(world: World, cfg: Config) -> None:
    _, _, frame = _marked(world, cfg, (300, 6))
    row, col = _cell(world, cfg, (60, 30))
    assert frame.glyph[row, col] == "o" and not frame.bold[row, col]


def test_a_later_event_is_not_marked(world: World, cfg: Config) -> None:
    _, _, frame = _marked(world, cfg, (300, 6))
    row, col = _cell(world, cfg, (100, 20))
    assert frame.glyph[row, col] != "="


def test_an_event_long_before_the_window_is_not_marked(world: World, cfg: Config) -> None:
    _, _, frame = _marked(world, cfg, (300, 6))
    row, col = _cell(world, cfg, (20, 10))
    assert frame.glyph[row, col] != "x"


def test_the_title_shows_the_seed(world: World, cfg: Config) -> None:
    assert f"seed {world.seed}" in _text(world, cfg, initial_state(world, cfg))[0]


def test_the_help_explains_the_map_marks(world: World, cfg: Config) -> None:
    grid = compose_history_frame(world, cfg, initial_state(world, cfg), SIZE, help_open=True)
    text = "\n".join("".join(row) for row in grid.glyph)
    assert "Marks on the map" in text and "> expansion" in text and "x battle" in text


def test_every_fall_war_and_peace_is_a_stop(world: World, cfg: Config) -> None:
    moments = set(change_moments(world, cfg))
    stops = {(e.year, e.month, e.id) for e in world.chronicle if e.kind in ("fall", "war", "peace")}
    assert stops and stops <= moments


def test_the_status_line_describes_a_fall_that_hands_over_land(world: World, cfg: Config) -> None:
    change = next(c for c in world.territory if c.kind == "fall")
    assert "fall:" in moment_summary(world, cfg, change.key)


def test_every_listed_event_is_a_stop(world: World, cfg: Config) -> None:
    moments = set(change_moments(world, cfg))
    assert {(e.year, e.month, e.id) for e in world.chronicle if e.salience == "major"} <= moments


def test_the_last_stop_is_the_present_even_when_the_last_event_changes_nothing(world: World, cfg: Config) -> None:
    moments = change_moments(world, cfg)
    assert moments[-1][:2] == (world.year, cfg.get("history.months_per_year"))
    assert moments[-1] >= max((e.year, e.month, e.id) for e in world.chronicle if e.salience == "major")


def test_stepping_forward_always_reaches_the_present(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    for _ in range(len(state.moments) + 2):
        _press(world, cfg, state, "]")
    assert state.at == state.moments[-1] and "the present" in _text(world, cfg, state)[0]


def test_the_present_key_goes_to_the_present_stop(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "\\")
    assert state.at[:2] == (world.year, cfg.get("history.months_per_year"))


def test_the_minor_key_adds_the_minor_events_as_stops(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    before = len(state.moments)
    _press(world, cfg, state, "m")
    assert state.minor and len(state.moments) > before


def test_the_minor_key_twice_goes_back_to_the_major_events(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    before = list(state.moments)
    _press(world, cfg, state, "m", "m")
    assert not state.minor and state.moments == before


def test_the_minor_events_are_listed_only_when_shown(world: World, cfg: Config) -> None:
    minor = next(e for e in world.chronicle if e.salience == "minor")
    state = initial_state(world, cfg, (minor.year, minor.month))
    shown = {"major": "\n".join(_text(world, cfg, state))}
    _press(world, cfg, state, "m")
    shown["minor"] = "\n".join(_text(world, cfg, state))
    assert minor.text[:12] not in shown["major"] and minor.text[:12] in shown["minor"]


# --- following one tile (the viewer opened from the explorer) -----------------------------------------------------


def _tile_of_a_battle(world: World) -> tuple[int, int]:
    battle = next(e for e in world.chronicle if e.kind == "battle" and e.location != (-1, -1))
    return battle.location


def test_the_tile_keys_do_nothing_from_the_command_line(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    before = state.at
    _press(world, cfg, state, "}")
    assert state.at == before and "explorer" in state.message


def test_the_tile_moments_include_its_events_and_its_changes(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import tile_moments

    x, y = _tile_of_a_battle(world)
    moments = tile_moments(world, cfg, (x, y))
    assert {(e.year, e.month, e.id) for e in world.events_at(x, y) if e.salience == "major"} <= set(moments)
    cell = y * world.width + x
    assert {c.key for c in world.territory if cell in c.cells.tolist()} <= set(moments)


def test_the_tile_key_goes_to_the_tiles_next_event(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import tile_moments

    tile = _tile_of_a_battle(world)
    own = tile_moments(world, cfg, tile)
    state = initial_state(world, cfg, own[0], tile)
    _press(world, cfg, state, "}")
    assert state.at == own[1]


def test_the_tile_keys_stop_at_the_ends_of_the_tiles_history(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import tile_moments

    tile = _tile_of_a_battle(world)
    own = tile_moments(world, cfg, tile)
    state = initial_state(world, cfg, own[-1], tile)
    _press(world, cfg, state, "}")
    assert state.at == own[-1] and "at this tile" in state.message


def test_the_title_and_hint_name_the_selected_tile(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg, None, (12, 7))
    text = _text(world, cfg, state)
    assert "tile 12,7" in text[0] and "this tile" in text[-1]


def test_the_selected_tile_is_reversed_on_the_map(world: World, cfg: Config) -> None:
    plain = compose_history_frame(world, cfg, initial_state(world, cfg), SIZE)
    marked = compose_history_frame(world, cfg, initial_state(world, cfg, None, (60, 30)), SIZE)
    assert (plain.bg[1:25, :70] != marked.bg[1:25, :70]).any()


def test_the_help_lists_the_tile_keys_only_with_a_tile(world: World, cfg: Config) -> None:
    without = compose_history_frame(world, cfg, initial_state(world, cfg), SIZE, help_open=True)
    within = compose_history_frame(world, cfg, initial_state(world, cfg, None, (12, 7)), SIZE, help_open=True)
    has = lambda grid: "at the selected tile" in "\n".join("".join(row) for row in grid.glyph)  # noqa: E731
    assert (has(without), has(within)) == (False, True)


# --- examining the powers ------------------------------------------------------------------------------------------


def _at_present(world: World, cfg: Config) -> HistoryState:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "\\")
    return state


def test_tab_switches_to_the_powers_and_selects_the_largest(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import _powers

    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    assert state.focus == "powers" and state.selected == _powers(world, state)[0][0]


def test_tab_again_goes_back_to_time_and_keeps_the_selection(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t", "\t")
    assert state.focus == "time" and state.selected is not None


def test_down_and_up_choose_another_power(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import _powers

    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t", "down")
    second = _powers(world, state)[1][0]
    assert state.selected == second
    _press(world, cfg, state, "up")
    assert state.selected == _powers(world, state)[0][0]


def test_the_profile_of_the_selected_power_replaces_the_chronicle(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    text = "\n".join(_text(world, cfg, state))
    name = world.realms[state.selected].short if state.selected >= 0 else ""
    assert "land:" in text and "strength:" in text and name in text


def test_the_selected_power_is_marked_in_the_list(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    assert any(line.startswith(">") for line in _text(world, cfg, state))


def test_space_shows_the_power_on_the_map_and_space_again_hides_it(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    plain = compose_history_frame(world, cfg, state, SIZE).bg[1:12, :70].copy()
    _press(world, cfg, state, " ")
    shown = compose_history_frame(world, cfg, state, SIZE).bg[1:12, :70].copy()
    _press(world, cfg, state, "down")  # the highlight stays on as the selection moves
    assert state.highlight is True and (plain != shown).any()
    _press(world, cfg, state, " ")
    hidden = compose_history_frame(world, cfg, state, SIZE).bg[1:12, :70].copy()
    assert state.highlight is False and (hidden == plain).all()


def test_leaving_the_powers_list_hides_the_highlight(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t", " ", "\t")
    assert state.focus == "time" and state.highlight is False


def test_page_down_in_the_time_focus_pages_the_chronicle(world: World, cfg: Config) -> None:
    state = initial_state(world, cfg)
    _press(world, cfg, state, "pagedown")
    assert not state.highlight and state.scroll > 0


def test_the_selection_follows_the_power_across_the_stops(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    chosen = state.selected
    _press(world, cfg, state, "[", "[")
    assert state.selected == chosen


def test_a_power_that_does_not_yet_exist_says_so(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    state.selected = max(r.id for r in world.realms if r.founded > 100)
    state.at = (5, 1)
    assert "not yet: begins in year" in "\n".join(_text(world, cfg, state))


def test_the_hints_follow_the_focus(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    assert "choose a power" in _text(world, cfg, state)[-1]


def test_the_tile_key_reaches_the_present_when_nothing_more_happens_at_the_tile(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import tile_moments

    tile = _tile_of_a_battle(world)
    own = tile_moments(world, cfg, tile)
    state = initial_state(world, cfg, own[0], tile)
    for _ in range(len(own) + 1):
        _press(world, cfg, state, "}")
    assert state.at[:2] == (world.year, cfg.get("history.months_per_year"))


def test_the_tile_key_goes_back_from_the_present_to_the_tiles_last_event(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import tile_moments

    tile = _tile_of_a_battle(world)
    own = tile_moments(world, cfg, tile)
    state = initial_state(world, cfg, own[-1], tile)
    _press(world, cfg, state, "{")
    assert state.at == own[-2]


# --- the start and the years in the profile -----------------------------------------------------------------------


def test_the_viewer_opens_at_the_start_before_any_event(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import START

    state = initial_state(world, cfg)
    assert state.at == START == state.moments[0] and "the start" in _text(world, cfg, state)[0]


def test_the_start_is_before_every_event_and_change(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import START

    assert START < min((e.year, e.month) for e in world.chronicle)
    assert all(c.moment > START for c in world.territory)


def test_the_home_key_goes_to_the_start_and_stepping_back_stays_there(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import START

    state = initial_state(world, cfg)
    _press(world, cfg, state, "end", "home", "[")
    assert state.at == START and state.message == "nothing earlier"


def test_the_map_at_the_start_has_no_realm_land(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import START

    assert (world.owners_at(*START) < 0).all()


def test_the_tile_keys_reach_the_start_too(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import START, tile_moments

    assert tile_moments(world, cfg, (60, 30))[0] == START


def test_the_profile_gives_years_not_dates(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import _years

    assert (_years(300, 260), _years(300, 299), _years(300, 300)) == (
        "for 40 years",
        "for 1 year",
        "for less than a year",
    )


def test_the_powers_panel_shows_how_long_a_ruler_has_ruled(world: World, cfg: Config) -> None:
    state = _at_present(world, cfg)
    _press(world, cfg, state, "\t")
    text = "\n".join(_text(world, cfg, state))
    assert "ruler:" in text and "reigning:" in text and " years" in text


# --- one stop per event, a fixed profile layout ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def crowded(cfg: Config) -> World:
    """Seed 42 with two listed events of one year moved into one month (ones that change no land)."""
    made = pipeline.generate(cfg, 42)
    changing = {c.event_id for c in made.territory}
    major = [e for e in made.chronicle if e.salience == "major" and e.id not in changing]
    first, second = next(
        (a, b) for a, b in zip(major, major[1:], strict=False) if a.year == b.year and b.id == a.id + 1
    )
    second.month = first.month
    return made


def _same_month_pair(world: World):
    """Two listed events of one year and month, next to each other in the chronicle."""
    major = [e for e in world.chronicle if e.salience == "major"]
    return next((a, b) for a, b in zip(major, major[1:], strict=False) if (a.year, a.month) == (b.year, b.month))


def test_two_events_of_one_month_are_two_stops(crowded: World, cfg: Config) -> None:
    first, second = _same_month_pair(crowded)
    moments = change_moments(crowded, cfg)
    assert (first.year, first.month, first.id) in moments and (second.year, second.month, second.id) in moments


def test_stepping_goes_from_one_event_to_the_next_even_in_one_month(crowded: World, cfg: Config) -> None:
    first, second = _same_month_pair(crowded)
    state = initial_state(crowded, cfg, (first.year, first.month, first.id))
    _press(crowded, cfg, state, "]")
    assert state.at == (second.year, second.month, second.id)


def _highlighted_text(world: World, cfg: Config, state: HistoryState) -> str:
    """The text of the chronicle rows drawn on the highlight background."""
    grid = compose_history_frame(world, cfg, state, SIZE)
    highlight = np.array(cfg.get("history.viewer.current_bg"), dtype=np.uint8)
    rows = np.flatnonzero((grid.bg[:, 80:100] == highlight).all(axis=2).any(axis=1))
    return " ".join("".join(grid.glyph[row, 74:]).strip() for row in rows)


def test_only_the_selected_event_is_highlighted(crowded: World, cfg: Config) -> None:
    first, second = _same_month_pair(crowded)
    state = initial_state(crowded, cfg, (first.year, first.month, first.id))
    one = _highlighted_text(crowded, cfg, state)
    state.at = (second.year, second.month, second.id)
    two = _highlighted_text(crowded, cfg, state)
    assert first.text.split()[0] in one and second.text.split()[0] in two
    assert first.text not in two.replace("\n", " ") and second.text not in one.replace("\n", " ")


def _profile_labels(world: World, cfg: Config, owner: int, at) -> list[str]:
    from biomegen.explorer.history_viewer import _profile_rows

    state = initial_state(world, cfg)
    state.selected, state.at = owner, at
    return ["".join(text for text, _ in row)[:13].strip() for row in _profile_rows(world, cfg, state, 46)]


def test_every_power_has_its_rows_in_the_same_places(world: World, cfg: Config) -> None:
    present = present_stop(world, cfg)
    layouts = {tuple(_profile_labels(world, cfg, owner, present)[1:24]) for owner in [r.id for r in world.realms]}
    assert len(layouts) == 1


def test_a_power_that_does_not_exist_keeps_the_layout_with_placeholders(world: World, cfg: Config) -> None:
    present = present_stop(world, cfg)
    realm = max(world.realms, key=lambda r: r.founded)
    alive = _profile_labels(world, cfg, realm.id, present)
    absent = _profile_labels(world, cfg, realm.id, (0, 0, -1))
    assert alive[1:24] == absent[1:24]


def test_a_missing_fact_shows_a_dash(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import _profile_rows

    state = initial_state(world, cfg)
    state.selected, state.at = max(world.realms, key=lambda r: r.founded).id, (0, 0, -1)
    rows = ["".join(text for text, _ in row) for row in _profile_rows(world, cfg, state, 46)]
    assert any(text.startswith("ruler:") and text.endswith("-") for text in rows)


def test_the_relations_list_starts_under_a_fixed_heading(world: World, cfg: Config) -> None:
    present = present_stop(world, cfg)
    rows = {owner: _profile_labels(world, cfg, owner, present) for owner in [r.id for r in world.realms]}
    assert len({labels.index("relations:") for labels in rows.values()}) == 1


def test_the_vassal_rows_are_reserved(world: World, cfg: Config) -> None:
    present = present_stop(world, cfg)
    heads = {_profile_labels(world, cfg, r.id, present).index("vassals:") for r in world.realms}
    heads2 = {_profile_labels(world, cfg, r.id, present).index("relations:") for r in world.realms}
    assert len(heads) == 1 and len(heads2) == 1 and next(iter(heads2)) - next(iter(heads)) == 4


def test_a_realm_exists_in_the_year_of_its_split_before_the_split_month(world: World, cfg: Config) -> None:
    from biomegen.world.powers import power_profile

    for predecessor in world.predecessors:
        split = next(e for e in world.chronicle if e.kind == "secession" and e.predecessor_ids == [predecessor.id])
        before = (split.year, split.month, split.id - 1)
        assert power_profile(world, cfg, -1000 - predecessor.id, before).exists


# --- names in their realm's colour ----------------------------------------------------------------------------------


def _colors(world: World, cfg: Config, owner: int, at) -> dict[str, tuple]:
    """Each coloured piece of text of a profile, by its text."""
    from biomegen.explorer.history_viewer import _profile_rows

    state = initial_state(world, cfg)
    state.selected, state.at = owner, at
    return {text: color for row in _profile_rows(world, cfg, state, 80) for text, color in row if color is not None}


def test_the_ruler_and_the_seat_are_in_the_realms_colour(world: World, cfg: Config) -> None:
    realm = max(world.realms, key=lambda r: int((world.realm_id == r.id).sum()))
    colors = _colors(world, cfg, realm.id, present_stop(world, cfg))
    assert colors[world.pois[realm.seat_poi].name] == realm.color
    assert realm.color in colors.values()


def test_a_liege_and_its_vassals_are_in_their_own_colours(world: World, cfg: Config) -> None:
    present = present_stop(world, cfg)
    vassal = next(r for r in world.realms if r.liege >= 0)
    lord = world.realms[world.top_realm(vassal.id)]
    assert _colors(world, cfg, vassal.id, present)[lord.short] == lord.color
    assert _colors(world, cfg, lord.id, present)[vassal.short] == vassal.color


def test_the_powers_in_a_relation_are_in_their_colours(world: World, cfg: Config) -> None:
    present = present_stop(world, cfg)
    realm = next(
        r for r in world.realms if r.id in {i for e in world.chronicle if e.kind == "rivalry" for i in e.realm_ids}
    )
    colors = _colors(world, cfg, realm.id, present)
    assert {r.color for r in world.realms if r.short in colors and colors[r.short] == r.color}


def test_the_status_line_colours_the_powers_it_names(world: World, cfg: Config) -> None:
    from biomegen.explorer.history_viewer import moment_segments

    change = next(c for c in world.territory if c.kind == "expansion")
    colors = {color for text, color in moment_segments(world, cfg, change.key) if color is not None}
    realm = world.realms[change.to_owner] if change.to_owner >= 0 else None
    assert colors and (realm is None or realm.color in colors)


def _map_bg(world: World, cfg: Config, state: HistoryState) -> np.ndarray:
    return compose_history_frame(world, cfg, state, SIZE).bg[1:12, :70].copy()


def _war_state(world: World, cfg: Config) -> HistoryState:
    event = next(e for e in world.chronicle if e.kind == "war" and e.location == (-1, -1) and e.realm_ids)
    return initial_state(world, cfg, (event.year, event.month, event.id))


def test_a_placed_event_lights_its_tile(world: World, cfg: Config) -> None:
    # A stop whose event has a location focuses on cells, not on realms
    event = next(e for e in world.chronicle if e.salience == "major" and e.location != (-1, -1) and e.kind != "war")
    state = initial_state(world, cfg, (event.year, event.month, event.id))
    cells, _ = event_focus(world, state)
    assert event.location[1] * world.width + event.location[0] in cells


def test_an_event_with_no_place_lights_its_realms(world: World, cfg: Config) -> None:
    # A war has no tile, so the focus is its realms' land
    state = _war_state(world, cfg)
    event = next(e for e in world.chronicle if (e.year, e.month, e.id) == state.at)
    _, owners = event_focus(world, state)
    assert set(event.realm_ids) <= owners


def test_space_lights_the_events_on_the_map_and_space_again_hides_them(world: World, cfg: Config) -> None:
    state = _war_state(world, cfg)
    plain = _map_bg(world, cfg, state)
    _press(world, cfg, state, " ")
    lit = _map_bg(world, cfg, state)
    _press(world, cfg, state, " ")
    assert state.highlight is False and (lit != plain).any() and (_map_bg(world, cfg, state) == plain).all()


def test_every_stop_with_minor_events_has_a_focus() -> None:
    # Seed 7904325738223517320 has creation events naming points of interest past World.pois: they must not crash
    config = load_config(None)
    made = pipeline.generate(config, 7904325738223517320)
    for stop in change_moments(made, config, minor=True):
        cells, owners = event_focus(made, initial_state(made, config, stop))
        assert cells.ndim == 1 and isinstance(owners, set)

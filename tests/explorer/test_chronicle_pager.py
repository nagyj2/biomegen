"""Tests for the chronicle pager: key resolution, frame composition, filters, search and the whole loop."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.chronicle_pager import (
    PagerState,
    _suggestions_of,
    apply_action,
    compose_pager_frame,
    parse_years,
    resolve_pager_action,
    run_chronicle,
)
from biomegen.explorer.panel import panel_color
from biomegen.world.chronicle import ChronicleFilter
from biomegen.world.entities import EVENT_KINDS, POI, ChronicleEvent, Realm, Ruler
from biomegen.world.world import World
from tests.explorer.replay import RecordingOut
from tests.explorer.test_app import ScriptedKeys

SIZE = (60, 12)  # 9 body rows
EVENT_COUNT = 30


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _world() -> World:
    """Thirty one-line events, years 100, 110, ...; even ids are wars naming the realm, odd ids are peaces."""
    world = World(4, 4, 9)
    world.island_name = "Testisle"
    world.year = 500
    world.realms = [Realm(id=0, kind="major", name="Kingdom of A")]
    world.chronicle = [
        ChronicleEvent(
            i,
            100 + 10 * i,
            "war" if i % 2 == 0 else "peace",
            [0] if i % 2 == 0 else [],
            text=f"Event {i} happens" + (" with a dragon." if i == 20 else "."),
        )
        for i in range(EVENT_COUNT)
    ]
    return world


def _screen(world: World, cfg: Config, state: PagerState, help_open: bool = False) -> list[str]:
    grid = compose_pager_frame(world, cfg, state, SIZE, help_open)
    return ["".join(row).rstrip() for row in grid.glyph]


def _press(world: World, cfg: Config, state: PagerState, *tokens: str) -> None:
    """Resolve and apply each token as the loop would (compose first, so scroll is clamped)."""
    for token in tokens:
        compose_pager_frame(world, cfg, state, SIZE)
        apply_action(world, cfg, state, resolve_pager_action(token, cfg, state.prompt is not None), SIZE)
    compose_pager_frame(world, cfg, state, SIZE)


@pytest.mark.parametrize(
    ("token", "action"),
    [
        ("up", ("scroll", -1)),
        ("down", ("scroll", 1)),
        ("k", ("scroll", -1)),
        ("j", ("scroll", 1)),
        ("w", ("scroll", -1)),
        ("s", ("scroll", 1)),
        ("shift-down", ("scroll", 8)),
        ("J", ("scroll", 8)),
        ("K", ("scroll", -8)),
        ("pagedown", ("page", 1)),
        (" ", ("page", 1)),
        ("pageup", ("page", -1)),
        ("home", ("top",)),
        ("g", ("top",)),
        ("end", ("bottom",)),
        ("G", ("bottom",)),
        ("/", ("prompt", "search")),
        ("n", ("match", 1)),
        ("N", ("match", -1)),
        ("v", ("cycle_kind",)),
        ("y", ("prompt", "years")),
        ("p", ("prompt", "realm")),
        ("c", ("clear",)),
        ("?", ("help",)),
        ("q", ("quit",)),
        ("esc", ("quit",)),
        ("eof", ("quit",)),
        ("resize", ("resize",)),
        ("x", ("none",)),
    ],
)
def test_default_keys_resolve_to_actions(cfg: Config, token: str, action: tuple) -> None:
    assert resolve_pager_action(token, cfg) == action


@pytest.mark.parametrize(
    ("token", "action"),
    [
        ("a", ("type", "a")),
        ("up", ("choice", -1)),
        ("down", ("choice", 1)),
        ("\t", ("complete",)),
        ("\x7f", ("backspace",)),
        ("\r", ("submit",)),
        ("esc", ("cancel",)),
        ("q", ("type", "q")),  # while typing, even the quit key is a letter
    ],
)
def test_keys_while_a_prompt_is_open(cfg: Config, token: str, action: tuple) -> None:
    assert resolve_pager_action(token, cfg, prompting=True) == action


def test_a_rebound_key_wins_over_the_scroll_letters() -> None:
    config = load_config(None)
    config.data["keys"]["filter_clear"] = "j"
    assert resolve_pager_action("j", config) == ("clear",)


@pytest.mark.parametrize(
    ("text", "years"),
    [("100-300", (100, 300)), ("100-", (100, None)), ("-300", (None, 300)), ("250", (250, 250)), (" 5 - 9 ", (5, 9))],
)
def test_parse_years(text: str, years: tuple) -> None:
    assert parse_years(text) == years


@pytest.mark.parametrize("text", ["abc", "9-1", "1-2-3"])
def test_unreadable_year_ranges_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_years(text)


def test_the_first_frame_shows_the_title_and_the_first_events(cfg: Config) -> None:
    screen = _screen(_world(), cfg, PagerState())
    assert [screen[0], screen[1].split(), screen[9].split()] == [
        "The Chronicle of Testisle (year 500)",
        ["100", "war", "Event", "0", "happens."],
        ["180", "war", "Event", "8", "happens."],
    ]


def test_the_status_line_counts_events_and_lines(cfg: Config) -> None:
    assert "30/30 events" in _screen(_world(), cfg, PagerState())[10]


def test_the_hint_line_shows_the_bound_keys(cfg: Config) -> None:
    assert "[/] search" in _screen(_world(), cfg, PagerState())[11]


def test_scrolling_down_moves_the_view_one_line(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "down")
    assert _screen(_world(), cfg, state)[1].split()[:2] == ["110", "peace"]


def test_scrolling_up_at_the_top_stays_at_the_top(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "up", "k")
    assert state.scroll == 0


def test_a_page_scrolls_a_screen_less_one_line(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "pagedown")
    assert state.scroll == 8


def test_the_end_shows_the_last_event_on_the_last_row(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "end")
    assert _screen(_world(), cfg, state)[9].split()[:2] == ["390", "peace"]


def test_scrolling_past_the_end_is_clamped(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "end", "down", "J")
    assert state.scroll == EVENT_COUNT - 9


def test_the_kind_key_cycles_through_the_kinds_and_back_to_all(cfg: Config) -> None:
    state = PagerState()
    world = _world()
    seen = []
    for _ in range(len(EVENT_KINDS) + 2):
        _press(world, cfg, state, "v")
        seen.append(state.chronicle_filter.kinds)
    assert seen == [*((kind,) for kind in EVENT_KINDS), (), (EVENT_KINDS[0],)]


def test_a_kind_filter_lists_only_that_kind(cfg: Config) -> None:
    state = PagerState(chronicle_filter=ChronicleFilter(kinds=("peace",)))
    screen = _screen(_world(), cfg, state)
    assert [line.split()[1] for line in screen[1:10]] == ["peace"] * 9


def test_changing_a_filter_returns_to_the_top(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "end", "v")
    assert state.scroll == 0


def test_the_years_prompt_filters_by_range(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "y", *"150-170", "\r")
    assert [e.id for e in state.layout.events] == [5, 6, 7]


def test_a_bad_year_range_leaves_the_filter_and_says_why(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "y", *"nope", "\r")
    assert (state.chronicle_filter, "years:" in state.message) == (ChronicleFilter(), True)


def test_the_realm_prompt_keeps_events_naming_the_realm(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "p", *"kingdom", "\r")
    assert {e.kind for e in state.layout.events} == {"war"}


def test_backspace_edits_the_prompt_text(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "p", *"kingx", "\x7f", *"dom", "\r")
    assert state.chronicle_filter.realm == "kingdom"


def test_escape_cancels_a_prompt_without_filtering(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "p", *"king", "esc")
    assert (state.prompt, state.chronicle_filter) == (None, ChronicleFilter())


def test_an_open_prompt_shows_what_was_typed(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"dra")
    assert _screen(_world(), cfg, state)[10] == " search: dra_"


def test_a_search_jumps_to_its_first_match(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"dragon", "\r")
    assert "dragon" in _screen(_world(), cfg, state)[1]


def test_a_search_with_no_match_says_so(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"unicorn", "\r")
    assert (state.scroll, state.message) == (0, "no match")


def test_next_match_moves_to_the_following_event(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 1", "\r", "n")  # matches are events 1 and 10-19
    assert state.current == 10


def test_previous_match_goes_back(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 1", "\r", "n", "N")
    assert state.current == 1


def test_next_match_wraps_to_the_first(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"dragon", "\r", "n")
    assert "dragon" in _screen(_world(), cfg, state)[1]


def test_next_match_without_a_search_says_so(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "n")
    assert state.message == "no search yet"


def test_the_matches_are_highlighted(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"dragon", "\r")
    grid = compose_pager_frame(_world(), cfg, state, SIZE)
    col = _screen(_world(), cfg, state)[1].index("dragon")
    assert tuple(grid.bg[1, col]) == tuple(cfg.get("history.colors.match_current"))  # the only match is the current one


def test_clear_drops_filters_and_search(cfg: Config) -> None:
    state = PagerState(chronicle_filter=ChronicleFilter(kinds=("war",)), query="x")
    _press(_world(), cfg, state, "c")
    assert (state.chronicle_filter, state.query) == (ChronicleFilter(), "")


def test_no_matching_events_shows_a_note(cfg: Config) -> None:
    state = PagerState(chronicle_filter=ChronicleFilter(text="unicorn"))
    assert "(no events match)" in _screen(_world(), cfg, state)[1]


def test_the_help_overlay_lists_the_keys(cfg: Config) -> None:
    text = "\n".join(_screen(_world(), cfg, PagerState(), help_open=True))
    assert "Chronicle keys" in text and "next / previous" in text


def test_a_tiny_terminal_gets_a_note(cfg: Config) -> None:
    grid = compose_pager_frame(_world(), cfg, PagerState(), (10, 3))
    assert "".join(grid.glyph[0]).startswith("terminal")


def test_a_long_event_wraps_under_the_text_column(cfg: Config) -> None:
    world = _world()
    world.chronicle[0].text = "word " * 30
    screen = _screen(world, cfg, PagerState())
    assert screen[2].startswith(" " * 19) and screen[2].strip().startswith("word")


def _run(cfg: Config, *tokens: str, chronicle_filter: ChronicleFilter | None = None) -> RecordingOut:
    out = RecordingOut(SIZE[1], SIZE[0])
    run_chronicle(
        _world(),
        cfg,
        "none",
        chronicle_filter,
        reader=ScriptedKeys(*tokens),
        out=out,
        get_size=lambda: SIZE,
    )
    return out


def test_the_loop_draws_then_quits_on_q(cfg: Config) -> None:
    out = _run(cfg)
    assert out.frames[-1][0].rstrip() == "The Chronicle of Testisle (year 500)"


def test_the_loop_scrolls_with_the_keys(cfg: Config) -> None:
    out = _run(cfg, "j", "j", "j")
    assert out.frames[-1][1].split()[:2] == ["130", "peace"]


def test_the_loop_starts_from_the_given_filter(cfg: Config) -> None:
    out = _run(cfg, chronicle_filter=ChronicleFilter(kinds=("peace",)))
    assert out.frames[-1][1].split()[1] == "peace"


def test_the_start_text_filter_also_starts_the_search(cfg: Config) -> None:
    out = _run(cfg, chronicle_filter=ChronicleFilter(text="dragon"))
    assert "search 'dragon': 1 found" in out.frames[-1][10]


def test_help_opens_and_any_key_closes_it(cfg: Config) -> None:
    out = _run(cfg, "?", "j")
    assert ["Chronicle keys" in "\n".join(frame) for frame in out.frames[-3:-1]] == [True, False]


def test_a_search_typed_in_the_loop_jumps(cfg: Config) -> None:
    out = _run(cfg, "/", *"dragon", "\r")
    assert "dragon" in out.frames[-1][1]


def test_the_loop_restores_the_screen_on_quit(cfg: Config) -> None:
    assert _run(cfg).getvalue().endswith("\x1b[?1049l")


def test_the_loop_survives_a_resize_token(cfg: Config) -> None:
    out = _run(cfg, "resize", "j")
    assert out.frames[-1][1].split()[:2] == ["110", "peace"]


def _named_world() -> World:
    """The thirty events, where event 4 also names a ruler and a settlement (as ids and in its refs)."""
    world = _world()
    world.realms = [Realm(id=0, kind="major", name="Kingdom of A", ruler="Queen Mab")]
    world.rulers = [Ruler(id=0, realm_id=0, name="Queen Mab", from_year=100, to_year=200, style="x")]
    world.pois = [POI(kind="village", x=1, y=1, interior_seed=1, name="Dunmere")]
    world.chronicle[4].text = "Queen Mab settles Dunmere."
    world.chronicle[4].refs = [(0, 9, "ruler", 0), (18, 25, "poi", 0)]
    world.chronicle[4].poi_ids = [0]
    return world


def _hits(world: World, cfg: Config, *tokens: str) -> list[int]:
    state = PagerState()
    _press(world, cfg, state, *tokens)
    return [event.id for event in state.layout.events]


def test_the_name_filter_matches_a_ruler(cfg: Config) -> None:
    assert _hits(_named_world(), cfg, "p", *"queen", "\r") == [4]


def test_the_name_filter_matches_a_settlement(cfg: Config) -> None:
    assert _hits(_named_world(), cfg, "p", *"dunm", "\r") == [4]


def test_the_realm_prompt_lists_matching_names_above_the_status_line(cfg: Config) -> None:
    state = PagerState()
    world = _named_world()
    _press(world, cfg, state, "p", *"m")
    screen = _screen(world, cfg, state)
    assert [line.split("  ")[0].strip() for line in screen[7:10]] == ["Dunmere", "Kingdom of A", "Queen Mab"]


def test_suggestions_put_prefix_matches_first() -> None:
    from biomegen.explorer.chronicle_pager import suggestions

    names = [("Adun", "realm"), ("Dunmere", "poi"), ("Mundun", "ruler")]
    assert suggestions(names, "dun") == [names[1], names[0], names[2]]


def test_down_then_enter_takes_the_picked_suggestion(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"m", "down", "down", "\r")
    assert state.chronicle_filter.realm == "Kingdom of A"  # "m" finds all three names; the second is picked


def test_up_from_no_pick_goes_to_the_last_suggestion(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", "up")
    assert state.prompt.choice == 2


def test_down_past_the_last_suggestion_returns_to_none(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", "down", "down", "down", "down")
    assert state.prompt.choice == -1


def test_tab_completes_the_shared_prefix(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"k", "\t")
    assert state.prompt.text == "Kingdom of A"


def test_tab_takes_the_picked_suggestion(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"e", "down", "down", "\t")
    assert state.prompt.text == "Queen Mab"  # "e" finds Dunmere and Queen Mab


def test_typing_drops_the_pick(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", "down", "x")
    assert state.prompt.choice == -1


def test_the_prompt_hints_name_the_keys(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p")
    assert "[Tab] complete" in _screen(_named_world(), cfg, state)[11]


def test_next_goes_forward_through_every_match_and_wraps(cfg: Config) -> None:
    # Matches are events 1 and 10-19 (11 matches); n from the first visits each in order, then wraps to it.
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 1", "\r")
    visited = [state.current]
    for _ in range(11):
        _press(_world(), cfg, state, "n")
        visited.append(state.current)
    assert visited == [1, *range(10, 20), 1]


def test_previous_goes_backward_and_wraps(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 1", "\r", "N")
    assert state.current == 19


def test_next_moves_even_when_the_matches_share_the_last_page(cfg: Config) -> None:
    # Both matches are on the final page, which cannot scroll further; the current match must still change.
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 2", "\r")  # events 2 and 20-29, the last ten on one page
    first = state.current
    _press(_world(), cfg, state, "n")
    assert (first, state.current) == (2, 20)


def test_the_current_match_has_its_own_background(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 2", "\r", "n")
    grid = compose_pager_frame(_world(), cfg, state, SIZE)
    shown = _screen(_world(), cfg, state)
    row = next(i for i, line in enumerate(shown) if line.split()[:1] == ["300"])
    assert tuple(grid.bg[row, shown[row].index("Event 2")]) == tuple(cfg.get("history.colors.match_current"))


def test_the_status_line_says_which_match_it_is_on(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 1", "\r", "n")
    assert "2/11 found" in _screen(_world(), cfg, state)[10]


def test_the_whole_help_title_is_highlighted(cfg: Config) -> None:
    grid = compose_pager_frame(_world(), cfg, PagerState(), SIZE, help_open=True)
    row = next(i for i, line in enumerate(_screen(_world(), cfg, PagerState(), True)) if "Chronicle keys" in line)
    col = _screen(_world(), cfg, PagerState(), True)[row].index("Chronicle keys")
    head = tuple(panel_color(cfg, "head"))
    assert all(tuple(grid.fg[row, col + i]) == head for i in range(len("Chronicle keys")))


def _suggestion_rows(cfg: Config) -> tuple:
    state = PagerState()
    world = _named_world()
    _press(world, cfg, state, "p", *"m")
    return compose_pager_frame(world, cfg, state, SIZE), _screen(world, cfg, state)


def test_each_suggestion_ends_with_what_kind_of_name_it_is(cfg: Config) -> None:
    _, screen = _suggestion_rows(cfg)
    assert [line.split(maxsplit=1)[1].rsplit("  ", 1)[-1].strip() for line in screen[7:10]] == [
        "settlement",
        "realm",
        "ruler",
    ]


def test_the_kind_tag_is_at_the_right_edge(cfg: Config) -> None:
    _, screen = _suggestion_rows(cfg)
    assert screen[7].endswith("settlement ") or screen[7].endswith("settlement")


def test_the_kind_tag_has_its_neutral_colour(cfg: Config) -> None:
    grid, screen = _suggestion_rows(cfg)
    col = screen[7].index("settlement")
    assert tuple(grid.fg[7, col]) == tuple(cfg.get("history.colors.type_poi"))


def test_the_kinds_have_different_colours(cfg: Config) -> None:
    colours = {
        tuple(cfg.get(f"history.colors.type_{kind}")) for kind in ("realm", "fallen", "predecessor", "ruler", "poi")
    }
    assert len(colours) == 5


def test_the_last_term_is_what_gets_suggestions(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"kingdom of a|dun")
    assert [name for name, _kind in _suggestions_of(_named_world(), state)] == ["Dunmere"]


def test_tab_completes_only_the_last_term(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"king&dun", "\t")
    assert state.prompt.text == "king&Dunmere"


def test_a_picked_suggestion_replaces_only_the_last_term(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"queen|d", "down", "\r")
    assert state.chronicle_filter.realm == "queen|Dunmere"


def test_the_name_filter_ignores_spaces_round_its_terms(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"queen | dunmere ", "\r")
    assert [e.id for e in state.layout.events] == [4]


def test_suggestions_ignore_spaces_after_an_operator(cfg: Config) -> None:
    state = PagerState()
    _press(_named_world(), cfg, state, "p", *"queen & dun")
    assert [name for name, _kind in _suggestions_of(_named_world(), state)] == ["Dunmere"]


def test_a_search_with_or_finds_both(cfg: Config) -> None:
    state = PagerState()
    _press(_world(), cfg, state, "/", *"event 3 |dragon", "\r")
    assert [state.current] + _hits_of(state) == [3, 3, 20]


def _hits_of(state: PagerState) -> list[int]:
    return state.layout.matches


def test_the_salience_key_toggles_between_major_only_and_all(cfg: Config) -> None:
    state = PagerState()
    world = _world()
    seen = []
    for _ in range(3):
        _press(world, cfg, state, "m")
        seen.append(state.chronicle_filter.salience)
    assert seen == ["all", "major", "all"]

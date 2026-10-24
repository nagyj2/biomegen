"""Tests for the simulation as the explorer's tick source: playback speed, the panel clock and the restart."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.app import run
from biomegen.explorer.panel import build_panel
from biomegen.explorer.state import ViewState
from biomegen.explorer.ticks import Clock, NoTicks, SimTicks, sim_status
from biomegen.render.layers import Seen
from biomegen.sim.hydrate import hydrate
from biomegen.world.world import World
from tests.explorer.replay import RecordingOut
from tests.explorer.test_app import _village_world
from tests.explorer.test_ticks import FakeSource, FakeTime, Waiting


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _world() -> World:
    world = _village_world()
    world.year = 1200
    world.master_seed = 5
    return world


def _source(cfg: Config) -> SimTicks:
    return SimTicks.start(_world(), cfg)


# ---------------------------------------------------------------- how many ticks are due
def test_the_first_poll_runs_no_ticks(cfg: Config) -> None:
    assert _source(cfg).due(100.0, 1.0) == 0


def test_a_tenth_of_a_second_at_normal_speed_is_a_tick(cfg: Config) -> None:
    # sim.playback.ticks_per_second is 10.
    source = _source(cfg)
    source.due(0.0, 1.0)
    assert source.due(0.1, 1.0) == 1


def test_a_fraction_of_a_tick_is_kept_for_the_next_poll(cfg: Config) -> None:
    source = _source(cfg)
    source.due(0.0, 1.0)
    assert (source.due(0.05, 1.0), source.due(0.10, 1.0)) == (0, 1)


def test_the_speed_scales_the_ticks(cfg: Config) -> None:
    source = _source(cfg)
    source.due(0.0, 8.0)
    assert source.due(0.1, 8.0) == 8


def test_a_long_gap_never_makes_a_burst_of_catch_up_ticks(cfg: Config) -> None:
    # A pause (the loop does not poll) or a slow frame counts at most sim.playback.max_frame_seconds (0.25 s).
    source = _source(cfg)
    source.due(0.0, 1.0)
    assert source.due(500.0, 1.0) == 2


def test_a_clock_that_goes_backwards_runs_no_ticks(cfg: Config) -> None:
    source = _source(cfg)
    source.due(10.0, 1.0)
    assert source.due(9.0, 1.0) == 0


# ---------------------------------------------------------------- running and restarting
def test_the_source_is_active_and_holds_the_simulations_state(cfg: Config) -> None:
    source = _source(cfg)
    assert source.active and source.state is source.simulation.state


def test_running_ticks_advances_the_simulation(cfg: Config) -> None:
    source = _source(cfg)
    start = source.state.tick
    source.tick(25)
    assert source.state.tick == start + 25


def test_running_ticks_with_no_behaviour_changes_nothing(cfg: Config) -> None:
    assert _source(cfg).tick(25) is False


def test_the_source_starts_where_hydrate_does(cfg: Config) -> None:
    world = _world()
    source = SimTicks.start(world, cfg)
    assert source.state.tick == hydrate(world, cfg, world.master_seed).tick


def test_a_reset_starts_the_simulation_again_on_the_world_given(cfg: Config) -> None:
    source = _source(cfg)
    first, start = source.state, source.state.tick
    source.tick(100)
    source.reset(_world())
    assert source.state is not first and source.state.tick == start


def test_a_reset_forgets_the_time_that_was_owed(cfg: Config) -> None:
    source = _source(cfg)
    source.due(0.0, 1.0)
    source.due(0.05, 1.0)
    source.reset(_world())
    assert (source.due(1000.0, 1.0), source.due(1000.05, 1.0)) == (0, 0)


# ---------------------------------------------------------------- the clock in the panel
def test_a_source_that_does_not_simulate_has_no_status(cfg: Config) -> None:
    assert (sim_status(NoTicks(), Clock(), cfg), sim_status(FakeSource(), Clock(), cfg)) == ("", "")


def test_the_status_gives_the_date_the_tick_in_the_month_and_the_speed(cfg: Config) -> None:
    assert sim_status(_source(cfg), Clock(), cfg) == "sim 1201/01 +00/30 x1"


def test_the_status_follows_the_ticks(cfg: Config) -> None:
    source = _source(cfg)
    source.tick(30 * 2 + 5)
    assert sim_status(source, Clock(), cfg) == "sim 1201/03 +05/30 x1"


def test_the_status_says_when_the_clock_is_paused(cfg: Config) -> None:
    assert sim_status(_source(cfg), Clock(paused=True), cfg).endswith("paused")


def test_the_status_gives_a_slow_speed_as_a_fraction(cfg: Config) -> None:
    assert sim_status(_source(cfg), Clock(index=0), cfg).endswith("x0.25")


def _title_row(status: str, width: int = 100, view: str = "terrain") -> str:
    world = _world()
    world.island_name = "Testland"
    grid = build_panel(world, load_config(None), ViewState(cx=20, cy=10), view, Seen(), width, 15, sim_status=status)
    return "".join(grid.glyph[1].tolist())


def test_the_panel_shows_the_status_at_the_right_end_of_the_island_line() -> None:
    assert "sim 1201/01 +00/30 x1" in _title_row("sim 1201/01 +00/30 x1")


def test_the_panel_without_a_status_has_a_blank_field() -> None:
    assert _title_row("").rstrip().endswith("floor 0")


def test_the_status_never_moves_the_title() -> None:
    plain, with_status = _title_row(""), _title_row("sim 1201/01 +00/30 x1")
    cut = plain.index("floor 0") + len("floor 0")
    assert plain[:cut] == with_status[:cut]


def test_the_status_starts_on_the_same_column_whatever_the_speed_says() -> None:
    fast, paused = _title_row("sim 1201/01 +00/30 x8"), _title_row("sim 1201/01 +00/30 paused")
    assert fast.index("sim 1201") == paused.index("sim 1201")


def test_a_narrow_panel_clips_the_status_and_keeps_the_title() -> None:
    row = _title_row("sim 1201/01 +00/30 x1", width=60)
    assert row.startswith(" Testland   seed 1") and len(row) == 60


def test_no_other_row_of_the_panel_changes_with_the_status() -> None:
    world = _world()
    plain = build_panel(world, load_config(None), ViewState(cx=20, cy=10), "terrain", Seen(), 100, 15)
    shown = build_panel(
        world,
        load_config(None),
        ViewState(cx=20, cy=10),
        "terrain",
        Seen(),
        100,
        15,
        sim_status="sim 1201/01 +00/30 x1",
    )
    assert (plain.glyph[[0, *range(2, 15)]] == shown.glyph[[0, *range(2, 15)]]).all()


# ---------------------------------------------------------------- the whole loop
def _loop(cfg: Config, source: SimTicks, keys: Waiting, regenerate=None) -> RecordingOut:
    out = RecordingOut(40, 100)
    fake = FakeTime()
    run(
        _world(),
        cfg,
        "none",
        reader=keys,
        out=out,
        get_size=lambda: (100, 40),
        ticks=source,
        now=fake.now,
        sleep=fake.sleep,
        regenerate=regenerate,
    )
    return out


def test_the_loop_runs_the_simulation_and_shows_its_clock(cfg: Config) -> None:
    source = _source(cfg)
    start = source.state.tick
    out = _loop(cfg, source, Waiting(8, "q"))
    assert source.state.tick > start and any("sim 1201/01 +" in "\n".join(frame) for frame in out.frames)


def test_the_loop_holds_the_simulation_while_paused(cfg: Config) -> None:
    source = _source(cfg)
    start = source.state.tick
    _loop(cfg, source, Waiting(0, "p", "q"))
    assert source.state.tick == start


def test_a_restart_starts_the_simulation_again(cfg: Config) -> None:
    source = _source(cfg)
    first = source.state
    _loop(cfg, source, Waiting(8, "r", "q"), regenerate=_world)
    assert source.state is not first


def test_the_loop_reads_the_world_through_the_new_state_after_a_restart(cfg: Config) -> None:
    # After r the reader is built on the source's new state: the clock shown is the restarted simulation's.
    source = _source(cfg)
    out = _loop(cfg, source, Waiting(8, "r", "q"), regenerate=_world)
    assert "sim 1201/01 +00/30" in "\n".join(out.frames[-1])

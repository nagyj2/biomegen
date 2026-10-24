"""Tests for the tick loop: each faction checks on its own beat, steps get the elapsed ticks, no step no change."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.registry import Registry
from biomegen.sim import cadence, steps
from biomegen.sim.engine import Simulation
from biomegen.sim.hydrate import hydrate
from biomegen.sim.steps import Check, Step
from biomegen.world.entities import Realm
from biomegen.world.sim_state import SimState
from biomegen.world.world import World

SEED = 42
FACTIONS = 8


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _world() -> World:
    """A bare world with a few realms: enough factions for the schedules, none of the cost of generating one."""
    world = World(8, 8, SEED)
    world.realms = [Realm(id=i, kind="major") for i in range(FACTIONS)]
    return world


class Recorder:
    """A step that records every check it sees (and says whether it changed anything)."""

    def __init__(self, changes: bool = False) -> None:
        self.seen: list[tuple[str, int, int, int, int]] = []
        self.changes = changes

    def __call__(self, sim: Simulation, check: Check) -> bool:
        self.seen.append((check.cadence, check.faction.realm_id, check.tick, check.elapsed, check.index))
        return self.changes


def _registries(**steps_by_cadence: dict[str, Step]) -> dict[str, Registry[Step]]:
    registries: dict[str, Registry[Step]] = {"economy": Registry("test_economy"), "strategy": Registry("test_strategy")}
    for cadence_name, named in steps_by_cadence.items():
        for name, step in named.items():
            registries[cadence_name].add(name, step)
    return registries


def _sim(cfg: Config, **steps_by_cadence: dict[str, Step]) -> Simulation:
    world = _world()
    return Simulation(world, cfg, SEED, steps=_registries(**steps_by_cadence))


def test_advancing_no_ticks_changes_nothing(cfg: Config) -> None:
    sim = _sim(cfg)
    start = sim.state.tick
    sim.advance(0)
    assert sim.state.tick == start


def test_advancing_moves_the_tick_by_the_count(cfg: Config) -> None:
    sim = _sim(cfg)
    start = sim.state.tick
    sim.advance(37)
    assert sim.state.tick == start + 37


def test_the_default_step_registries_are_empty() -> None:
    # 10a has no behaviour: the economy (10b) and diplomacy (10d) register their steps later.
    assert [list(registry.names()) for registry in steps.STEPS.values()] == [[], []]


def test_there_is_a_registry_for_every_default_cadence(cfg: Config) -> None:
    assert set(steps.STEPS) == set(cadence.cadence_names(cfg))


def test_a_cadence_with_no_registry_is_refused(cfg: Config) -> None:
    config = copy.deepcopy(cfg)
    config.data["sim"]["cadence"]["diplomacy"] = {"months": 2, "jitter_ticks": 1}
    with pytest.raises(ValueError, match="diplomacy"):
        Simulation(_world(), config, SEED)


def test_every_faction_checks_on_the_beat_the_cadence_gives_it(cfg: Config) -> None:
    # The recorded ticks of each faction equal its schedule computed from the pure functions alone.
    recorder = Recorder()
    sim = _sim(cfg, economy={"record": recorder})
    start = sim.state.tick
    sim.advance(200)
    for faction in range(FACTIONS):
        expected, tick, count = [], cadence.first_check(SEED, cfg, faction, "economy", start), 0
        while tick <= start + 200:
            expected.append(tick)
            count += 1
            tick = cadence.next_check(SEED, cfg, faction, "economy", tick, count)
        assert [t for c, f, t, _e, _i in recorder.seen if f == faction] == expected


def test_there_is_no_global_month_step(cfg: Config) -> None:
    # If checks came on a month boundary every recorded tick would be a multiple of the ticks per month.
    recorder = Recorder()
    sim = _sim(cfg, economy={"record": recorder})
    sim.advance(180)
    per_month = sim.state.ticks_per_month
    assert len({tick % per_month for _c, _f, tick, _e, _i in recorder.seen}) > 1


def test_no_tick_holds_every_factions_check(cfg: Config) -> None:
    recorder = Recorder()
    sim = _sim(cfg, strategy={"record": recorder})
    sim.advance(400)
    per_tick: dict[int, int] = {}
    for _c, _f, tick, _e, _i in recorder.seen:
        per_tick[tick] = per_tick.get(tick, 0) + 1
    assert max(per_tick.values()) < FACTIONS


def test_a_first_check_counts_its_elapsed_ticks_from_the_start(cfg: Config) -> None:
    recorder = Recorder()
    sim = _sim(cfg, economy={"record": recorder})
    start = sim.state.tick
    sim.advance(60)
    first = {f: (t, e, i) for c, f, t, e, i in reversed(recorder.seen)}
    assert all(elapsed == tick - start and index == 0 for tick, elapsed, index in first.values())


def test_a_later_check_counts_the_ticks_since_the_last(cfg: Config) -> None:
    recorder = Recorder()
    sim = _sim(cfg, economy={"record": recorder})
    sim.advance(200)
    mine = [(t, e, i) for c, f, t, e, i in recorder.seen if f == 3]
    assert all(later[1] == later[0] - earlier[0] for earlier, later in zip(mine, mine[1:], strict=False))


def test_a_check_index_counts_the_checks_made_before(cfg: Config) -> None:
    recorder = Recorder()
    sim = _sim(cfg, economy={"record": recorder})
    sim.advance(200)
    assert [i for c, f, t, e, i in recorder.seen if f == 3] == list(
        range(len([1 for _c, f, *_ in recorder.seen if f == 3]))
    )


def test_a_check_leaves_the_faction_scheduled_again(cfg: Config) -> None:
    sim = _sim(cfg, economy={"record": Recorder()})
    sim.advance(100)
    faction = sim.state.factions[2]
    schedule = faction.schedule["economy"]
    assert schedule.next_tick > sim.state.tick and schedule.last_tick <= sim.state.tick and schedule.count >= 1


def test_checks_due_on_one_tick_run_by_cadence_then_by_faction_id(cfg: Config) -> None:
    # Force every faction to be due on the first tick on both cadences: the order is economy, then strategy, each by id.
    recorder = Recorder()
    sim = _sim(cfg, economy={"record": recorder}, strategy={"record": recorder})
    for faction in sim.state.factions.values():
        for schedule in faction.schedule.values():
            schedule.next_tick = sim.state.tick + 1
    sim.advance(1)
    expected = [("economy", f) for f in range(FACTIONS)] + [("strategy", f) for f in range(FACTIONS)]
    assert [(c, f) for c, f, *_ in recorder.seen] == expected


def test_steps_of_one_cadence_run_in_sorted_name_order(cfg: Config) -> None:
    order: list[str] = []

    def named(label: str) -> Step:
        def step(sim: Simulation, check: Check) -> bool:
            order.append(label)
            return False

        return step

    sim = _sim(cfg, economy={"b": named("b"), "a": named("a")})
    for faction in sim.state.factions.values():  # only faction 0 is due on the first tick
        faction.schedule["economy"].next_tick = sim.state.tick + 1000
    sim.state.factions[0].schedule["economy"].next_tick = sim.state.tick + 1
    sim.advance(1)
    assert order == ["a", "b"]


def test_a_step_that_changes_nothing_leaves_the_revision(cfg: Config) -> None:
    sim = _sim(cfg, economy={"record": Recorder(changes=False)})
    sim.advance(100)
    assert sim.state.revision == 0


def test_a_step_that_changes_something_bumps_the_revision(cfg: Config) -> None:
    sim = _sim(cfg, economy={"record": Recorder(changes=True)})
    sim.advance(100)
    assert sim.state.revision > 0


def test_the_revision_bumps_once_per_tick_however_many_steps_change(cfg: Config) -> None:
    # Two factions due on one tick, both changing state: one bump for the tick.
    sim = _sim(cfg, economy={"record": Recorder(changes=True)})
    for faction in sim.state.factions.values():
        faction.schedule["economy"].next_tick = sim.state.tick + 1
    sim.advance(1)
    assert sim.state.revision == 1


def test_advance_says_whether_state_changed(cfg: Config) -> None:
    changing, quiet = _sim(cfg, economy={"r": Recorder(changes=True)}), _sim(cfg, economy={"r": Recorder()})
    assert (changing.advance(100), quiet.advance(100)) == (True, False)


def _same(first: SimState, second: SimState) -> bool:
    schedules = lambda s: {i: dict(f.schedule) for i, f in s.factions.items()}  # noqa: E731
    return first.tick == second.tick and first.revision == second.revision and schedules(first) == schedules(second)


def test_one_batch_equals_the_same_ticks_one_at_a_time(cfg: Config) -> None:
    batch = _sim(cfg, economy={"r": Recorder(changes=True)}, strategy={"r": Recorder()})
    single = _sim(cfg, economy={"r": Recorder(changes=True)}, strategy={"r": Recorder()})
    batch.advance(250)
    for _ in range(250):
        single.advance(1)
    assert _same(batch.state, single.state)


def test_a_simulation_continues_a_state_it_is_given(cfg: Config) -> None:
    world = _world()
    state = hydrate(world, cfg, SEED)
    state.tick += 500
    assert Simulation(world, cfg, SEED, state=state).state is state


def test_the_moment_is_the_states_year_and_month(cfg: Config) -> None:
    world = _world()
    world.year = 1200
    sim = Simulation(world, cfg, SEED, steps=_registries())
    sim.advance(1)
    assert sim.moment() == (1201, 1)


def test_the_moment_advances_a_month_every_ticks_per_month(cfg: Config) -> None:
    world = _world()
    world.year = 1200
    sim = Simulation(world, cfg, SEED, steps=_registries())
    sim.advance(sim.state.ticks_per_month * 3)
    assert sim.moment() == (1201, 4)


@pytest.fixture(scope="module")
def generated(cfg: Config) -> World:
    return pipeline.generate(cfg, SEED)


def test_a_run_with_no_steps_changes_nothing_but_the_clock_and_the_schedules(generated: World, cfg: Config) -> None:
    # Zero behaviour: after a year of ticks the owners, places, manifests, relations and events are hydrate's.
    sim = Simulation(generated, cfg, SEED)
    before = hydrate(generated, cfg, SEED)
    sim.advance(sim.state.ticks_per_month * 12)
    after = sim.state
    assert (
        np.array_equal(after.owners, before.owners)
        and after.places == before.places
        and after.manifests == before.manifests
        and after.relations == before.relations
        and after.events == [] == after.pois
        and after.revision == 0
    )


def test_a_run_leaves_the_world_unchanged(cfg: Config) -> None:
    fresh = pipeline.generate(cfg, SEED)
    before = (
        fresh.fingerprint(),
        copy.deepcopy(fresh.pois),
        copy.deepcopy(fresh.realms),
        copy.deepcopy(fresh.chronicle),
    )
    Simulation(fresh, cfg, SEED).advance(2000)
    assert (fresh.fingerprint(), fresh.pois, fresh.realms, fresh.chronicle) == before

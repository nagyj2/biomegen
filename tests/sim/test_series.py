"""Tests for the series: one row of counts for a state, and a run that samples it over the years."""

from __future__ import annotations

from collections import Counter

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sim.hydrate import hydrate
from biomegen.sim.series import COLUMNS, format_rows, run_series, series_row
from biomegen.world.entities import POI
from biomegen.world.sim_state import PlaceState, SimState
from biomegen.world.world import World

SEED = 42


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, SEED)


@pytest.fixture(scope="module")
def row(world: World, cfg: Config) -> dict[str, int | str]:
    return series_row(world, cfg, hydrate(world, cfg, SEED))


def test_a_row_has_every_column_in_order(row: dict[str, int | str]) -> None:
    assert tuple(row) == COLUMNS


def test_a_row_starts_at_the_first_month_after_the_present(row: dict[str, int | str], world: World) -> None:
    assert row["date"] == f"{world.year + 1}/01"


def test_a_row_counts_every_realm_as_a_faction(row: dict[str, int | str], world: World) -> None:
    assert row["factions"] == len(world.realms)


def test_a_power_is_a_faction_with_no_liege(row: dict[str, int | str], world: World) -> None:
    assert row["powers"] == sum(1 for realm in world.realms if realm.liege < 0)


def test_settlements_are_the_civilized_places(row: dict[str, int | str], world: World) -> None:
    assert row["settlements"] == sum(1 for poi in world.pois if poi.civilized)


def test_population_is_what_the_factions_count(row: dict[str, int | str], world: World) -> None:
    assert row["population"] == sum(realm.pop for realm in world.realms)


def test_each_kind_of_relation_is_counted(row: dict[str, int | str], world: World) -> None:
    kinds = Counter(relation.kind for relation in world.relations)
    assert [row["wars"], row["rivalries"], row["alliances"], row["trades"]] == [
        kinds["war"],
        kinds["rivalry"],
        kinds["alliance"],
        kinds["trade"],
    ]


def test_no_stock_is_held_before_the_economy_exists(row: dict[str, int | str]) -> None:
    assert row["stock"] == 0


def test_a_settlement_the_simulation_minted_is_counted(cfg: Config) -> None:
    # A place past the standing and vanished POIs is read from the state's own list.
    small = World(4, 4, 1)
    small.pois = [POI(kind="town", x=0, y=0, interior_seed=1, civilized=True)]
    small.vanished = [POI(kind="watchtower", x=1, y=1, interior_seed=2)]
    state = SimState(ticks_per_month=30)
    state.pois = [POI(kind="hamlet", x=2, y=2, interior_seed=3, civilized=True)]
    state.places = {0: PlaceState(), 2: PlaceState()}
    assert series_row(small, cfg, state)["settlements"] == 2


def test_stock_is_summed_over_every_place(cfg: Config) -> None:
    small = World(4, 4, 1)
    small.pois = [POI(kind="town", x=0, y=0, interior_seed=1, civilized=True)]
    state = SimState(ticks_per_month=30, places={0: PlaceState(stock={"food": 3, "wood": 4})})
    assert series_row(small, cfg, state)["stock"] == 7


def test_a_run_samples_every_so_many_years_and_at_the_start(world: World, cfg: Config) -> None:
    rows, _sim = run_series(world, cfg, SEED, years=100, every=25)
    assert [r["date"] for r in rows] == [f"{world.year + 1 + n}/01" for n in (0, 25, 50, 75, 100)]


def test_a_run_that_does_not_end_on_a_sample_adds_a_last_row(world: World, cfg: Config) -> None:
    rows, _sim = run_series(world, cfg, SEED, years=30, every=25)
    assert [r["date"] for r in rows][-2:] == [f"{world.year + 26}/01", f"{world.year + 31}/01"]


def test_a_run_of_no_years_is_one_row(world: World, cfg: Config) -> None:
    rows, _sim = run_series(world, cfg, SEED, years=0, every=25)
    assert len(rows) == 1


def test_a_run_ends_the_given_years_after_the_start(world: World, cfg: Config) -> None:
    start = hydrate(world, cfg, SEED).tick
    _rows, sim = run_series(world, cfg, SEED, years=10, every=5)
    assert sim.state.tick == start + 10 * 12 * int(cfg.get("sim.ticks_per_month"))


def test_with_no_behaviour_every_row_but_the_date_is_the_same(world: World, cfg: Config) -> None:
    rows, _sim = run_series(world, cfg, SEED, years=50, every=25)
    rest = [{key: value for key, value in r.items() if key not in ("date", "tick")} for r in rows]
    assert rest[0] == rest[1] == rest[2]


def test_a_run_is_deterministic(world: World, cfg: Config) -> None:
    assert run_series(world, cfg, SEED, years=20, every=10)[0] == run_series(world, cfg, SEED, years=20, every=10)[0]


def test_the_table_has_a_header_and_a_line_per_row(world: World, cfg: Config) -> None:
    rows, _sim = run_series(world, cfg, SEED, years=50, every=25)
    lines = format_rows(rows).splitlines()
    assert (lines[0].split(), len(lines)) == (list(COLUMNS), 4)


def test_the_table_columns_line_up(world: World, cfg: Config) -> None:
    rows, _sim = run_series(world, cfg, SEED, years=50, every=25)
    assert len({len(line) for line in format_rows(rows).splitlines()}) == 1

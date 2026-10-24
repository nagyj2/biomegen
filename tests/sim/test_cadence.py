"""Tests for the staggered check schedules: reproducible, spread over the period and independent per faction."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sim import cadence

FACTIONS = range(24)
SEEDS = (1, 42, 7, 1337)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def test_cadences_run_shortest_period_first(cfg: Config) -> None:
    assert cadence.cadence_names(cfg) == ["economy", "strategy"]


def test_a_period_is_its_months_times_the_ticks_per_month(cfg: Config) -> None:
    # Defaults: economy every month (30 ticks), strategy every quarter (90).
    assert (cadence.period_ticks(cfg, "economy"), cadence.period_ticks(cfg, "strategy")) == (30, 90)


@pytest.mark.parametrize("name", ["economy", "strategy"])
def test_a_phase_lies_within_the_first_period(cfg: Config, name: str) -> None:
    # From the first tick run (1) to one whole period after the start: the first check is never at the start tick.
    period = cadence.period_ticks(cfg, name)
    phases = [cadence.phase_ticks(seed, cfg, faction, name) for seed in SEEDS for faction in FACTIONS]
    assert min(phases) >= 1 and max(phases) <= period


def test_a_schedule_is_reproducible_from_the_seed(cfg: Config) -> None:
    first = [cadence.first_check(42, cfg, faction, "strategy", 1000) for faction in FACTIONS]
    again = [cadence.first_check(42, cfg, faction, "strategy", 1000) for faction in FACTIONS]
    assert first == again


def test_a_different_seed_gives_a_different_schedule(cfg: Config) -> None:
    one = [cadence.phase_ticks(1, cfg, faction, "economy") for faction in FACTIONS]
    two = [cadence.phase_ticks(2, cfg, faction, "economy") for faction in FACTIONS]
    assert one != two


def test_a_factions_phase_does_not_depend_on_how_many_factions_exist(cfg: Config) -> None:
    # The draw is keyed on the faction alone, so adding factions never moves an earlier one.
    few = [cadence.phase_ticks(42, cfg, faction, "economy") for faction in range(5)]
    many = [cadence.phase_ticks(42, cfg, faction, "economy") for faction in range(40)]
    assert many[:5] == few


def test_the_first_check_is_the_start_plus_the_phase(cfg: Config) -> None:
    assert cadence.first_check(7, cfg, 3, "economy", 5000) == 5000 + cadence.phase_ticks(7, cfg, 3, "economy")


def test_a_factions_two_cadences_do_not_share_a_phase(cfg: Config) -> None:
    # Drawn on separate streams: for most factions the strategy phase is not the economy phase (mod the shorter period).
    economy = cadence.period_ticks(cfg, "economy")
    same = [
        faction
        for faction in FACTIONS
        if cadence.phase_ticks(42, cfg, faction, "strategy") % economy
        == cadence.phase_ticks(42, cfg, faction, "economy") % economy
    ]
    assert len(same) < len(FACTIONS) // 2


@pytest.mark.parametrize("name", ["economy", "strategy"])
def test_the_gap_to_the_next_check_is_the_period_within_the_jitter(cfg: Config, name: str) -> None:
    period, spread = cadence.period_ticks(cfg, name), int(cfg.get(f"sim.cadence.{name}.jitter_ticks"))
    gaps = [cadence.next_check(42, cfg, 5, name, 0, index) for index in range(200)]
    assert all(period - spread <= gap <= period + spread for gap in gaps)


def test_the_jitter_actually_varies(cfg: Config) -> None:
    # A jitter that never moved the check would leave every gap equal to the period.
    gaps = {cadence.next_check(42, cfg, 5, "strategy", 0, index) for index in range(60)}
    assert len(gaps) > 1


def test_a_next_check_is_always_after_the_last(cfg: Config) -> None:
    after = [
        cadence.next_check(seed, cfg, faction, name, 100, index) > 100
        for seed in SEEDS
        for faction in FACTIONS
        for name in ("economy", "strategy")
        for index in range(10)
    ]
    assert all(after)


def test_a_jitter_is_keyed_on_the_check_not_on_the_tick(cfg: Config) -> None:
    # The same check number gives the same jitter wherever the faction's schedule has got to.
    early = cadence.next_check(42, cfg, 5, "economy", 100, 4) - 100
    late = cadence.next_check(42, cfg, 5, "economy", 99999, 4) - 99999
    assert early == late


@pytest.mark.parametrize("name", ["economy", "strategy"])
def test_the_first_checks_are_spread_over_the_period(cfg: Config, name: str) -> None:
    # No tick of the period holds more than sim.max_check_share of the factions' first checks.
    limit = float(cfg.get("sim.max_check_share"))
    shares = [
        cadence.max_share([cadence.first_check(seed, cfg, faction, name, 0) for faction in FACTIONS]) for seed in SEEDS
    ]
    assert max(shares) <= limit


def test_the_second_checks_stay_spread(cfg: Config) -> None:
    # The jitter keeps the factions apart a period later too.
    limit = float(cfg.get("sim.max_check_share"))
    ticks = [
        cadence.next_check(42, cfg, faction, "economy", cadence.first_check(42, cfg, faction, "economy", 0), 0)
        for faction in FACTIONS
    ]
    assert cadence.max_share(ticks) <= limit


def test_a_global_beat_has_a_share_of_one() -> None:
    assert cadence.max_share([90] * 12) == 1.0


def test_two_checks_of_twelve_on_one_tick_is_a_sixth() -> None:
    assert cadence.max_share([5, 5, *range(10, 20)]) == pytest.approx(2 / 12)


def test_no_checks_have_no_share() -> None:
    assert cadence.max_share([]) == 0.0

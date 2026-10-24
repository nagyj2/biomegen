"""When a faction checks: its staggered schedules, as pure functions of the seed.

A faction's larger computations (build projects, deals, relationship changes, the planner) run on **cadences** (the
rows of ``sim.cadence``): a check every so many months, never on a global beat. Each faction has its own phase for each
cadence, drawn once, and each next check is the period plus a seeded jitter, so no two factions check on the same tick,
a faction's cadences need not coincide, and the chronicle has no block of events on one tick. Units follow neither: they
move at their own speed (``docs/simulation_plan.md`` 2.2).

Every draw is ``rng.derive(seed, "sim", "cadence", faction, cadence, ...)``: it depends only on that faction and that
cadence, so a faction's schedule does not change with how many other factions exist, and the same seed gives the same
schedule on any machine. Nothing here reads or writes state; the caller keeps the check count and passes it in.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ..config.model import Config
from ..util import rng


def cadence_names(config: Config) -> list[str]:
    """Return the cadences of ``sim.cadence``, shortest period first (then by name), the order a tick runs them in."""
    rows = config.get("sim.cadence")
    return sorted(rows, key=lambda name: (int(rows[name]["months"]), name))


def period_ticks(config: Config, cadence: str) -> int:
    """Return the ticks between two checks of ``cadence`` (before jitter)."""
    return int(config.get(f"sim.cadence.{cadence}.months")) * int(config.get("sim.ticks_per_month"))


def phase_ticks(seed: int, config: Config, faction_id: int, cadence: str) -> int:
    """Return how many ticks after the start a faction's first check of ``cadence`` falls, from 1 to one period.

    Drawn once per faction and cadence, so factions start on different ticks. It is at least 1: the first tick the
    simulation runs is one after the start.
    """
    stream = rng.derive(seed, "sim", "cadence", faction_id, cadence, "phase")
    return 1 + stream.randrange(period_ticks(config, cadence))


def first_check(seed: int, config: Config, faction_id: int, cadence: str, start_tick: int) -> int:
    """Return the tick of a faction's first check of ``cadence`` when the simulation starts at ``start_tick``."""
    return start_tick + phase_ticks(seed, config, faction_id, cadence)


def jitter_ticks(seed: int, config: Config, faction_id: int, cadence: str, index: int) -> int:
    """Return the jitter of check number ``index`` (counted from 0): a whole number of ticks from minus to plus the
    cadence's ``jitter_ticks``."""
    spread = int(config.get(f"sim.cadence.{cadence}.jitter_ticks"))
    return rng.derive(seed, "sim", "cadence", faction_id, cadence, index).randint(-spread, spread)


def next_check(seed: int, config: Config, faction_id: int, cadence: str, after_tick: int, index: int) -> int:
    """Return the tick of the check after the one made at ``after_tick``.

    ``index`` is how many checks of this cadence the faction has made, this one included, so the jitter is keyed on the
    check and never on a tick or on the order factions are visited in. The gap is the period plus the jitter, which
    config validation keeps above 0, so a faction never checks twice on one tick.
    """
    return after_tick + period_ticks(config, cadence) + jitter_ticks(seed, config, faction_id, cadence, index)


def max_share(ticks: Sequence[int]) -> float:
    """Return the share of ``ticks`` (the ticks of some factions' checks) that fall on the busiest single tick.

    1 means every check is on one tick (a global beat); the schedule's tests hold the share of a period under
    ``sim.max_check_share``. An empty sequence has share 0.
    """
    return max(Counter(ticks).values()) / len(ticks) if ticks else 0.0

"""Defaults for the ``sim`` section: the tick simulation (see ``biomegen/sim`` and ``docs/simulation_plan.md``).

Time is whole ticks: ``ticks_per_month`` of them make a month. Each faction runs its computations on cadences (a period
in months), each staggered per faction by a seeded phase and jitter, so no two factions check on the same tick.
Units are tied to no cadence: they move at their own speed and are placed by the tick.
"""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Integer ticks in one month: the simulation's time base (``SimState.tick // ticks_per_month`` is the month). A
    # first guess, tuned by eye once units move.
    "ticks_per_month": 30,
    # A faction's cadences: ``months`` is the period between its checks and ``jitter_ticks`` the most (either way) a
    # seeded draw moves each next check, so the gap varies. A cadence needs a step registry in ``sim/steps.py``.
    "cadence": {
        "economy": {"months": 1, "jitter_ticks": 3},  # build projects, trade deals, production
        "strategy": {"months": 3, "jitter_ticks": 10},  # diplomacy, war decisions, relationship changes, the planner
    },
    # The most checks of one cadence the factions may put on one tick of a period, as a share of the factions (what the
    # schedule's tests hold it to; the engine does not enforce it).
    "max_check_share": 0.25,
    # The explorer's clock (``explorer/ticks.py``): ticks per second at normal speed, and the longest span of real time
    # one poll may count (a pause or a slow frame never makes a burst of catch-up ticks).
    "playback": {"ticks_per_second": 10.0, "max_frame_seconds": 0.25},
    # ``scripts/simulate.sh`` runs this many years and prints a row every ``every_years`` of them.
    "series": {"years": 100, "every_years": 25},
}

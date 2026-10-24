"""The steps a faction runs when one of its cadences comes due, and the registries that hold them.

Each cadence of ``sim.cadence`` (``economy``, ``strategy``) has a registry. A step is a function of the simulation and
one :class:`Check`; it returns whether it changed anything a reader may have cached (the engine then bumps the state's
revision). Steps of one registry run in sorted name order, so the order never depends on import order. Nothing is
registered in 10a: the economy (10b) and the diplomacy and war steps (10d) add theirs.

A step must not assume a month passed since the faction's last check: the jitter and the phase make the gap vary, so it
scales what it does by :attr:`Check.elapsed` ticks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..registry import Registry
from ..world.sim_state import Faction

if TYPE_CHECKING:
    from .engine import Simulation


@dataclass(frozen=True)
class Check:
    """One faction's check of one cadence, as a step sees it.

    Attributes:
        faction: The faction checking (a step may change it, as it may change any simulation state).
        cadence: The cadence that came due (a ``sim.cadence`` row name).
        tick: The tick of the check.
        elapsed: Ticks since the faction's last check of this cadence (since the start, for its first).
        index: How many checks of this cadence the faction made before this one.
    """

    faction: Faction
    cadence: str
    tick: int
    elapsed: int
    index: int


Step = Callable[["Simulation", Check], bool]

ECONOMY_STEPS: Registry[Step] = Registry("sim_economy_step")
STRATEGY_STEPS: Registry[Step] = Registry("sim_strategy_step")

# The registry of each cadence, keyed by its ``sim.cadence`` row name.
STEPS: dict[str, Registry[Step]] = {"economy": ECONOMY_STEPS, "strategy": STRATEGY_STEPS}

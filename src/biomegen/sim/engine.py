"""The tick loop: advance a :class:`~biomegen.world.sim_state.SimState` by whole ticks.

:class:`Simulation` owns the state of one world. Each tick adds 1 to the state's tick, then runs every check that has
come due: for each cadence (shortest period first) and each faction due on it (in sorted id order) the cadence's steps
(:mod:`.steps`) run with the ticks elapsed since the faction's last check, and the faction is scheduled again
(:func:`~biomegen.sim.cadence.next_check`). A faction checks on its own beat, so there is no global month step and no
tick on which every faction acts. Units are not stepped here: they are a pure function of the tick (10c).

With no step registered (all of 10a) a tick changes nothing but the tick and the schedules, and the state's revision
stays put. The world is read and never written.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from ..config.model import Config
from ..registry import Registry
from ..world.sim_state import SimState
from ..world.world import World
from . import cadence
from .hydrate import hydrate
from .steps import STEPS, Check, Step


class Simulation:
    """The simulation of one world: its state and the loop that advances it.

    Args:
        world: The generated world (read only).
        config: The merged configuration.
        seed: The seed cadence jitter and later draws are keyed on (the world's master seed).
        state: The state to continue (default: :func:`~biomegen.sim.hydrate.hydrate` of ``world``).
        steps: The step registry of each cadence (default: :data:`~biomegen.sim.steps.STEPS`); tests pass their own.

    Raises:
        ValueError: ``sim.cadence`` has a cadence that ``steps`` has no registry for.
    """

    def __init__(
        self,
        world: World,
        config: Config,
        seed: int,
        state: Optional[SimState] = None,
        steps: Optional[Mapping[str, Registry[Step]]] = None,
    ) -> None:
        self.world = world
        self.config = config
        self.seed = seed
        self.state = state if state is not None else hydrate(world, config, seed)
        self._steps: Mapping[str, Registry[Step]] = steps if steps is not None else STEPS
        self._cadences = cadence.cadence_names(config)
        missing = [name for name in self._cadences if name not in self._steps]
        if missing:
            raise ValueError(f"no step registry for the cadence {missing[0]!r}")

    def moment(self) -> tuple[int, int]:
        """Return the current ``(year, month)``, the month counted from 1."""
        return self.state.moment(int(self.config.get("history.months_per_year")))

    def advance(self, count: int) -> bool:
        """Run ``count`` ticks; return whether any step changed state (always False while no step is registered)."""
        changed = False
        for _ in range(count):
            changed |= self._tick()
        return changed

    def _tick(self) -> bool:
        state = self.state
        state.tick += 1
        changed = False
        factions = sorted(state.factions)
        for name in self._cadences:
            due = [
                faction_id
                for faction_id in factions
                if state.factions[faction_id].schedule[name].next_tick <= state.tick
            ]
            if not due:
                continue
            registry = self._steps[name]
            steps = [registry.get(step) for step in registry.names()]
            for faction_id in due:
                faction = state.factions[faction_id]
                schedule = faction.schedule[name]
                check = Check(faction, name, state.tick, state.tick - schedule.last_tick, schedule.count)
                for step in steps:
                    changed |= step(self, check)
                schedule.count += 1
                schedule.last_tick = state.tick
                schedule.next_tick = cadence.next_check(
                    self.seed, self.config, faction_id, name, state.tick, schedule.count
                )
        if changed:
            state.revision += 1
        return changed

"""The explorer's time seam: a tick source the loop polls, with speed and pause.

By default nothing ticks (:class:`NoTicks`), so the loop blocks on keys exactly as before. With ``--sim`` the source is
a :class:`SimTicks`, which runs a simulation: while a source is ``active`` the loop polls it between keys (never
blocking on the keyboard), runs the ticks that are due at the clock's speed and redraws. Pure apart from the injectable
clock and sleep, so tests drive it with fake ones.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ..config.model import Config
from ..sim.engine import Simulation
from ..world.sim_state import SimState
from ..world.world import World
from .input import KeyReader


class TickSource(Protocol):
    """Something that advances while the explorer is open (a simulation).

    ``state`` is the simulation's state, which the explorer reads the world through (``None`` for a source with none).
    """

    active: bool

    @property
    def state(self) -> Optional[SimState]: ...

    def due(self, now: float, speed: float) -> int:
        """Return how many ticks are due at time ``now`` (seconds) when running at ``speed`` times its normal rate."""
        ...

    def tick(self, count: int) -> bool:
        """Run ``count`` ticks; return whether anything changed (the loop redraws after any ticks either way)."""
        ...

    def reset(self, world: World) -> None:
        """Forget the simulation's state and begin again on ``world`` (the explorer restarted from the seed)."""
        ...


class NoTicks:
    """The default source: it never ticks, so the loop waits on keys alone."""

    active = False
    state: Optional[SimState] = None

    def due(self, now: float, speed: float) -> int:
        return 0

    def tick(self, count: int) -> bool:
        return False

    def reset(self, world: World) -> None:
        return None


class SimTicks:
    """A tick source that runs a :class:`~biomegen.sim.engine.Simulation`.

    The time due is real time times the clock's speed times ``sim.playback.ticks_per_second``. One poll counts at most
    ``sim.playback.max_frame_seconds`` of real time, so a pause (when the loop does not poll) or a slow frame never
    makes a burst of catch-up ticks. Only whole ticks are run; the fraction is kept for the next poll.

    Attributes:
        active: Always True: the loop polls it between keys.
        simulation: The simulation it advances (made again on :meth:`reset`).
    """

    active = True

    def __init__(self, simulation: Simulation) -> None:
        self.simulation = simulation
        self._ticks_per_second = float(simulation.config.get("sim.playback.ticks_per_second"))
        self._longest_poll = float(simulation.config.get("sim.playback.max_frame_seconds"))
        self._last: Optional[float] = None
        self._owed = 0.0

    @classmethod
    def start(cls, world: World, config: Config) -> "SimTicks":
        """Return a source that simulates ``world`` from the present moment."""
        return cls(Simulation(world, config, world.master_seed))

    @property
    def state(self) -> SimState:
        return self.simulation.state

    def due(self, now: float, speed: float) -> int:
        last, self._last = self._last, now
        if last is None:
            return 0
        elapsed = min(max(0.0, now - last), self._longest_poll)
        self._owed += elapsed * speed * self._ticks_per_second
        count = int(self._owed)
        self._owed -= count
        return count

    def tick(self, count: int) -> bool:
        return self.simulation.advance(count)

    def reset(self, world: World) -> None:
        self.simulation = Simulation(world, self.simulation.config, world.master_seed)
        self._last, self._owed = None, 0.0


def sim_status(source: TickSource, clock: "Clock", config: Config) -> str:
    """The panel's sim field: ``sim 1201/03 +12/30 x1`` (year/month, ticks into the month, speed) or ``... paused``;
    empty when no simulation runs."""
    state = getattr(source, "state", None)  # a source with no state of its own (a test's) runs no simulation
    if not source.active or state is None:
        return ""
    year, month = state.moment(int(config.get("history.months_per_year")))
    speed = "paused" if clock.paused else f"x{clock.speed:g}"
    return f"sim {year}/{month:02d} +{state.tick % state.ticks_per_month:02d}/{state.ticks_per_month} {speed}"


@dataclass
class Clock:
    """Speed and pause of the explorer's time.

    Attributes:
        speeds: The speed multipliers the faster / slower keys step through, slowest first (``controls.tick_speeds``).
        index: The current one.
        paused: Whether ticks are held back.
    """

    speeds: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
    index: int = 2
    paused: bool = False

    @classmethod
    def from_config(cls, config: Config) -> "Clock":
        speeds = tuple(float(v) for v in config.get("controls.tick_speeds"))
        return cls(speeds, min(range(len(speeds)), key=lambda i: abs(speeds[i] - 1.0)))

    @property
    def speed(self) -> float:
        return self.speeds[self.index]

    def reset(self) -> None:
        """Back to normal speed, running."""
        self.index = min(range(len(self.speeds)), key=lambda i: abs(self.speeds[i] - 1.0))
        self.paused = False

    def toggle_pause(self) -> str:
        self.paused = not self.paused
        return "paused" if self.paused else f"running at {self.speed:g}x"

    def step(self, direction: int) -> str:
        """Move to the next faster (+1) or slower (-1) speed and say which."""
        self.index = max(0, min(len(self.speeds) - 1, self.index + direction))
        return f"speed {self.speed:g}x" + (" (paused)" if self.paused else "")


def next_token(
    reader: KeyReader,
    source: TickSource,
    clock: Clock,
    poll_seconds: float,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Return the next key token, running due ticks while none is waiting.

    With an inactive source this is just ``reader.read_key()`` (it blocks). With an active one the keyboard is polled:
    when ticks come due they are run and ``"tick"`` is returned so the caller redraws.
    """
    if not source.active:
        return reader.read_key()
    while not reader.pending():
        due = 0 if clock.paused else source.due(now(), clock.speed)
        if due:
            source.tick(due)
            return "tick"
        sleep(poll_seconds)
    return reader.read_key()

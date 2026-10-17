"""The explorer's time seam: a tick source the loop polls, with speed and pause.

Nothing ticks today (:class:`NoTicks`), so the loop blocks on keys exactly as before. A later simulation implements
:class:`TickSource`; while it is ``active`` the loop polls it between keys (never blocking on the keyboard), runs the
ticks that are due at the clock's speed and redraws. Pure apart from the injectable clock and sleep, so tests drive it
with fake ones.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from ..config.model import Config
from ..world.world import World
from .input import KeyReader


class TickSource(Protocol):
    """Something that advances while the explorer is open (a simulation)."""

    active: bool

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

    def due(self, now: float, speed: float) -> int:
        return 0

    def tick(self, count: int) -> bool:
        return False

    def reset(self, world: World) -> None:
        return None


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

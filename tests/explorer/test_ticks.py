"""Tests for the explorer's time seam: the tick source, the clock and the loop that polls them."""

from __future__ import annotations

from types import TracebackType
from typing import Optional

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.app import run
from biomegen.explorer.ticks import Clock, NoTicks, next_token
from tests.explorer.replay import RecordingOut
from tests.explorer.test_app import ScriptedKeys, _village_world


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


class FakeSource:
    """An active source that is due one tick every second of the fake clock (scaled by the speed)."""

    active = True

    def __init__(self) -> None:
        self.ran = 0
        self._next = 1.0

    def due(self, now: float, speed: float) -> int:
        count = 0
        while now * speed >= self._next:
            self._next += 1.0
            count += 1
        return count

    def tick(self, count: int) -> bool:
        self.ran += count
        return True


class Waiting(ScriptedKeys):
    """A keyboard with nothing waiting for ``idle`` polls, then the scripted keys (then q)."""

    def __init__(self, idle: int, *tokens: str) -> None:
        super().__init__(*tokens)
        self.idle = idle

    def __enter__(self) -> "Waiting":
        return self

    def __exit__(
        self, kind: Optional[type[BaseException]], value: Optional[BaseException], trace: Optional[TracebackType]
    ) -> None:
        return None

    def pending(self) -> bool:
        if self.idle > 0:
            self.idle -= 1
            return False
        return True


class FakeTime:
    """A clock that moves a quarter second each time the loop sleeps."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps = 0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.t += 0.25


def test_with_no_ticks_the_loop_just_reads_a_key() -> None:
    clock = FakeTime()
    token = next_token(ScriptedKeys("x"), NoTicks(), Clock(), 0.02, clock.now, clock.sleep)
    assert token == "x" and clock.sleeps == 0


def test_an_active_source_ticks_while_no_key_is_waiting() -> None:
    source, clock = FakeSource(), FakeTime()
    token = next_token(Waiting(5, "x"), source, Clock(), 0.02, clock.now, clock.sleep)
    assert token == "tick" and source.ran == 1


def test_a_waiting_key_wins_over_the_ticks() -> None:
    source, clock = FakeSource(), FakeTime()
    assert next_token(Waiting(0, "x"), source, Clock(), 0.02, clock.now, clock.sleep) == "x" and source.ran == 0


def test_a_paused_clock_runs_no_ticks() -> None:
    source, clock = FakeSource(), FakeTime()
    paused = Clock(paused=True)
    token = next_token(Waiting(4, "x"), source, paused, 0.02, clock.now, clock.sleep)
    assert token == "x" and source.ran == 0 and clock.sleeps == 4


def test_a_faster_clock_brings_ticks_sooner() -> None:
    slow_source, fast_source = FakeSource(), FakeSource()
    slow_time, fast_time = FakeTime(), FakeTime()
    next_token(Waiting(10, "x"), slow_source, Clock(), 0.02, slow_time.now, slow_time.sleep)
    next_token(Waiting(10, "x"), fast_source, Clock(index=5), 0.02, fast_time.now, fast_time.sleep)
    assert fast_time.t < slow_time.t


def test_the_clock_steps_through_its_speeds_and_stops_at_the_ends() -> None:
    clock = Clock()
    messages = [clock.step(1) for _ in range(5)]
    assert messages[-1] == "speed 8x" and clock.step(1) == "speed 8x"
    assert [clock.step(-1) for _ in range(6)][-1] == "speed 0.25x" and clock.step(-1) == "speed 0.25x"


def test_pausing_toggles_and_says_so() -> None:
    clock = Clock()
    assert (clock.toggle_pause(), clock.toggle_pause()) == ("paused", "running at 1x")


def test_the_clock_starts_at_normal_speed(cfg: Config) -> None:
    assert Clock.from_config(cfg).speed == 1.0


def _run(cfg: Config, keys, ticks=None, clock: Optional[FakeTime] = None) -> RecordingOut:
    out = RecordingOut(40, 100)
    fake = clock or FakeTime()
    run(
        _village_world(),
        cfg,
        "none",
        reader=keys,
        out=out,
        get_size=lambda: (100, 40),
        ticks=ticks,
        now=fake.now,
        sleep=fake.sleep,
    )
    return out


def test_the_pause_key_says_nothing_is_running_without_a_simulation(cfg: Config) -> None:
    out = _run(cfg, ScriptedKeys("p"))
    assert any("no simulation is running" in "\n".join(frame) for frame in out.frames)


def test_an_active_source_ticks_inside_the_explorer_loop(cfg: Config) -> None:
    source = FakeSource()
    _run(cfg, Waiting(6, "q"), source)
    assert source.ran >= 1


def test_the_pause_key_holds_an_active_source(cfg: Config) -> None:
    source = FakeSource()
    out = _run(cfg, Waiting(0, "p", "q"), source)
    assert source.ran == 0 and any("paused" in "\n".join(frame) for frame in out.frames)

"""Tests for key tokenizing, action resolution and the POSIX reader (run against a real pseudo-terminal)."""

from __future__ import annotations

import os
import signal
import sys

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.input import PosixKeyReader, resolve_action, tokenize


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("a", ["a"]),
        ("ab", ["a", "b"]),
        ("\x1b[A", ["up"]),
        ("\x1b[B", ["down"]),
        ("\x1b[C", ["right"]),
        ("\x1b[D", ["left"]),
        ("\x1bOA", ["up"]),
        ("\x1b[1;2C", ["shift-right"]),
        ("\x1b[1;5D", ["shift-left"]),
        ("\x1b", ["esc"]),
        ("\x1b[3~", ["unknown"]),
        ("\x1b[5~", ["pageup"]),
        ("\x1b[6~", ["pagedown"]),
        ("\x1b[H", ["home"]),
        ("\x1b[F", ["end"]),
        ("\x1b[1~", ["home"]),
        ("\x1b[4~", ["end"]),
        ("q\x1b[Aq", ["q", "up", "q"]),
        (" ", [" "]),
    ],
)
def test_tokenize_splits_keys_and_names_escape_sequences(text: str, tokens: list[str]) -> None:
    assert tokenize(text) == tokens


@pytest.mark.parametrize(
    ("token", "action"),
    [
        ("up", ("move", 0, -1)),
        ("left", ("move", -1, 0)),
        ("shift-down", ("move", 0, 8)),
        ("shift-right", ("move", 8, 0)),
        ("w", ("pan", 0, -1)),
        ("a", ("pan", -1, 0)),
        ("h", ("move", -1, 0)),
        ("W", ("pan", 0, -8)),
        ("L", ("move", 8, 0)),
        (" ", ("zoom",)),
        ("z", ("local",)),
        ("f", ("toggle_scale",)),
        ("v", ("cycle_view",)),
        ("?", ("help",)),
        ("<", ("floor", 1)),
        (">", ("floor", -1)),
        ("e", ("export", "view")),
        ("E", ("export", "world")),
        ("q", ("quit",)),
        ("esc", ("quit",)),
        ("eof", ("quit",)),
        ("resize", ("resize",)),
        ("x", ("none",)),
        ("r", ("none",)),
        ("unknown", ("none",)),
    ],
)
def test_default_keys_resolve_to_actions(config: Config, token: str, action: tuple) -> None:
    # `r` is deliberately unbound in 4c: regenerate returns in phase 9.
    assert resolve_action(token, config) == action


def test_fast_step_follows_the_config() -> None:
    config = load_config(None)
    config.data["controls"]["fast_step"] = 3
    assert resolve_action("shift-up", config) == ("move", 0, -3)


def test_a_rebound_key_wins() -> None:
    config = load_config(None)
    config.data["keys"]["zoom"] = "x"
    assert (resolve_action("x", config), resolve_action(" ", config)) == (("zoom",), ("none",))


def test_a_bound_letter_beats_the_movement_letters() -> None:
    # Binding quit to "h" must not also move left.
    config = load_config(None)
    config.data["keys"]["quit"] = "h"
    assert resolve_action("h", config) == ("quit",)


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pseudo-terminal")


@pytest.fixture
def terminal():
    """A pseudo-terminal pair: write to ``master``, the reader reads ``slave``."""
    master, slave = os.openpty()
    yield master, slave
    for handle in (master, slave):
        try:
            os.close(handle)
        except OSError:
            pass


@posix_only
def test_reader_returns_typed_characters(terminal) -> None:
    master, slave = terminal
    with PosixKeyReader(slave) as reader:
        os.write(master, b"qz")
        assert [reader.read_key(), reader.read_key()] == ["q", "z"]


@posix_only
def test_reader_says_whether_a_key_is_waiting(terminal) -> None:
    # Nothing typed: nothing waiting. Two keys typed: one waits after the first is read, none after the second.
    master, slave = terminal
    with PosixKeyReader(slave) as reader:
        idle = reader.pending()
        os.write(master, b"ab")
        reader.read_key()
        after_first = reader.pending()
        reader.read_key()
        assert (idle, after_first, reader.pending()) == (False, True, False)


@posix_only
def test_reader_names_arrow_sequences(terminal) -> None:
    master, slave = terminal
    with PosixKeyReader(slave) as reader:
        os.write(master, b"\x1b[A\x1b[1;2C")
        assert [reader.read_key(), reader.read_key()] == ["up", "shift-right"]


@posix_only
def test_reader_reports_a_resize(terminal) -> None:
    _, slave = terminal
    with PosixKeyReader(slave) as reader:
        os.kill(os.getpid(), signal.SIGWINCH)
        assert reader.read_key() == "resize"


@posix_only
def test_reader_restores_the_terminal_mode(terminal) -> None:
    import termios

    _, slave = terminal
    before = termios.tcgetattr(slave)
    with PosixKeyReader(slave):
        pass
    assert termios.tcgetattr(slave) == before


@posix_only
def test_reader_reports_end_of_input(terminal) -> None:
    master, slave = terminal
    with PosixKeyReader(slave) as reader:
        os.close(master)
        assert reader.read_key() == "eof"

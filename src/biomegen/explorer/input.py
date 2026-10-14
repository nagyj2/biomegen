"""Keys: reading raw terminal input and turning it into explorer actions.

Reading is split from meaning. A reader (termios on POSIX, msvcrt on Windows) yields *tokens*: a single
character (``"a"``, ``" "``) or a name (``"up"``, ``"shift-left"``, ``"esc"``, ``"resize"``). :func:`resolve_action`
maps a token to an action tuple using the rebindable ``keys`` table, so the loop reads as a clean switch.

Actions: ``("move", dx, dy)``, ``("zoom",)``, ``("local",)``, ``("toggle_scale",)``, ``("cycle_view",)``,
``("floor", +1 | -1)``, ``("export", "view" | "world")``, ``("help",)``, ``("quit",)``, ``("resize",)``,
``("none",)``.
"""

from __future__ import annotations

import os
import re
import sys
from collections import deque
from types import TracebackType
from typing import Optional, Protocol

from ..config.model import Config

Action = tuple

_ESCAPE = "\x1b"
_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left"}
# An escape sequence: CSI (ESC [ params letter) or SS3 (ESC O letter); params like "1;2" mark a modifier.
_SEQUENCE = re.compile(r"\x1b(?:\[([0-9;]*)([A-Za-z~])|O([A-Za-z]))")

_STEPS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}
_LETTER_STEPS = {"w": "up", "s": "down", "a": "left", "d": "right", "k": "up", "j": "down", "h": "left", "l": "right"}
_BOUND_ACTIONS = (
    ("zoom", ("zoom",), " "),
    ("local", ("local",), "z"),
    ("toggle_scale", ("toggle_scale",), "f"),
    ("cycle_view", ("cycle_view",), "v"),
    ("help", ("help",), "?"),
    ("floor_up", ("floor", 1), "<"),
    ("floor_down", ("floor", -1), ">"),
    ("export_view", ("export", "view"), "e"),
    ("export_world", ("export", "world"), "E"),
)


def tokenize(text: str) -> list[str]:
    """Split raw terminal text into key tokens: escape sequences become names, a lone ESC is ``"esc"``.

    A modified arrow (``ESC [ 1 ; 2 A``) becomes ``"shift-up"``; sequences that are not arrows become
    ``"unknown"``. Anything else is one token per character.
    """
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != _ESCAPE:
            tokens.append(char)
            index += 1
            continue
        match = _SEQUENCE.match(text, index)
        if match is None:
            tokens.append("esc")
            index += 1
            continue
        params, final, ss3 = match.group(1), match.group(2), match.group(3)
        letter = ss3 or final
        name = _ARROWS.get(letter)
        if name is None:
            tokens.append("unknown")
        elif params and params.split(";")[-1] in ("2", "5"):  # xterm: 2 = shift, 5 = control
            tokens.append(f"shift-{name}")
        else:
            tokens.append(name)
        index = match.end()
    return tokens


def resolve_action(token: str, config: Config) -> Action:
    """Translate a key token into an action (fast moves go ``controls.fast_step`` tiles)."""
    keys = config.get("keys")
    step = int(config.get("controls.fast_step", 8))
    if token == "resize":
        return ("resize",)
    if token in _STEPS:
        dx, dy = _STEPS[token]
        return ("move", dx, dy)
    if token.startswith("shift-") and token[6:] in _STEPS:
        dx, dy = _STEPS[token[6:]]
        return ("move", dx * step, dy * step)
    if token in ("esc", "eof") or token == keys.get("quit", "q"):
        return ("quit",)
    lower = token.lower()
    if len(token) == 1 and lower in _LETTER_STEPS and token not in _bound_keys(keys):
        dx, dy = _STEPS[_LETTER_STEPS[lower]]
        scale = step if token.isupper() else 1
        return ("move", dx * scale, dy * scale)
    for name, action, default in _BOUND_ACTIONS:
        if token == keys.get(name, default):
            return action
    return ("none",)


def _bound_keys(keys: dict) -> set[str]:
    """The keys the user bound to actions, which win over the WASD / HJKL movement letters."""
    return {keys.get(name, default) for name, _action, default in _BOUND_ACTIONS} | {keys.get("quit", "q")}


class KeyReader(Protocol):
    """A source of key tokens that holds the terminal in raw mode between ``__enter__`` and ``__exit__``."""

    def __enter__(self) -> "KeyReader": ...

    def __exit__(
        self, kind: Optional[type[BaseException]], value: Optional[BaseException], trace: Optional[TracebackType]
    ) -> None: ...

    def read_key(self) -> str:
        """Block until a key arrives and return its token (``"eof"`` when input closes)."""
        ...


class PosixKeyReader:
    """Reads keys from a terminal file descriptor in cbreak mode, with ``"resize"`` on SIGWINCH."""

    def __init__(self, fd: Optional[int] = None) -> None:
        self._fd = sys.stdin.fileno() if fd is None else fd
        self._pending: deque[str] = deque()
        self._saved: Optional[list] = None
        self._wake_read = -1
        self._wake_write = -1
        self._old_handler: object = None

    def __enter__(self) -> "PosixKeyReader":
        import signal
        import termios
        import tty

        self._saved = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        self._wake_read, self._wake_write = os.pipe()
        os.set_blocking(self._wake_write, False)
        self._old_handler = signal.signal(signal.SIGWINCH, lambda *_: self._wake())
        return self

    def __exit__(
        self, kind: Optional[type[BaseException]], value: Optional[BaseException], trace: Optional[TracebackType]
    ) -> None:
        import signal
        import termios

        if self._old_handler is not None:
            signal.signal(signal.SIGWINCH, self._old_handler)  # type: ignore[arg-type]
        if self._saved is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except termios.error, OSError:
                pass  # the terminal is already gone (hung up), so there is nothing to restore
        for handle in (self._wake_read, self._wake_write):
            if handle >= 0:
                os.close(handle)

    def _wake(self) -> None:
        try:
            os.write(self._wake_write, b"x")
        except OSError:
            pass  # pipe full: a resize is already pending

    def read_key(self) -> str:
        import select

        while not self._pending:
            ready, _, _ = select.select([self._fd, self._wake_read], [], [])
            if self._wake_read in ready:
                os.read(self._wake_read, 64)
                return "resize"
            try:
                data = os.read(self._fd, 64)
            except OSError:  # a closed pty raises EIO rather than returning b""
                return "eof"
            if not data:
                return "eof"
            self._pending.extend(tokenize(data.decode("utf-8", errors="ignore")))
        return self._pending.popleft()


_WINDOWS_ARROWS = {"H": "up", "P": "down", "K": "left", "M": "right"}


class WindowsKeyReader:
    """Reads keys with ``msvcrt`` on Windows (arrows arrive as a prefix byte plus a code)."""

    def __enter__(self) -> "WindowsKeyReader":
        return self

    def __exit__(
        self, kind: Optional[type[BaseException]], value: Optional[BaseException], trace: Optional[TracebackType]
    ) -> None:
        return None

    def read_key(self) -> str:
        import msvcrt  # type: ignore[import-not-found,unused-ignore]

        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):
            return _WINDOWS_ARROWS.get(msvcrt.getwch(), "unknown")
        if char == _ESCAPE:
            return "esc"
        if char in ("\x03", "\x1a"):  # Ctrl-C, Ctrl-Z
            return "eof"
        return char


def make_reader() -> KeyReader:
    """Return the key reader for this platform."""
    return WindowsKeyReader() if os.name == "nt" else PosixKeyReader()

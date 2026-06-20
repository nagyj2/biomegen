"""Key bindings -> actions.

Maps a raw curses key code to a small action tuple the app loop dispatches on. Movement keys cover
the arrow keys plus WASD and vi-style HJKL; the rest come from the configurable ``keys`` table so a
user can rebind them. Keeping this isolated means the app loop reads as a clean switch.
"""

from __future__ import annotations

import curses
from typing import Optional, Tuple

from ..config.model import Config

# Action tuples returned to the app loop:
#   ("move", dx, dy) | ("zoom",) | ("local",) | ("toggle_scale",) | ("floor", +/-1)
#   ("export", "view"|"world") | ("refresh",) | ("quit",) | ("resize",) | ("none",)
Action = Tuple

_SLOW_MOVE = {
    "w": (0, -1),
    "s": (0, 1),
    "a": (-1, 0),
    "d": (1, 0),
    "k": (0, -1),
    "j": (0, 1),
    "h": (-1, 0),
    "l": (1, 0),
}

_FAST_MOVE = {
    "W": (0, -1),
    "S": (0, 1),
    "A": (-1, 0),
    "D": (1, 0),
    "K": (0, -1),
    "J": (0, 1),
    "H": (-1, 0),
    "L": (1, 0),
}

_BOUND_ACTIONS = (
    ("zoom", "zoom", " "),
    ("local", "local", "z"),
    ("toggle_scale", "toggle_scale", "f"),
    ("refresh", "refresh", "r"),
    ("floor_up", "floor", "<"),
    ("floor_down", "floor", ">"),
    ("export_view", "export", "e"),
    ("export_world", "export", "E"),
)


def _shift_arrow_sets() -> tuple[set[int], set[int], set[int], set[int]]:
    """Return (left, right, up, down) sets of shifted-arrow key codes available on this curses build.

    Shifted left/right are standard (``KEY_SLEFT``/``KEY_SRIGHT``); shifted up/down vary by backend
    (ncurses uses ``KEY_SR``/``KEY_SF``, PDCurses/windows-curses adds ``KEY_SUP``/``KEY_SDOWN``), so
    we accept any of the known aliases.
    """

    def codes(*names):
        return {getattr(curses, n) for n in names if hasattr(curses, n)}

    return (
        codes("KEY_SLEFT"),
        codes("KEY_SRIGHT"),
        codes("KEY_SR", "KEY_SUP", "KEY_SPREVIOUS"),
        codes("KEY_SF", "KEY_SDOWN", "KEY_SNEXT"),
    )


def _arrow_action(key: int, step: int) -> Optional[Action]:
    plain = {
        curses.KEY_LEFT: ("move", -1, 0),
        curses.KEY_RIGHT: ("move", 1, 0),
        curses.KEY_UP: ("move", 0, -1),
        curses.KEY_DOWN: ("move", 0, 1),
    }
    if key in plain:
        return plain[key]
    if key == curses.KEY_RESIZE:
        return ("resize",)

    s_left, s_right, s_up, s_down = _shift_arrow_sets()
    if key in s_left:
        return ("move", -step, 0)
    if key in s_right:
        return ("move", step, 0)
    if key in s_up:
        return ("move", 0, -step)
    if key in s_down:
        return ("move", 0, step)
    return None


def _char_action(ch: str, keys: dict, step: int, key: int) -> Optional[Action]:
    if ch in _SLOW_MOVE:
        dx, dy = _SLOW_MOVE[ch]
        return ("move", dx, dy)
    if ch in _FAST_MOVE:
        dx, dy = _FAST_MOVE[ch]
        return ("move", dx * step, dy * step)

    if ch == keys.get("quit", "q") or key == 27:  # 27 = ESC
        return ("quit",)

    for key_name, action_name, default in _BOUND_ACTIONS:
        if ch != keys.get(key_name, default):
            continue
        if action_name == "floor":
            return ("floor", 1 if key_name == "floor_up" else -1)
        if action_name == "export":
            return ("export", "view" if key_name == "export_view" else "world")
        return (action_name,)
    return None


def resolve_action(key: int, config: Config) -> Action:
    """Translate a curses key code into an action tuple (fast variants move ``controls.fast_step``)."""
    keys = config.get("keys")
    step = int(config.get("controls.fast_step", 8))

    action = _arrow_action(key, step)
    if action is not None:
        return action

    ch = chr(key) if 0 <= key < 0x110000 else ""
    action = _char_action(ch, keys, step, key)
    if action is not None:
        return action
    return ("none",)

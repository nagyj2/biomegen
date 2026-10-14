"""Tests for the per-cell enums in world.tile."""

from __future__ import annotations

import numpy as np

from biomegen.world.tile import RELIEF_BY_NAME, Relief


def test_relief_none_is_zero() -> None:
    # A zero-filled uint8 relief array means "no relief" everywhere.
    assert Relief(0) is Relief.NONE


def test_relief_values_fit_uint8() -> None:
    # Relief is stored as a uint8 array, so every value must round-trip through it.
    values = np.array([int(r) for r in Relief], dtype=np.uint8)
    assert [Relief(int(v)) for v in values] == list(Relief)


def test_relief_names_resolve_to_members() -> None:
    # The table key for each member is its lower-case name.
    assert {name: RELIEF_BY_NAME[name] for name in ("none", "hills", "mountain", "peak", "volcano")} == {
        r.name.lower(): r for r in Relief
    }

"""The simulation fingerprint: a digest of a :class:`~biomegen.world.sim_state.SimState` for the determinism proofs.

The same seed, config and tick count give the same digest on any machine, whether the run was headless or watched, so
a refactor that must not change the simulation is proved by an unchanged digest (``scripts/simulate.sh --proof``). The
state is encoded field by field by reflection, so a field a later phase adds (stocks, units, opinions) is covered the
day it is added and nothing can be forgotten. Integers are exact, a float is its ``float.hex`` (exact too), text is
length prefixed, a mapping is encoded in the order of its encoded keys and a numpy array by dtype, shape and bytes.
Builtin ``hash()`` is never used. ``revision`` is left out: it counts cache invalidations, not simulated state.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from ..util.rng import hash_bytes
from ..world.sim_state import SimState

_EXCLUDED = frozenset({"revision"})  # bookkeeping for readers' caches, not state


def _sized(tag: bytes, payload: bytes) -> bytes:
    return tag + len(payload).to_bytes(8, "big") + payload


def _encode(value: Any) -> bytes:
    """Return the canonical bytes of ``value`` (see the module docstring); a type with no encoding is an error."""
    if value is None:
        return b"N"
    if isinstance(value, bool):
        return b"B1" if value else b"B0"
    if isinstance(value, int):
        return _sized(b"I", str(int(value)).encode())
    if isinstance(value, float):
        return _sized(b"F", value.hex().encode())
    if isinstance(value, str):
        return _sized(b"S", value.encode("utf-8"))
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        array = array.astype(array.dtype.newbyteorder("<"), copy=False)
        header = f"{array.dtype.str}{array.shape}".encode()
        return _sized(b"A", _sized(b"H", header) + array.tobytes())
    if isinstance(value, (list, tuple)):
        return _sized(b"L", b"".join(_encode(item) for item in value))
    if isinstance(value, dict):
        items = sorted((_encode(key), _encode(item)) for key, item in value.items())
        return _sized(b"D", b"".join(key + item for key, item in items))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        parts = [_sized(b"S", type(value).__name__.encode())]
        for field in dataclasses.fields(value):
            if not (isinstance(value, SimState) and field.name in _EXCLUDED):
                parts.append(_sized(b"S", field.name.encode()) + _encode(getattr(value, field.name)))
        return _sized(b"C", b"".join(parts))
    raise TypeError(f"the simulation fingerprint has no encoding for {type(value).__name__}")


def sim_fingerprint(state: SimState) -> str:
    """Return a stable hex digest of ``state``: its tick and time base, owner grid, factions, places, manifests,
    relations and everything the simulation made (events, rulers, predecessors, realms, POIs)."""
    return hash_bytes(_encode(state))

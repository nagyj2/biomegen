"""Values derived from a generated world, computed once and kept beside it.

A world is immutable once generated, so anything worked out from its arrays (the road network's geometry, a lookup a
renderer or a later simulation reads on every frame) can be computed once. :func:`derived` keeps such values per world
without storing them on it, keyed by name, and checks a blake2b digest of the arrays a value was built from, so a world
whose arrays were edited in place (a test's hand-made world) gets a fresh value instead of a stale one. The digest is
cheap next to the work it saves; it is never builtin ``hash()``.
"""

from __future__ import annotations

import hashlib
import weakref
from typing import Any, Callable, Hashable, TypeVar

import numpy as np

from .world import World

T = TypeVar("T")

_CACHE: "weakref.WeakKeyDictionary[World, dict[Hashable, tuple[bytes, Any]]]" = weakref.WeakKeyDictionary()


def _digest(sources: tuple[np.ndarray, ...]) -> bytes:
    """Return a blake2b digest of the arrays' shapes, dtypes and contents."""
    digest = hashlib.blake2b(digest_size=16)
    for array in sources:
        contiguous = np.ascontiguousarray(array)
        digest.update(f"{contiguous.dtype.str}{contiguous.shape}".encode())
        digest.update(contiguous.data)
    return digest.digest()


def derived(world: World, key: Hashable, build: Callable[[], T], *sources: np.ndarray) -> T:
    """Return the value ``build()`` makes for ``world`` under ``key``, building it once while ``sources`` are unchanged.

    ``key`` names the value and every setting it depends on (two settings, two keys); ``sources`` are the world arrays
    it is computed from. The value is shared: callers must not change it.
    """
    digest = _digest(sources)
    entries = _CACHE.setdefault(world, {})
    entry = entries.get(key)
    if entry is None or entry[0] != digest:
        entry = (digest, build())
        entries[key] = entry
    return entry[1]

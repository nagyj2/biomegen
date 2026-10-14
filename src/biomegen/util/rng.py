"""The determinism anchor for the whole generator.

Reproducibility is a hard requirement: the same seed must always produce the same world. The classic
failure mode is threading a *single* shared RNG through every stage - then any change to stage order
or to how many random numbers a stage draws shifts every downstream result ("one change ripples
everywhere"). The industry-standard fix, used here, is **named sub-streams**: from one master integer
seed we derive an *independent* RNG per stage (and per tile) by hashing the master seed together with
a stable label. Identical (seed, labels) always yield identical streams; unrelated stages never
interfere.

Two rules make this airtight:

1. We hash with :func:`hashlib.blake2b`, **never** the built-in :func:`hash`. ``hash()`` is salted
   per process (``PYTHONHASHSEED``) for str/bytes, so using it anywhere in the seed path would make
   worlds irreproducible across runs.
2. Stage label strings are drawn from :data:`LABELS` (a documented registry) so two stages cannot
   silently pick the same label and collide their streams.

Public helpers:
    normalize_seed  - turn any user-supplied seed (int / hex / arbitrary string) into a stable uint64.
    derive_int      - deterministic 64-bit int from (master_seed, *labels).
    derive          - a seeded :class:`random.Random` from (master_seed, *labels).
    derive_numpy    - a seeded :class:`numpy.random.Generator` from (master_seed, *labels).
    tile_rng        - a per-tile :class:`random.Random` keyed on coordinates (for lazy zoom interiors).
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable

import numpy as np

# Mask to fold arbitrary integers into an unsigned 64-bit range.
_UINT64_MASK = 0xFFFFFFFFFFFFFFFF

# ---------------------------------------------------------------------------
# Canonical stage-label registry.
#
# Every call into this module passes one or more of these labels. Keeping them in one place means a
# reviewer can see, at a glance, that no two stages share a label (which would couple their RNG
# streams). New stages MUST add their label here rather than inventing an ad-hoc string at the call
# site. Per-tile interiors append integer coordinates to the relevant label.
# ---------------------------------------------------------------------------
LABELS: frozenset[str] = frozenset(
    {
        "heightmap",  # base elevation fBm permutation
        "heightmap.warp",  # domain-warp fBm permutation
        "heightmap.coast",  # coastline-detail mask noise
        "heightmap.island",  # archipelago land-distribution noise
        "moisture",  # climate moisture fBm permutation
        "hydrology",  # hydrology general
        "hydrology.rivers",  # river source selection / meander
        "regions",  # region colour jitter / tie-breaks
        "biomeblend.x",  # detail-view biome-boundary blend warp (x component)
        "biomeblend.y",  # detail-view biome-boundary blend warp (y component)
        "poi",  # POI placement sampling
        "poi_interior",  # per-POI interior seed minting (keyed on coordinates too)
        "interior.footprint",  # poi_interiors metadata stage: per-POI footprint size jitter
        "interior",  # interior floor layout (BSP rooms/corridors), keyed on interior_seed + floor
        "interior.shaft",  # aligned stair-shaft positions (floor-independent, so floors stack)
        "interior.shape",  # solid-building outer-boundary shape mask (per-structure, floor-independent)
        "interior.door",  # exterior entrance door position (entry floor only)
        "interior.furnish",  # role-based furnishing pass, keyed on interior_seed + floor
        "interior.erode",  # ruin erosion: which walls collapse / floor cracks into rubble
        "roads",  # road graph edge selection
        "roads.meander",  # per-edge road meander noise
        "naming",  # name/lore generation
        "naming.culture",  # per-region culture assignment (mixed-culture naming)
        "regen",  # perturbed master seed for a regeneration attempt after the land-fraction gate
        # Stages of the redesigned pipeline (docs/redesign_plan.md 4.1), registered ahead of their
        # phase so no earlier stage can claim the name. Each stage adds its own suffixes when it lands.
        "terrain",  # map latitude, elevation, mountain belts, sea level
        "climate",  # temperature and rainfall
        "biomes",  # biome and relief classification
        "geography",  # landmasses, ranges, seas, lakes and their names
        "settlements",  # habitability sampling and settlement tiers
        "realms",  # realm growth from capitals
        "diplomacy",  # vassalage, relations, fronts, claims
        "history",  # the derived chronicle (per-event streams are suffixed)
        "pois",  # config-driven POI kinds placed from chronicle events
    }
)


def normalize_seed(seed: object) -> int:
    """Fold any user-supplied seed into a stable unsigned 64-bit integer.

    Accepts a real integer (taken modulo 2**64), or any other value which is stringified and hashed.
    This lets the CLI accept ``--seed 42``, ``--seed 0xCAFE`` or ``--seed "my island"`` and still be
    perfectly reproducible, because the conversion uses blake2b (not the salted built-in ``hash``).
    """
    if isinstance(seed, bool):  # bool is an int subclass; treat explicitly to avoid surprises.
        seed = int(seed)
    if isinstance(seed, int):
        return seed & _UINT64_MASK
    if isinstance(seed, str):
        text = seed.strip()
        # Allow hex / decimal numeric strings to be interpreted as their integer value.
        try:
            return int(text, 0) & _UINT64_MASK
        except ValueError:
            pass
    digest = hashlib.blake2b(str(seed).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _label_bytes(label: object) -> bytes:
    """Encode a single label component to bytes for hashing (ints fixed-width, others as UTF-8)."""
    if isinstance(label, bool):
        label = int(label)
    if isinstance(label, int):
        # 9 bytes, signed, covers negative floor indices and any tile coordinate we will ever use.
        return label.to_bytes(9, "big", signed=True)
    return str(label).encode("utf-8")


def derive_int(master_seed: object, *labels: object) -> int:
    """Return a deterministic 64-bit integer from a master seed plus zero or more labels.

    The labels are length-prefixed-by-separator so that ``("ab", "c")`` and ``("a", "bc")`` cannot
    collide. This is the single primitive every other helper in this module is built on.
    """
    h = hashlib.blake2b(digest_size=8)
    h.update(normalize_seed(master_seed).to_bytes(8, "big"))
    for label in labels:
        h.update(b"\x1f")  # ASCII unit separator between components, so concatenations stay distinct.
        h.update(_label_bytes(label))
    return int.from_bytes(h.digest(), "big")


def derive(master_seed: object, *labels: object) -> random.Random:
    """Return a fresh :class:`random.Random` seeded from (master_seed, *labels)."""
    return random.Random(derive_int(master_seed, *labels))


def derive_numpy(master_seed: object, *labels: object) -> np.random.Generator:
    """Return a fresh numpy :class:`~numpy.random.Generator` seeded from (master_seed, *labels).

    Used by the vectorised generation stages (e.g. building a noise permutation table). numpy's
    PCG64 bit-generator is deterministic for a given integer seed, so the world is reproducible as
    long as the same code path runs.
    """
    return np.random.default_rng(derive_int(master_seed, *labels))


def tile_rng(master_seed: object, x: int, y: int, label: str) -> random.Random:
    """Return a per-tile :class:`random.Random` keyed on integer coordinates.

    This is what lets POI interiors be generated lazily yet deterministically: the same tile always
    mints the same stream, so an interior can be regenerated identically every time it is opened
    without being stored in the World.
    """
    return random.Random(derive_int(master_seed, label, int(x), int(y)))


def hash_bytes(*chunks: bytes) -> str:
    """Return a short hex digest of the given byte chunks - used by the golden-world test.

    Centralised here so the determinism guarantee (blake2b, never ``hash()``) is enforced in one
    place for both seed derivation and world fingerprinting.
    """
    h = hashlib.blake2b(digest_size=16)
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()


def assert_known_labels(used: Iterable[str]) -> None:
    """Raise if any label in ``used`` is not in :data:`LABELS` (a guard for tests/CI)."""
    unknown = sorted(set(used) - LABELS)
    if unknown:
        raise AssertionError(f"undeclared RNG labels in use: {unknown}")

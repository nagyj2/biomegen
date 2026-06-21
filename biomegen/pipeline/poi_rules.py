"""Per-kind POI rule parsing, suitability scoring, and floor mapping.

A ``KindRule`` is the typed form of one ``poi.types.<kind>`` config block. From it we build a hard
*eligibility* mask (which tiles a kind may occupy at all) and a soft *score* array (how much it would
like each eligible tile), then the sampler picks placements. Floors map per kind: dungeons descend
(negative ``lowest_floor``), everything else (incl. towers, which rise) anchors at floor 0.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional, Tuple, Union

import numpy as np

from ..util import rng
from ..world.tile import WaterType, biome_from_name
from ..world.world import World


@dataclass(frozen=True)
class KindRule:
    """Typed placement rule for one POI kind."""

    kind: str  # POI kind, e.g. "city"
    count: int  # how many of this kind to place
    min_spacing: int  # minimum tile distance between anchors of this kind
    civilized: bool  # whether this kind counts as civilization (feeds remoteness)
    biome_ints: frozenset  # allowed biome ints (hard whitelist)
    elevation_min: Optional[float]
    elevation_max: Optional[float]
    near_freshwater: float  # weight on closeness-to-freshwater
    coastal: float  # weight on closeness-to-coast
    remoteness: float  # weight on distance-from-settlements
    on_water: bool  # boats: anchor must be a water tile
    avoid_water: bool  # structures: the whole footprint (not just the anchor) must be water-free
    floors: Union[int, Tuple[int, int]]


def parse_rule(kind: str, raw: dict) -> KindRule:
    """Coerce a raw ``poi.types.<kind>`` dict into a :class:`KindRule` (absent weights default to 0)."""
    floors = raw.get("floors", 1)
    if isinstance(floors, (list, tuple)):
        floors = (int(floors[0]), int(floors[1]))
    else:
        floors = int(floors)
    return KindRule(
        kind=kind,
        count=int(raw.get("count", 0)),
        min_spacing=int(raw.get("min_spacing", 1)),
        civilized=bool(raw.get("civilized", False)),
        biome_ints=frozenset(int(biome_from_name(n)) for n in raw.get("biomes", [])),
        elevation_min=(float(raw["elevation_min"]) if "elevation_min" in raw else None),
        elevation_max=(float(raw["elevation_max"]) if "elevation_max" in raw else None),
        near_freshwater=float(raw.get("near_freshwater", 0.0)),
        coastal=float(raw.get("coastal", 0.0)),
        remoteness=float(raw.get("remoteness", 0.0)),
        on_water=bool(raw.get("on_water", False)),
        avoid_water=bool(raw.get("avoid_water", False)),
        floors=floors,
    )


def eligibility_mask(rule: KindRule, world: World, footprint: Optional[Tuple[int, int]] = None) -> np.ndarray:
    """Boolean grid of tiles this kind may occupy: biome whitelist + elevation + water/land + free.

    When ``rule.avoid_water`` is set and a ``footprint`` (max width/height in tiles) is given, the
    anchor must also sit where the *entire* centred footprint is water-free - not just the anchor tile.
    This stops a structure whose anchor is on land from laying walls/floors over coastal/lake/river
    water (footprints are sized in a later stage and centred on the anchor, so the anchor alone can be
    dry while the footprint clips water).
    """
    biome = world.biome
    allowed = (
        np.isin(biome, np.array(sorted(rule.biome_ints), dtype=biome.dtype))
        if rule.biome_ints
        else np.zeros(biome.shape, dtype=bool)
    )

    if rule.on_water:
        surface_ok = world.water_type != int(WaterType.NONE)  # boats sit on water
    else:
        surface_ok = world.water_type == int(WaterType.NONE)  # land POIs on land

    mask = allowed & surface_ok & (world.poi_index < 0)  # never reuse an occupied tile
    if rule.elevation_min is not None:
        mask &= world.elevation >= rule.elevation_min
    if rule.elevation_max is not None:
        mask &= world.elevation <= rule.elevation_max
    if rule.avoid_water and footprint is not None:
        mask &= water_free_footprint_mask(world, footprint[0], footprint[1])
    return mask


def water_free_footprint_mask(world: World, fw: int, fh: int) -> np.ndarray:
    """Bool grid: True where an ``fw x fh`` footprint *centred* on the tile contains no water.

    Footprints are centred on the anchor (``tx0 = x - fw // 2``; see :mod:`poi_interiors`), so a tile
    is acceptable only when every tile of that centred window is non-water. Off-map tiles (the
    footprint is clipped at the border) count as land. Implemented with a summed-area table so the
    per-tile window sum is a 4-point lookup, keeping the whole thing O(width * height) with no scipy.
    """
    water = (world.water_type != int(WaterType.NONE)).astype(np.int64)
    h, w = water.shape
    # Summed-area table padded with a zero first row/col so any window sum is sat[y1,x1] - sat[y0,x1]
    # - sat[y1,x0] + sat[y0,x0] with half-open [y0,y1) x [x0,x1) bounds (no special-casing the edge).
    sat = np.zeros((h + 1, w + 1), dtype=np.int64)
    sat[1:, 1:] = water.cumsum(0).cumsum(1)
    xs, ys = np.arange(w), np.arange(h)
    x0 = np.clip(xs - fw // 2, 0, w)  # window cols [x0, x1) matching the centred footprint, clamped
    x1 = np.clip(xs - fw // 2 + fw, 0, w)
    y0 = np.clip(ys - fh // 2, 0, h)  # window rows [y0, y1), clamped to the map
    y1 = np.clip(ys - fh // 2 + fh, 0, h)
    count = sat[np.ix_(y1, x1)] - sat[np.ix_(y0, x1)] - sat[np.ix_(y1, x0)] + sat[np.ix_(y0, x0)]
    return count == 0


def score_array(
    rule: KindRule,
    mask: np.ndarray,
    fresh_w: np.ndarray,
    coast_w: np.ndarray,
    remote_w: Union[np.ndarray, float],
    jitter: np.ndarray,
) -> np.ndarray:
    """Score eligible tiles; ineligible tiles get ``-inf`` so they are never chosen.

    Score = 1 (base) + weighted closeness terms + a small jitter to break ties organically.
    """
    score = 1.0 + rule.near_freshwater * fresh_w + rule.coastal * coast_w + rule.remoteness * remote_w + jitter
    return np.where(mask, score, -np.inf).astype(np.float64)


def floors_for(kind: str, rule: KindRule, rgen: random.Random) -> Tuple[int, int]:
    """Return ``(floor_count, lowest_floor)``. Dungeons descend; towers/others anchor at 0."""
    if isinstance(rule.floors, tuple):
        lo, hi = rule.floors
        floor_count = int(rgen.randint(min(lo, hi), max(lo, hi)))
    else:
        floor_count = int(rule.floors)
    floor_count = max(1, floor_count)
    lowest_floor = -(floor_count - 1) if kind == "dungeon" else 0
    return floor_count, lowest_floor


def build_jitter(world: World, seed: int, kind: str, strength: float) -> np.ndarray:
    """Deterministic per-tile jitter in ``[0, strength)`` for tie-breaking (vectorised, no ``hash()``)."""
    gen = rng.derive_numpy(seed, "poi", kind)
    return gen.random((world.height, world.width)) * strength

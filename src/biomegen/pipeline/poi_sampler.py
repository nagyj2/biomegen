"""Placement-strategy registry: turn a per-kind score field into chosen anchor coordinates.

The default ``bluenoise`` strategy is a greedy, capacity-constrained blue-noise pick: take the
highest-scoring eligible tiles, accepting each only if it respects ``min_spacing`` from every
already-placed POI (a shared set across all kinds). The candidate set is tiny (a few dozen accepted
points), so a vectorised distance test against the running list is plenty fast - no KDTree needed.
Strategies are selected by ``poi.sampler``; ``random`` and ``grid`` are registered for parity with the
swappable-algorithm design.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ..registry import Registry
from .poi_rules import KindRule

Coord = Tuple[int, int]
POI_SAMPLERS: Registry = Registry("poi_sampler")


def _ordered_candidates(score: np.ndarray, limit: int = 4000) -> List[Coord]:
    """Return eligible (score > -inf) tiles as (x, y), sorted by score desc with a stable tie-break.

    Capped at ``limit`` best candidates - placement only needs the top handful, and this keeps the
    sort/loop cheap on large eligible regions.
    """
    ys, xs = np.nonzero(np.isfinite(score))
    if xs.size == 0:
        return []
    vals = score[ys, xs]
    # Sort by (-score, y, x): highest score first, then a deterministic coordinate tie-break.
    order = np.lexsort((xs, ys, -vals))
    if order.size > limit:
        order = order[:limit]
    return [(int(xs[i]), int(ys[i])) for i in order]


@POI_SAMPLERS.register("bluenoise")
def bluenoise_place(score: np.ndarray, rule: KindRule, placed: List[Coord]) -> List[Coord]:
    """Greedy blue-noise: best-scoring tiles first, each kept only if >= ``min_spacing`` from all placed."""
    accepted: List[Coord] = []
    spacing2 = float(rule.min_spacing) ** 2
    # numpy array of all currently-placed points (shared across kinds) for vectorised distance checks.
    pts = np.array(placed, dtype=np.float64) if placed else np.empty((0, 2))
    for x, y in _ordered_candidates(score):
        if len(accepted) >= rule.count:
            break
        if pts.shape[0]:
            d2 = (pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2
            if float(d2.min()) < spacing2:
                continue
        accepted.append((x, y))
        pts = np.vstack([pts, [x, y]]) if pts.shape[0] else np.array([[x, y]], dtype=np.float64)
    return accepted


@POI_SAMPLERS.register("random")
def random_place(score: np.ndarray, rule: KindRule, placed: List[Coord]) -> List[Coord]:
    """Spacing-respecting random pick among eligible tiles (score used only as an eligibility gate)."""
    # Reuse the blue-noise spacing logic but over a score where eligible tiles are flattened to a
    # constant so the lexsort tie-break (y, x) gives a deterministic, score-independent order.
    flat = np.where(np.isfinite(score), 0.0, -np.inf)
    return bluenoise_place(flat, rule, placed)


@POI_SAMPLERS.register("grid")
def grid_place(score: np.ndarray, rule: KindRule, placed: List[Coord]) -> List[Coord]:
    """Coarse-grid pick: identical spacing contract; here it behaves like blue-noise (kept for parity)."""
    return bluenoise_place(score, rule, placed)

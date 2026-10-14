"""Drawing a plan into a grid of a different resolution."""

from __future__ import annotations

from typing import Optional

import numpy as np

_CODE = 256  # a cell value is below this, so ``priority * _CODE + cell`` orders by priority and then by value


def _reduce(codes: np.ndarray, axis: int, first: np.ndarray, last: np.ndarray) -> np.ndarray:
    """Return the maximum of ``codes`` over each block ``[first[i], last[i])`` along ``axis``."""
    pad = [(0, 0), (0, 0)]
    pad[axis] = (0, 1)
    padded = np.pad(codes, pad)
    bounds = np.empty(first.size * 2, dtype=np.int64)
    bounds[0::2], bounds[1::2] = first, last
    return np.maximum.reduceat(padded, bounds, axis=axis).take(np.arange(first.size) * 2, axis=axis)


def _edges(count: int, size: int, lo: int, hi: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the source block ``[first, last)`` of each target index in ``[lo, hi)``, mapping ``size`` to ``count``."""
    index = np.arange(lo, hi)
    first = np.minimum(index * size // count, size - 1)
    last = np.maximum((index + 1) * size // count, first + 1)
    return first, np.minimum(last, size)


def sample_rect(
    plan: np.ndarray,
    row0: int,
    col0: int,
    span_rows: int,
    span_cols: int,
    max_rows: int,
    max_cols: int,
    priority: Optional[np.ndarray] = None,
) -> Optional[tuple[slice, slice, np.ndarray]]:
    """Sample ``plan`` into a ``span_rows x span_cols`` rectangle at ``(row0, col0)`` of a grid.

    Returns ``(row_slice, col_slice, values)`` over the part of the rectangle inside ``[0, max_rows) x [0, max_cols)``,
    or ``None`` when it misses the grid. The rectangle may start off the grid or overflow it. This is the one place a
    plan is scaled to a view, so the map outline, the zoom view and the site view agree on the mapping.

    Where the plan is finer than the rectangle, each target cell takes the nearest source cell, or, given a
    ``priority`` lookup (one number per cell value), the source cell of highest priority in its block, so a one-cell
    wall survives being drawn smaller.
    """
    plan_rows, plan_cols = plan.shape
    if span_rows <= 0 or span_cols <= 0:
        return None
    row_lo, row_hi = max(0, row0), min(max_rows, row0 + span_rows)
    col_lo, col_hi = max(0, col0), min(max_cols, col0 + span_cols)
    if row_hi <= row_lo or col_hi <= col_lo:
        return None
    rows = (row_lo - row0, row_hi - row0)
    cols = (col_lo - col0, col_hi - col0)
    if priority is None or (span_rows >= plan_rows and span_cols >= plan_cols):
        source_rows = np.minimum(np.arange(*rows) * plan_rows // span_rows, plan_rows - 1)
        source_cols = np.minimum(np.arange(*cols) * plan_cols // span_cols, plan_cols - 1)
        return slice(row_lo, row_hi), slice(col_lo, col_hi), plan[np.ix_(source_rows, source_cols)]
    codes = priority[plan].astype(np.int64) * _CODE + plan
    for axis, span, size, (lo, hi) in ((0, span_rows, plan_rows, rows), (1, span_cols, plan_cols, cols)):
        if span < size:
            first, last = _edges(span, size, lo, hi)
            codes = _reduce(codes, axis, first, last)
        else:
            index = np.minimum(np.arange(lo, hi) * size // span, size - 1)
            codes = codes.take(index, axis=axis)
    return slice(row_lo, row_hi), slice(col_lo, col_hi), (codes % _CODE).astype(plan.dtype)

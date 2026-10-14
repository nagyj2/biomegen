"""Drawing a plan into a grid of a different resolution."""

from __future__ import annotations

from typing import Optional

import numpy as np


def sample_rect(
    plan: np.ndarray, row0: int, col0: int, span_rows: int, span_cols: int, max_rows: int, max_cols: int
) -> Optional[tuple[slice, slice, np.ndarray]]:
    """Nearest-neighbour sample ``plan`` into a ``span_rows x span_cols`` rectangle at ``(row0, col0)`` of a grid.

    Returns ``(row_slice, col_slice, values)`` over the part of the rectangle inside ``[0, max_rows) x [0, max_cols)``,
    or ``None`` when it misses the grid. The rectangle may start off the grid or overflow it. This is the one place a
    plan is scaled to a view, so the map outline, the zoom silhouette and the site view agree on the mapping.
    """
    plan_rows, plan_cols = plan.shape
    if span_rows <= 0 or span_cols <= 0:
        return None
    row_lo, row_hi = max(0, row0), min(max_rows, row0 + span_rows)
    col_lo, col_hi = max(0, col0), min(max_cols, col0 + span_cols)
    if row_hi <= row_lo or col_hi <= col_lo:
        return None
    source_rows = np.minimum(np.arange(row_lo - row0, row_hi - row0) * plan_rows // span_rows, plan_rows - 1)
    source_cols = np.minimum(np.arange(col_lo - col0, col_hi - col0) * plan_cols // span_cols, plan_cols - 1)
    return slice(row_lo, row_hi), slice(col_lo, col_hi), plan[np.ix_(source_rows, source_cols)]

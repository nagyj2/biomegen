"""Defaults for the ``compute`` section (compute backends)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Backend for connected-components / distance transforms / nearest-neighbour queries.
    #   "scipy" : ndimage.label + distance_transform_edt + cKDTree (default, fastest).
    #   "numpy" / "pure" : in-house implementations (no scipy needed).
    "backend": "scipy",
}

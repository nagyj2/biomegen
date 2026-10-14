"""The scale bar shown in the title line."""

from __future__ import annotations

from ...config.model import Config
from ...util.units import GridScale


def scale_bar(scale: GridScale, cols: int, config: Config, ascii_only: bool) -> str:
    """Return a bar such as `` 0├────┤500 km `` sized to about ``1/scale_fraction`` of the map width."""
    cfg = config.get("render.furniture")
    target_cols = cols / cfg["scale_fraction"]
    length_km = min(cfg["scale_km"], key=lambda km: abs(km / scale.km_per_col - target_cols))
    span = max(3, round(length_km / scale.km_per_col))
    if ascii_only:
        return f" 0|{'-' * (span - 2)}|{length_km} km "
    return f" 0├{'─' * (span - 2)}┤{length_km} km "

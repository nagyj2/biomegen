"""Km-true scale model: how big one map cell is, and where it sits on the globe.

One tile is one terminal cell, but the world has a physical size (``world.size_km``), so a cell is
``km_per_col`` wide and ``km_per_row`` tall and is generally *not* square. Every spatial stage that
measures distance, area or position goes through a :class:`GridScale` instead of counting tiles, so
changing the grid resolution keeps km-based tunables meaning the same thing.

Latitude decreases down the map (north is up); longitude increases to the right and wraps to
``[-180, 180)``. Degrees of longitude shrink with ``cos(latitude)``; the map uses the value at its
centre latitude for every row (an equirectangular projection, as in the reference generator).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Mean length of one degree of latitude on Earth (km). A physical constant, not a tunable.
KM_PER_DEGREE = 111.32

# Highest centre latitude magnitude the projection allows, so the top and bottom edges stay within
# the poles; and the floor on cos(latitude), so degrees of longitude stay finite near a pole.
_MAX_LATITUDE = 89.0
_MIN_COS_LATITUDE = 0.05


@dataclass(frozen=True)
class GridScale:
    """Physical size and placement of a ``width`` x ``height`` cell grid.

    Attributes:
        km_per_col: Width of one cell (one column step) in km.
        km_per_row: Height of one cell (one row step) in km.
        lat_top: Latitude of the map's top edge, in degrees (north positive).
        lon_left: Longitude of the map's left edge, in degrees (east positive).
        deg_lon_per_km: Degrees of longitude per km east-west, fixed at the centre latitude.
    """

    km_per_col: float
    km_per_row: float
    lat_top: float
    lon_left: float
    deg_lon_per_km: float

    @property
    def aspect(self) -> float:
        """Cell height over cell width in km (``> 1`` means a cell is taller than it is wide)."""
        return self.km_per_row / self.km_per_col

    @property
    def cell_area_km2(self) -> float:
        """Area of one cell in km²."""
        return self.km_per_col * self.km_per_row

    @property
    def sampling(self) -> tuple[float, float]:
        """Per-axis cell size as ``(row_km, col_km)``, the ``[y, x]`` order numpy distance transforms take."""
        return (self.km_per_row, self.km_per_col)

    def km_to_cols(self, km: float) -> float:
        """Convert an east-west distance in km to a (fractional) number of columns."""
        return km / self.km_per_col

    def km_to_rows(self, km: float) -> float:
        """Convert a north-south distance in km to a (fractional) number of rows."""
        return km / self.km_per_row

    def area_to_cells(self, km2: float) -> float:
        """Convert an area in km² to a (fractional) number of cells."""
        return km2 / self.cell_area_km2

    def distance_km(self, x0: float, y0: float, x1: float, y1: float) -> float:
        """Straight-line distance in km between two cell positions ``(x, y)``."""
        return math.hypot((x1 - x0) * self.km_per_col, (y1 - y0) * self.km_per_row)

    def lat_of_row(self, y: float) -> float:
        """Latitude in degrees at the centre of row ``y``."""
        return self.lat_top - (y + 0.5) * self.km_per_row / KM_PER_DEGREE

    def lon_of_col(self, x: float) -> float:
        """Longitude in degrees at the centre of column ``x``, wrapped to ``[-180, 180)``."""
        lon = self.lon_left + (x + 0.5) * self.km_per_col * self.deg_lon_per_km
        return (lon + 180.0) % 360.0 - 180.0


def grid_scale(
    width: int, height: int, size_km: tuple[float, float], center_lat: float, center_lon: float
) -> GridScale:
    """Build the :class:`GridScale` for a ``width`` x ``height`` grid covering ``size_km``.

    Args:
        width: Number of columns (must be positive).
        height: Number of rows (must be positive).
        size_km: Physical ``(east-west, north-south)`` extent of the whole map in km (both positive).
        center_lat: Latitude of the map centre in degrees. Clamped so both edges stay within ±89°.
        center_lon: Longitude of the map centre in degrees.

    Returns:
        The scale; ``lat_top`` and ``lon_left`` are the outer edges of the first row and column.

    Raises:
        ValueError: If a dimension or extent is not positive.
    """
    km_wide, km_tall = float(size_km[0]), float(size_km[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"grid dimensions must be positive, got {width}x{height}")
    if km_wide <= 0 or km_tall <= 0:
        raise ValueError(f"size_km must be positive, got {size_km!r}")
    lat_span = km_tall / KM_PER_DEGREE
    limit = max(0.0, _MAX_LATITUDE - lat_span / 2)
    lat = min(max(float(center_lat), -limit), limit)
    deg_lon_per_km = 1.0 / (KM_PER_DEGREE * max(_MIN_COS_LATITUDE, math.cos(math.radians(lat))))
    return GridScale(
        km_per_col=km_wide / width,
        km_per_row=km_tall / height,
        lat_top=lat + lat_span / 2,
        lon_left=float(center_lon) - km_wide / 2 * deg_lon_per_km,
        deg_lon_per_km=deg_lon_per_km,
    )

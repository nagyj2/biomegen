"""Latitude and longitude tick labels for a whole-world map (one cell per tile)."""

from __future__ import annotations

import math

from ...config.model import Config
from ...util.units import KM_PER_DEGREE, GridScale


def _first_step(steps: list, tile_degrees: float, minimum_tiles: float) -> float:
    """Return the first step (degrees) that spans at least ``minimum_tiles`` tiles, else the largest."""
    return next((s for s in steps if s / tile_degrees >= minimum_tiles), steps[-1])


def latitude_labels(scale: GridScale, rows: int, config: Config, degree: str) -> dict[int, str]:
    """Return ``{row: label}`` for the rows a latitude tick falls on (``"40°N"``, ``"0°"``, ``"15°S"``)."""
    cfg = config.get("render.furniture")
    degrees_per_row = scale.km_per_row / KM_PER_DEGREE
    step = _first_step(cfg["lat_steps"], degrees_per_row, cfg["lat_tick_rows"])
    labels: dict[int, str] = {}
    latitude = math.ceil(scale.lat_of_row(rows - 1) / step) * step
    while latitude <= scale.lat_top:
        row = round((scale.lat_top - latitude) / degrees_per_row - 0.5)
        if 0 <= row < rows:
            labels[row] = (
                f"0{degree}" if latitude == 0 else f"{abs(latitude):.0f}{degree}{'N' if latitude > 0 else 'S'}"
            )
        latitude += step
    return labels


def longitude_labels(scale: GridScale, cols: int, config: Config, degree: str) -> dict[int, str]:
    """Return ``{column: label}`` for the columns a longitude tick falls on (``"20°E"``, ``"0°"``, ``"5°W"``)."""
    cfg = config.get("render.furniture")
    degrees_per_col = scale.km_per_col * scale.deg_lon_per_km
    step = _first_step(cfg["lon_steps"], degrees_per_col, cfg["lon_tick_cols"])
    labels: dict[int, str] = {}
    longitude = math.ceil(scale.lon_left / step) * step
    while longitude <= scale.lon_left + cols * degrees_per_col:
        col = round((longitude - scale.lon_left) / degrees_per_col - 0.5)
        if 0 <= col < cols:
            wrapped = (longitude + 180) % 360 - 180
            labels[col] = f"0{degree}" if wrapped == 0 else f"{abs(wrapped):.0f}{degree}{'E' if wrapped > 0 else 'W'}"
        longitude += step
    return labels

"""Defaults for the ``world`` section (world dimensions)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Default sized so the whole map fits a typical terminal at 1:1 with room for the status
    # panel below it (the reference terminal is ~209x58; 44 + status_height(12) <= 58, 192 <= 209).
    "width": 192,
    "height": 75,
    # Sea level on the normalised [0, 1] elevation scale: tiles below this are ocean/water.
    "sea_level": 0.40,
    # "fixed" keeps the dimensions above (reproducible across terminals). "auto" fits the world to
    # the current terminal at launch (nicer fit, but the same seed yields different worlds on
    # differently sized terminals - documented trade-off).
    "size_mode": "fixed",
    # Global per-axis multipliers applied to noise sample coordinates: >1 stretches features along
    # that axis (zooms out), <1 compresses them. Distinct from per-feature ``terrain.scale``.
    "scale_x": 1.0,
    "scale_y": 1.0,
    # The island-mask sanity gate regenerates with a perturbed seed up to this many times if a
    # seed produces less than ``min_land_fraction`` land (prevents empty-world cascades).
    "regen_attempts": 8,
    "min_land_fraction": 0.12,
}

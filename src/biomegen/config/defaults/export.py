"""Defaults for the ``export`` section (export (in-game keypress))."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    "dir": "./images",
    "cell_px": 12,  # pixel size of one tile in exported images
    "png": True,  # also write a PNG (via Pillow) next to the SVG
    "filename_pattern": "{name}_{seed}_{view}",
}

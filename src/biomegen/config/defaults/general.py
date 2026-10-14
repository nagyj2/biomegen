"""Defaults for the ``general`` section (general)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Master seed. 0 / absent means "pick a random seed and echo it" so a random run is still
    # reproducible afterwards. May also be set on the CLI (which takes precedence).
    "seed": 0,
}

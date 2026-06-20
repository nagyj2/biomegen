"""Load a TOML config, deep-merge it onto the in-code defaults, validate, and wrap it.

Flow: ``defaults (deep copy) <- user TOML overlay -> validate/coerce -> Config``. A user file only
needs the keys it wants to change; everything else falls back to :data:`~biomegen.config.defaults.DEFAULTS`.
With no file at all the app runs on pure defaults.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, Optional

from .defaults import get_defaults
from .model import Config
from .validate import validate


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (mutating ``base``) and return it.

    Nested tables are merged key-by-key; any non-dict value in ``override`` replaces the value in
    ``base`` wholesale (so e.g. a user-supplied ``biomes.matrix`` replaces the default matrix rather
    than trying to merge lists element-wise).
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: Optional[str | Path] = None) -> Config:
    """Return a validated :class:`Config`.

    Parameters
    ----------
    path:
        Optional path to a TOML file. If ``None`` or the file does not exist, pure defaults are used.
    """
    merged = get_defaults()

    if path is not None:
        p = Path(path)
        if p.exists():
            with p.open("rb") as fh:  # tomllib requires binary mode.
                user = tomllib.load(fh)
            _deep_merge(merged, user)
        # A missing explicit path is tolerated (run on defaults); callers that care can pre-check.

    validate(merged)
    return Config(merged)

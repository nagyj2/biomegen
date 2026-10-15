"""The :class:`Config` object passed (read-only) into every subsystem.

It wraps the fully-merged-and-validated configuration dict and exposes ergonomic, dotted-path access
so stages read ``config.get("terrain.octaves")`` instead of indexing nested dicts (or re-parsing
TOML). It is frozen: a stage cannot accidentally mutate shared tuning mid-run, which protects
reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Hashable, TypeVar

import numpy as np

_MISSING = object()
T = TypeVar("T")


@dataclass(frozen=True)
class Config:
    """Immutable wrapper around a merged configuration tree.

    Use :meth:`get` with a dotted path for scalar lookups and :meth:`section` to scope into a subtree.
    The raw merged dict is available as :attr:`data` for the rare case a whole subtree is needed.
    """

    data: Dict[str, Any] = field(default_factory=dict)
    _memo: Dict[Hashable, Any] = field(default_factory=dict, compare=False, repr=False)

    def cached(self, key: Hashable, build: Callable[[], T]) -> T:
        """Return the value ``build()`` made for ``key`` on this config, building it the first time it is asked for.

        For lookups derived only from the configuration (style tables, glyph tables) that would otherwise be rebuilt
        on every frame. The config is treated as final once it is in use: a value is never rebuilt, so mutating
        ``data`` after a lookup was cached leaves the old lookup in place.
        """
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    def get(self, path: str, default: Any = _MISSING) -> Any:
        """Resolve a dotted path (``"a.b.c"``) through the nested tree.

        Raises :class:`KeyError` if the path is absent and no ``default`` was supplied - a missing key
        almost always means a typo or a defaults/loader drift, and failing loudly beats silently
        substituting ``None`` deep inside a generation stage.
        """
        node: Any = self.data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                if default is _MISSING:
                    raise KeyError(f"config key {path!r} not found")
                return default
        return node

    def table_array(self, table: str, key: str, names: Dict[int, str]) -> np.ndarray:
        """Return ``tables.<table>.<name>.<key>`` as a float array indexed by enum value.

        ``names`` maps each enum value to its row name (``BIOME_NAME``, ``RELIEF_NAME``), so a stage can index the
        array with a whole ``biome`` or ``relief`` grid instead of looping over cells.
        """
        out = np.zeros(max(names) + 1, dtype=np.float64)
        for value, name in names.items():
            out[value] = float(self.get(f"tables.{table}.{name}.{key}"))
        return out

    def section(self, name: str) -> "Config":
        """Return a :class:`Config` scoped to the subtree at ``name`` (empty if absent)."""
        node = self.data.get(name, {})
        if not isinstance(node, dict):
            raise KeyError(f"config section {name!r} is not a table")
        return Config(node)

    def __contains__(self, path: str) -> bool:
        return self.get(path, None) is not None

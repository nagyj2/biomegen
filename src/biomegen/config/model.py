"""The :class:`Config` object passed (read-only) into every subsystem.

It wraps the fully-merged-and-validated configuration dict and exposes ergonomic, dotted-path access
so stages read ``config.get("terrain.octaves")`` instead of indexing nested dicts (or re-parsing
TOML). It is frozen: a stage cannot accidentally mutate shared tuning mid-run, which protects
reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

_MISSING = object()


@dataclass(frozen=True)
class Config:
    """Immutable wrapper around a merged configuration tree.

    Use :meth:`get` with a dotted path for scalar lookups and :meth:`section` to scope into a subtree.
    The raw merged dict is available as :attr:`data` for the rare case a whole subtree is needed.
    """

    data: Dict[str, Any] = field(default_factory=dict)

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

    def section(self, name: str) -> "Config":
        """Return a :class:`Config` scoped to the subtree at ``name`` (empty if absent)."""
        node = self.data.get(name, {})
        if not isinstance(node, dict):
            raise KeyError(f"config section {name!r} is not a table")
        return Config(node)

    def __contains__(self, path: str) -> bool:
        return self.get(path, None) is not None

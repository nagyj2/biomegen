"""The mutable runtime layer composited over the immutable generated world.

Generation produces a read-only :class:`~biomegen.world.world.World`. Future gameplay, however, will
need to *change* things - a structure tile gets destroyed, an object is placed, a chest is opened. To
keep generation pure and reproducible while still allowing such changes, all runtime edits are stored
here, in a separate sparse structure, and applied **on top of** the base when something is read or
drawn. The base biome is never touched; only overlay deltas change.

Two scopes are tracked:

* **surface** - edits to the biome-map layer, keyed by ``(x, y)``. Each entry is a small dict of
  changed render attributes (e.g. ``{"glyph": "x", "blocked": True}``). The underlying base biome
  array is intentionally *not* representable here.
* **interior** - edits to a POI interior, keyed by ``(interior_seed, floor)`` then ``(x, y)`` to a
  :class:`~biomegen.world.tile.Cell` value. This is what makes "regenerate the interior from its seed,
  then re-apply stored edits" work: the base interior is deterministic, the deltas are remembered.

The whole overlay is JSON-serialisable (:meth:`to_dict` / :meth:`from_dict`) so a future save/load
feature can persist exactly the player's changes without re-storing the generated world.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

# Type aliases for readability.
Coord = Tuple[int, int]
InteriorKey = Tuple[int, int]  # (interior_seed, floor)


class Overlay:
    """Sparse store of runtime modifications, applied over the immutable base at read time.

    Attributes:
        revision: Counts the edits made so far, so a reader that keeps what it drew (the render cache) can tell
            when the overlay has changed under it.
    """

    def __init__(self) -> None:
        self.revision = 0
        # Surface edits: (x, y) -> {attribute: value}.
        self._surface: Dict[Coord, Dict[str, Any]] = {}
        # Interior edits: (interior_seed, floor) -> {(x, y): cell_int}.
        self._interior: Dict[InteriorKey, Dict[Coord, int]] = {}

    # ------------------------------------------------------------------ surface layer
    def set_surface(self, x: int, y: int, **attrs: Any) -> None:
        """Merge ``attrs`` into the surface delta at ``(x, y)`` (creating it if needed)."""
        self._surface.setdefault((int(x), int(y)), {}).update(attrs)
        self.revision += 1

    def get_surface(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        """Return the surface delta dict at ``(x, y)`` (or None if the tile is unmodified)."""
        return self._surface.get((int(x), int(y)))

    def clear_surface(self, x: int, y: int) -> None:
        """Remove any surface delta at ``(x, y)`` (revert to the generated base)."""
        if self._surface.pop((int(x), int(y)), None) is not None:
            self.revision += 1

    def surface_edits(self) -> list[tuple[Coord, Dict[str, Any]]]:
        """Return every surface delta as ``((x, y), attrs)``, sorted by coordinate (deterministic order)."""
        return sorted(self._surface.items())

    @property
    def has_surface_edits(self) -> bool:
        return bool(self._surface)

    # ------------------------------------------------------------------ interior layer
    def set_interior(self, interior_seed: int, floor: int, x: int, y: int, cell: int) -> None:
        """Record that interior ``interior_seed`` floor ``floor`` has ``cell`` at ``(x, y)``."""
        self._interior.setdefault((int(interior_seed), int(floor)), {})[(int(x), int(y))] = int(cell)
        self.revision += 1

    def get_interior_cell(self, interior_seed: int, floor: int, x: int, y: int) -> Optional[int]:
        """Return the overridden cell at ``(x, y)`` for this interior/floor, or None if unmodified."""
        edits = self._interior.get((int(interior_seed), int(floor)))
        if edits is None:
            return None
        return edits.get((int(x), int(y)))

    def apply_interior(self, base_grid: np.ndarray, interior_seed: int, floor: int) -> np.ndarray:
        """Return ``base_grid`` with this interior/floor's stored edits applied.

        ``base_grid`` is the deterministically regenerated interior (a 2-D ``uint8`` array of
        :class:`~biomegen.world.tile.Cell` values). If there are no edits the base is returned
        untouched; otherwise a copy is made so the caller's deterministic base is never mutated.
        """
        edits = self._interior.get((int(interior_seed), int(floor)))
        if not edits:
            return base_grid
        out = base_grid.copy()
        h, w = out.shape
        for (x, y), cell in edits.items():
            if 0 <= y < h and 0 <= x < w:
                out[y, x] = cell
        return out

    # ------------------------------------------------------------------ serialisation
    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation (string keys, list coordinates)."""
        return {
            "surface": [{"x": x, "y": y, "attrs": attrs} for (x, y), attrs in self._surface.items()],
            "interior": [
                {
                    "seed": seed,
                    "floor": floor,
                    "cells": [{"x": x, "y": y, "cell": c} for (x, y), c in cells.items()],
                }
                for (seed, floor), cells in self._interior.items()
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Overlay":
        """Rebuild an :class:`Overlay` from :meth:`to_dict` output."""
        overlay = cls()
        for entry in data.get("surface", []):
            overlay.set_surface(entry["x"], entry["y"], **entry.get("attrs", {}))
        for entry in data.get("interior", []):
            for cell in entry.get("cells", []):
                overlay.set_interior(entry["seed"], entry["floor"], cell["x"], cell["y"], cell["cell"])
        return overlay

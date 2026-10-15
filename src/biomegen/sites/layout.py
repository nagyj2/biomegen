"""What a layout is given and what it returns.

A layout turns a patch of terrain into a plan: a ``uint8`` grid ``[row, col]`` of :class:`~biomegen.world.tile.Cell`
values over the extent box, where void means the terrain shows through. Layouts register by name; a row of
``tables.sites`` picks one with its ``layout`` key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from ..config.model import Config
from ..world.tile import Cell
from .patch import SitePatch
from .streets import StreetRules

Layout = Callable[["SiteContext"], Optional[np.ndarray | tuple[np.ndarray, np.ndarray]]]
LAYOUTS: dict[str, Layout] = {}


def layout(name: str) -> Callable[[Layout], Layout]:
    """Register a layout under ``name`` (the ``layout`` key of a ``tables.sites`` row)."""

    def register(function: Layout) -> Layout:
        LAYOUTS[name] = function
        return function

    return register


@dataclass(frozen=True)
class SiteContext:
    """Everything a layout reads for one floor of one site.

    Attributes:
        kind: The POI kind.
        seed: The POI's site seed; every random choice derives from it.
        floor: The floor being built (0 is the ground and entry level: dungeons descend, towers rise).
        lowest_floor: The lowest floor of the site.
        floor_count: How many floors the site has.
        patch: The terrain under the extent, and the road gates.
        furniture: Per room role, the site's furniture as ``(cell, weight)`` pairs.
        plaza_rows: A settlement's plaza radius in rows (0 for none).
        walled: Whether a settlement has a wall.
        config: The merged configuration, for the tunables of the ``sites`` section.
        tags: The POI's site traits (``port``, ``river``, ``lake``): a settlement builds a harbour or a mill for them.
    """

    kind: str
    seed: int
    floor: int
    lowest_floor: int
    floor_count: int
    patch: SitePatch
    furniture: dict[str, list[tuple[Cell, float]]]
    plaza_rows: int
    walled: bool
    config: Config
    tags: tuple[str, ...] = ()

    def weights(self, role: str) -> list[tuple[Cell, float]]:
        """The furniture weights of a room role (empty: the role is left bare)."""
        return self.furniture.get(role, [])

    @property
    def rows(self) -> int:
        return self.patch.rows

    @property
    def cols(self) -> int:
        return self.patch.cols

    @property
    def top_floor(self) -> int:
        """The highest floor index."""
        return self.lowest_floor + self.floor_count - 1

    @property
    def aspect(self) -> float:
        """Cell height over width: how many columns look as wide as one row is tall."""
        return float(self.config.get("render.cell_aspect"))

    @property
    def street_rules(self) -> StreetRules:
        return StreetRules(
            float(self.config.get("sites.street_water_cost")),
            int(self.config.get("sites.bridge_max_rows")),
            self.aspect,
        )

    @property
    def vertical_width(self) -> int:
        """Columns a corridor running up and down needs to look as thick as one running across."""
        return max(1, round(self.aspect))

    def setting(self, key: str) -> Any:
        """Read ``sites.<key>``."""
        return self.config.get(f"sites.{key}")

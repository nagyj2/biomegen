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

Layout = Callable[
    ["SiteContext"],
    Optional[np.ndarray | tuple[np.ndarray, np.ndarray] | tuple[np.ndarray, np.ndarray, tuple["SiteBuilding", ...]]],
]
LAYOUTS: dict[str, Layout] = {}


def layout(name: str) -> Callable[[Layout], Layout]:
    """Register a layout under ``name`` (the ``layout`` key of a ``tables.sites`` row)."""

    def register(function: Layout) -> Layout:
        LAYOUTS[name] = function
        return function

    return register


@dataclass(frozen=True)
class SiteBuilding:
    """A building that stands in a site plan: what the explorer names, and what a later manifest records.

    Attributes:
        kind: Its building kind (a ``tables.buildings`` row).
        x: Column of its top-left plan cell.
        y: Row of its top-left plan cell.
        width: Its outer width in cells.
        height: Its outer height in cells.
        footprint: ``[height, width]`` bool grid of the cells under its roof.
    """

    kind: str
    x: int
    y: int
    width: int
    height: int
    footprint: np.ndarray

    def contains(self, col: int, row: int) -> bool:
        """Whether plan cell ``(col, row)`` is under this building's roof."""
        x, y = col - self.x, row - self.y
        return 0 <= x < self.width and 0 <= y < self.height and bool(self.footprint[y, x])


@dataclass(frozen=True)
class Fall:
    """How far a ruined settlement has fallen, for the settlement layout's fall pass.

    Attributes:
        standing: Share of its buildings that still stand (at least one always does).
        wall: Share of its wall that has fallen (its gates are always breached).
        erosion: Share of a fallen building's walls that have collapsed.
    """

    standing: float
    wall: float
    erosion: float


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
        age_years: Years since the POI fell (a ruin fell in with them); None when it is undated or still stands.
        purpose: The POI's purpose (a camp's: founding, bandit or army), which a layout may dress differently.
        fall: Set for a ruin of a settlement tier: the settlement layout then lays the settlement and lets it fall.
        dress: A homestead's dressing (the ``dress`` key of its site row: farm, mill, mine, lodge, fishery, or none).
        tier: The settlement tier a settlement layout draws: the POI kind, or a ruin's ``ruin_of`` (else empty).
        kinds: The specialized building kinds a settlement is chosen to have, in placing order (``settlement_kinds``).
        style: A generated hamlet's style (its first building is that style's kind and is always built), else empty.
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
    age_years: Optional[int] = None
    purpose: str = ""
    fall: Optional[Fall] = None
    dress: str = ""
    tier: str = ""
    kinds: tuple[str, ...] = ()
    style: str = ""

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

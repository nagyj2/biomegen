"""Building kinds: the rows of ``tables.buildings`` and the plan cell each kind's roof is drawn with.

A plan is one ``uint8`` array, so a kind has no cell of its own in the :class:`~biomegen.world.tile.Cell` enum: its roof
is ``KIND_ROOF_BASE + rank`` (the reserved block of ``world/tile.py``), with the glyph and colour of its row's ``roof``.
"""

from __future__ import annotations

from typing import Any, Optional

from ..config.model import Config
from ..world.entities import POI
from ..world.tile import KIND_ROOF_BASE, KIND_ROOF_SLOTS, Cell
from .building import Spec
from .layout import SiteContext


def kind_row(config: Config, kind: str) -> dict[str, Any]:
    """Return the ``tables.buildings`` row of ``kind``."""
    return dict(config.get(f"tables.buildings.{kind}"))


def _ranks(config: Config) -> dict[str, int]:
    """Kind name -> rank, for every building kind (built once per config)."""
    return config.cached(
        (__name__, "ranks"),
        lambda: {name: int(row["rank"]) for name, row in sorted(config.get("tables.buildings").items())},
    )


def roof_cell(config: Config, kind: str) -> int:
    """Return the plan cell value of ``kind``'s roof: the block's base plus the kind's rank."""
    return KIND_ROOF_BASE + _ranks(config)[kind]


def kind_of_cell(config: Config, cell: int) -> Optional[str]:
    """Return the building kind whose roof is ``cell``, or None when it is not a kind's roof cell."""
    if not KIND_ROOF_BASE <= cell < KIND_ROOF_BASE + KIND_ROOF_SLOTS:
        return None
    rank = cell - KIND_ROOF_BASE
    return next((name for name, value in _ranks(config).items() if value == rank), None)


def cell_name(config: Config, cell: int) -> str:
    """Return the lower-case name of a plan cell for a legend: the enum name, or a kind's label for its roof."""
    kind = kind_of_cell(config, cell)
    if kind is not None:
        return str(config.get(f"tables.buildings.{kind}.label")).lower()
    return Cell(cell).name.lower()


def family_weights(config: Config, family: str) -> dict[str, list[tuple[Cell, float]]]:
    """Return a furniture family's weights per room role as ``(cell, weight)`` pairs, cells in name order."""
    return {
        role: [(Cell[name.upper()], float(weight)) for name, weight in sorted(weights.items())]
        for role, weights in sorted(config.get(f"tables.furniture.{family}").items())
    }


def kind_spec(ctx: SiteContext, kind: str) -> Spec:
    """Return what a building of ``kind`` is built to: its roles, shapes and furniture family, homes' clutter density.

    Room size is the site's own (``sites.room_rows``); the kind's ``rows`` and ``width`` are the lot's business.
    """
    row = kind_row(ctx.config, kind)
    furniture = family_weights(ctx.config, str(row["furniture"]))
    density = float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.home_density"))
    roles = tuple(str(role) for role in row["roles"])
    return Spec(
        int(ctx.setting("room_rows")[0]),
        ctx.aspect,
        roles,
        {role: furniture.get(role, []) for role in roles},
        density,
        tuple(str(shape) for shape in row["shapes"]),
    )


def lot_rows(config: Config, kind: str) -> tuple[int, int]:
    """Return the ``(shortest, tallest)`` outer height in rows a lot of ``kind`` takes."""
    lo, hi = kind_row(config, kind)["rows"]
    return int(lo), int(hi)


def lot_widths(config: Config, kind: str, aspect: float) -> tuple[int, int]:
    """Return the ``(narrowest, widest)`` outer width in columns a lot of ``kind`` takes.

    The row's ``width`` is a multiple of its height times the cell aspect: the narrowest from its shortest height, the
    widest from its tallest.
    """
    row = kind_row(config, kind)
    rows_lo, rows_hi = lot_rows(config, kind)
    narrow, wide = row["width"]
    return round(float(narrow) * rows_lo * aspect), round(float(wide) * rows_hi * aspect)


def centre_kind(config: Config, poi: POI) -> Optional[str]:
    """Return the civic kind at the plaza of ``poi``: its tier's ``centre``, or None for a kind with no tier.

    A ruin has the centre of the tier it was (``ruin_of``); a homestead or a wild site is no settlement and has none.
    """
    tier = poi.ruin_of or poi.kind
    centre = config.get(f"tables.tiers.{tier}.centre", None)
    return None if centre is None else str(centre)


def tier_centre(config: Config, tier: str) -> str:
    """Return the civic kind that stands at the plaza of a settlement of ``tier``."""
    return str(config.get(f"tables.tiers.{tier}.centre"))


def tier_reserve(config: Config, tier: str) -> str:
    """Return the civic kind whose plot a ``tier`` plaza keeps: the next tier's centre, else its own."""
    return str(config.get(f"tables.tiers.{tier}.reserve", tier_centre(config, tier)))

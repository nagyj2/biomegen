"""Building kinds: the rows of ``tables.buildings`` and the plan cell each kind's roof is drawn with.

A plan is one ``uint8`` array, so a kind has no cell of its own in the :class:`~biomegen.world.tile.Cell` enum: its roof
is ``KIND_ROOF_BASE + rank`` (the reserved block of ``world/tile.py``), with the glyph and colour of its row's ``roof``.
"""

from __future__ import annotations

from typing import Any, Optional

from ..config.model import Config
from ..world.tile import KIND_ROOF_BASE, KIND_ROOF_SLOTS, Cell


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

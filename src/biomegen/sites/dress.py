"""Dressings: the ground cover and small works laid round a building, and the variants a condition picks from.

A dressing (a row of ``tables.dress``: a field, ...) has variants, each an existing :class:`~biomegen.world.tile.Cell`
or a look of its own with a plan cell in the reserved block ``DRESS_BASE + rank``. A site asks for the dress for its
kind in its condition (a standing site or a ruin) and the table answers by weight, so a standing field is full or
harvested and a ruin's harvested or dead. This module is the data side; the layouts lay the cells.
"""

from __future__ import annotations

import random
from typing import Optional

from ..config.model import Config
from ..world.tile import DRESS_BASE, DRESS_SLOTS, Cell

CONDITIONS = ("standing", "ruin")


def _variants(config: Config, dress: str) -> dict[str, dict]:
    """The variants of ``dress``, by name."""
    return dict(config.get(f"tables.dress.{dress}.variants"))


def variant_cell(config: Config, dress: str, variant: str) -> int:
    """Return the plan cell of a variant: its existing ``cell``, else the dress block's base plus its rank."""
    row = _variants(config, dress)[variant]
    if "cell" in row:
        return int(Cell[str(row["cell"]).upper()])
    return DRESS_BASE + int(row["rank"])


def variants_for(config: Config, dress: str, condition: str, kind: str) -> list[tuple[str, float]]:
    """Return ``(variant, weight)`` for each variant of ``dress`` that may appear at POI ``kind`` in ``condition``.

    Variants are in name order; a variant with weight 0 in the condition, or whose ``kinds`` omit ``kind``, is left out.
    """
    rows = _variants(config, dress)
    return [
        (name, float(rows[name][condition]))
        for name in sorted(rows)
        if float(rows[name][condition]) > 0.0 and kind in rows[name].get("kinds", [kind])
    ]


def pick_variant(config: Config, dress: str, condition: str, kind: str, stream: random.Random) -> str:
    """Draw a variant of ``dress`` for a site of POI ``kind`` in ``condition`` (``standing`` or ``ruin``), by weight.

    Raises ``ValueError`` when no variant may appear there.
    """
    table = variants_for(config, dress, condition, kind)
    if not table:
        raise ValueError(f"no variant of dress {dress!r} may appear at a {kind} in the {condition} condition")
    roll = stream.random() * sum(weight for _name, weight in table)
    running = 0.0
    for name, weight in table:
        running += weight
        if roll < running:
            return name
    return table[-1][0]


def variant_of_cell(config: Config, cell: int) -> Optional[tuple[str, str]]:
    """Return ``(dress, variant)`` for a cell of the dress block, or None when ``cell`` is not one."""
    if not DRESS_BASE <= cell < DRESS_BASE + DRESS_SLOTS:
        return None
    rank = cell - DRESS_BASE
    for dress in sorted(config.get("tables.dress")):
        for name, row in sorted(_variants(config, dress).items()):
            if "cell" not in row and int(row["rank"]) == rank:
                return dress, name
    return None

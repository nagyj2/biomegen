"""Which plan cells the renderer draws at which scale, and which can be walked."""

from __future__ import annotations

import numpy as np

from ..world.tile import DRESS_BASE, DRESS_SLOTS, KIND_ROOF_BASE, KIND_ROOF_SLOTS, Cell

VOID = int(Cell.VOID)  # not part of the site: the terrain shows through

# The structure outline: walls, doors and stairs. The map scale draws only these, as a small image of the wall plan.
STRUCTURAL: frozenset[int] = frozenset({int(Cell.WALL), int(Cell.DOOR), int(Cell.STAIRS_UP), int(Cell.STAIRS_DOWN)})

# The building shell drawn at the zoom scale: the outline plus floor, water, paths and bridges, but not furniture.
SHELL: frozenset[int] = STRUCTURAL | frozenset(
    {int(Cell.FLOOR), int(Cell.WATER), int(Cell.PATH), int(Cell.BRIDGE), int(Cell.BRIDGE_WALL)}
)

# Cells a walker can stand on.
PASSABLE: frozenset[int] = frozenset(
    {
        int(Cell.FLOOR),
        int(Cell.RUBBLE),
        int(Cell.DOOR),
        int(Cell.STAIRS_UP),
        int(Cell.STAIRS_DOWN),
        int(Cell.PATH),
        int(Cell.BRIDGE),
    }
)

_CELLS = max(int(cell) for cell in Cell) + 1
_WALLISH = (int(Cell.WALL), int(Cell.DOOR))

# What wins when a plan is drawn smaller and several cells share one: the highest number. A roof or a solid wall beats
# a street, which beats anything else drawn, which beats bare terrain (void).
OUTSIDE_PRIORITY = np.zeros(256, dtype=np.uint8)
OUTSIDE_PRIORITY[:_CELLS] = 1
OUTSIDE_PRIORITY[VOID] = 0
for _cell in (Cell.PATH, Cell.BRIDGE, Cell.BRIDGE_WALL, Cell.DOOR, Cell.WHEEL, Cell.AXLE_H, Cell.AXLE_V, Cell.BANNER):
    OUTSIDE_PRIORITY[int(_cell)] = 2
for _cell in (Cell.ROOF, Cell.STONE, Cell.WALL, Cell.HULL, Cell.TENT):
    OUTSIDE_PRIORITY[int(_cell)] = 3
OUTSIDE_PRIORITY[KIND_ROOF_BASE : KIND_ROOF_BASE + KIND_ROOF_SLOTS] = (
    3  # a building kind's roof is a roof; the higher id wins a tie
)
OUTSIDE_PRIORITY[DRESS_BASE : DRESS_BASE + DRESS_SLOTS] = (
    1  # a dress variant is ground cover, like the cells it stands for
)

NO_WALL = 255  # ``wall_index`` of a cell that is not a wall


def wall_index(cells: np.ndarray) -> np.ndarray:
    """Return, per cell, which of the 16 line glyphs a wall draws, or ``NO_WALL`` for a cell that is not a wall.

    The index is a bit mask of which neighbours (north 1, east 2, south 4, west 8) are also wall or door, so adjoining
    walls join into box-drawing lines.
    """
    wallish = np.isin(cells, _WALLISH)
    padded = np.pad(wallish, 1)
    index = (
        padded[:-2, 1:-1].astype(np.uint8)
        | (padded[1:-1, 2:].astype(np.uint8) << 1)
        | (padded[2:, 1:-1].astype(np.uint8) << 2)
        | (padded[1:-1, :-2].astype(np.uint8) << 3)
    )
    return np.where(cells == int(Cell.WALL), index, NO_WALL).astype(np.uint8)

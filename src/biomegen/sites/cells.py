"""Which plan cells the renderer draws at which scale, and which can be walked."""

from __future__ import annotations

from ..world.tile import Cell

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

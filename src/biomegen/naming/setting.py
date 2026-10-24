"""The setting of a settlement: the row of ``tables.settlement_names`` (coast, river, hills, ...) its place matches."""

from __future__ import annotations

from typing import Optional

from ..config.model import Config
from ..world.entities import POI
from ..world.tile import BIOME_NAME, RELIEF_NAME
from ..world.world import World


def setting_row(world: World, config: Config, poi: POI) -> Optional[dict]:
    """Return the first row of ``tables.settlement_names`` (file order) that ``poi`` matches by tag, relief or biome."""
    relief = RELIEF_NAME[int(world.relief[poi.y, poi.x])]
    biome = BIOME_NAME[int(world.biome[poi.y, poi.x])]
    for row in config.get("tables.settlement_names").values():
        if (
            any(tag in poi.tags for tag in row.get("tags", ()))
            or relief in row.get("reliefs", ())
            or biome in row.get("biomes", ())
        ):
            return dict(row)
    return None

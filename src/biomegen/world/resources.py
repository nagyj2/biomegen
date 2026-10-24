"""What a realm's land yields, read from the ``resource`` column of the biome and relief tables.

Pure functions of the finished world and the config (``data/resources.toml``), so the derived history and a later
simulation (docs/simulation_plan.md 3.2 and 3.6) read a realm's wealth the same way. A cell yields the resource of its
relief when that row names one (hills give stone, mountains metal), else of its biome (grass food, forest wood); water,
bare land and ice yield none. A ``goods`` name is the chronicle's word for what a row yields ("grain", "iron").
"""

from __future__ import annotations

import numpy as np

from ..config.model import Config
from .tile import BIOME_NAME, RELIEF_NAME
from .world import World


def land_resources(config: Config) -> list[str]:
    """Return the resources land can yield (every row that is not the currency), sorted by name."""
    rows = config.get("tables.resources")
    return sorted(name for name, row in rows.items() if row["kind"] != "currency")


def _yield_grid(world: World, config: Config, names: list[str]) -> np.ndarray:
    """Return the index into ``names`` of what each cell yields (-1 for nothing): its relief's, else its biome's."""
    index = {name: i for i, name in enumerate(names)}
    biomes = np.full(max(BIOME_NAME) + 1, -1, dtype=np.int16)
    reliefs = np.full(max(RELIEF_NAME) + 1, -1, dtype=np.int16)
    for value, name in BIOME_NAME.items():
        biomes[value] = index.get(str(config.get(f"tables.biomes.{name}.resource")), -1)
    for value, name in RELIEF_NAME.items():
        reliefs[value] = index.get(str(config.get(f"tables.relief.{name}.resource")), -1)
    from_relief = reliefs[world.relief]
    return np.where(from_relief >= 0, from_relief, biomes[world.biome])


def realm_supply(world: World, config: Config) -> dict[int, dict[str, float]]:
    """Return, for every realm id, the share of its land cells that yield each land resource (0 for none).

    The shares of one realm sum to at most 1: cells that yield nothing (a lake, bare ground) count in the total only.
    """
    names = land_resources(config)
    count = len(names)
    grid = _yield_grid(world, config, names)
    owner = world.realm_id.astype(np.int64)
    held = owner >= 0
    slots = owner[held] * (count + 1) + np.where(grid[held] >= 0, grid[held], count)
    totals = np.bincount(slots, minlength=len(world.realms) * (count + 1)).reshape(len(world.realms), count + 1)
    cells = np.maximum(totals.sum(axis=1), 1)
    return {
        realm.id: {name: float(totals[realm.id, i]) / float(cells[realm.id]) for i, name in enumerate(names)}
        for realm in world.realms
    }


def goods_word(world: World, config: Config, realm_id: int, resource: str) -> str:
    """Return the goods name ``realm_id``'s land is known for in ``resource`` ("" when it yields none).

    That is the ``goods`` of the biome or relief row that yields the resource on most of the realm's cells (the row with
    the smaller name wins a tie); a row with no goods name gives the resource's label in lower case.
    """
    names = land_resources(config)
    if resource not in names:
        return ""
    mine = (world.realm_id == realm_id) & (_yield_grid(world, config, names) == names.index(resource))
    from_relief = np.zeros(max(RELIEF_NAME) + 1, dtype=bool)
    for value, name in RELIEF_NAME.items():
        from_relief[value] = str(config.get(f"tables.relief.{name}.resource")) == resource
    by_relief = mine & from_relief[world.relief]
    counts: dict[tuple[str, str], int] = {}
    for table, enum_names, array, selected in (
        ("relief", RELIEF_NAME, world.relief, by_relief),
        ("biomes", BIOME_NAME, world.biome, mine & ~by_relief),
    ):
        for value, name in enum_names.items():
            cells = int(np.count_nonzero(selected & (array == value)))
            if cells:
                counts[(table, name)] = cells
    if not counts:
        return ""
    table, name = min(counts, key=lambda key: (-counts[key], key[1]))
    return (
        str(config.get(f"tables.{table}.{name}.goods")) or str(config.get(f"tables.resources.{resource}.label")).lower()
    )

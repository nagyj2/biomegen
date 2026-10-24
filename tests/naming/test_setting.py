"""Settlement names by setting: ``tables.settlement_names`` rows picked from a settlement's tags, relief and biome."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.naming import forge
from biomegen.naming.setting import setting_row
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, Relief
from biomegen.world.world import World


def _world_with(biome: Biome, relief: Relief) -> World:
    world = World(8, 8, 0)
    world.biome[:] = int(biome)
    world.relief[:] = int(relief)
    return world


def _poi(tags: tuple[str, ...] = ()) -> POI:
    return POI(kind="village", x=3, y=3, interior_seed=0, civilized=True, tags=tags)


def test_a_port_tag_outranks_the_terrain() -> None:
    # Rows are tried in file order, so the coast wins over hills under the same settlement.
    row = setting_row(_world_with(Biome.GRASS, Relief.HILLS), load_config(None), _poi(("port",)))
    assert row is not None and "{n} Port" in row["forms"]


def test_hills_match_by_relief() -> None:
    row = setting_row(_world_with(Biome.GRASS, Relief.HILLS), load_config(None), _poi())
    assert row is not None and "{n} Hill" in row["forms"]


def test_a_plain_settlement_matches_no_row() -> None:
    assert setting_row(_world_with(Biome.GRASS, Relief.NONE), load_config(None), _poi()) is None


def test_chance_one_always_uses_a_setting_form() -> None:
    name = forge.name_entity(
        1, "poi", (3, 3), "common", None, None, civilized=True, setting_forms=["{n} Port"], setting_chance=1.0
    )
    assert name.endswith(" Port")


def test_chance_zero_keeps_the_plain_name() -> None:
    plain = forge.name_entity(1, "poi", (3, 3), "common", None, None, civilized=True)
    kept = forge.name_entity(1, "poi", (3, 3), "common", None, None, civilized=True, setting_forms=["{n} Port"])
    assert kept == plain

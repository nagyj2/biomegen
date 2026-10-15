"""Stage 10: naming.

Runs last, once realms, diplomacy, POIs, rivers, lakes and geographic features all exist. Each realm gets a culture
(biome-biased, seeded on the realm id; a vassal keeps its own), then the island, every POI, river, lake and geographic
feature is named in the culture of the realm that holds it (wild land and open water use ``common``). Realms are named
once their seats are, and the reasons of the relations are worded once every place has a name. Names are keyed on
stable entity identity, so the result is invariant to processing order. Names live on the entity objects (not the
numpy arrays), so this stage does not change ``World.fingerprint()``.
"""

from __future__ import annotations

from ..config.model import Config
from ..naming import cultures, forge, polity
from ..world.world import World

COMMON = "common"


def _culture_at(world: World, realm_culture: dict[int, str], x: int, y: int) -> str:
    """Culture of the realm under (x, y); 'common' for wild land and open water."""
    return realm_culture.get(int(world.realm_id[y, x]), COMMON)


def run(world: World, config: Config, seed: int) -> None:
    """Name everything, mutating the entities in place."""
    naming_cfg = config.section("naming")
    generators = config.get("naming.generators")

    # 1. Assign a culture to each realm (stable, biome-biased).
    for realm in world.realms:
        realm.culture = cultures.culture_for_realm(seed, realm)
    realm_culture = {realm.id: realm.culture for realm in world.realms}

    # 2. Island name from the largest realm (lowest id breaks ties).
    if world.realms:
        largest = max(world.realms, key=lambda r: (r.area_km2, -r.id))
        world.island_name = forge.name_entity(seed, "island", (largest.id,), largest.culture, generators, naming_cfg)
    else:
        world.island_name = ""

    # 3. Name POIs.
    for poi in world.pois:
        poi.name = forge.name_entity(
            seed,
            "poi",
            (poi.x, poi.y),
            realm_culture.get(poi.realm_id, COMMON),
            generators,
            naming_cfg,
            kind=poi.kind,
            civilized=poi.civilized,
        )

    # 4. Name rivers and lakes by the culture of the realm they traverse.
    for river in world.rivers:
        cell = river.mouth or river.path[len(river.path) // 2]
        river.name = forge.name_entity(
            seed, "river", (cell[0], cell[1]), _culture_at(world, realm_culture, *cell), generators, naming_cfg
        )
    for lake in world.lakes:
        cell = sorted(lake.tiles)[0] if lake.tiles else (0, 0)
        lake.name = forge.name_entity(
            seed, "lake", (cell[0], cell[1]), _culture_at(world, realm_culture, *cell), generators, naming_cfg
        )
    _name_features(world, config, seed, realm_culture)

    # 5. Name realms (their seats are named now), then word the relations (every place is named now).
    for realm in sorted(world.realms, key=lambda r: r.id):
        polity.name_realm(seed, realm, polity.seat_name(world, realm) or "", config)
    polity.describe_relations(world, config, seed)


def _name_features(world: World, config: Config, seed: int, realm_culture: dict[int, str]) -> None:
    """Name geographic features: lakes and rivers take their entity's name, the rest a geo_names form."""
    generators = config.get("naming.generators")
    naming_cfg = config.section("naming")
    rows = config.get("tables.geo_names")
    for feature in world.features:
        if feature.kind == "lake":
            feature.name = world.lakes[feature.ref].name
        elif feature.kind == "river":
            feature.name = world.rivers[feature.ref].name
        else:
            x, y = feature.anchor
            culture = _culture_at(world, realm_culture, x, y)
            feature.name = forge.name_feature(
                seed, feature.kind, (x, y), culture, rows[feature.kind], generators, naming_cfg
            )

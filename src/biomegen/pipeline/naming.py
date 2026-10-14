"""Stage 10: naming + region lore.

Runs last, once regions, POIs, rivers, lakes and geographic features all exist. It assigns each region
a culture (biome-biased, seeded on the region id), then names the island, every region, POI, river,
lake and geographic feature using that culture, and writes balanced lore for each region from its real
contents. Names are keyed on stable entity identity, so the result is invariant to processing order.
Names live on the entity objects (not the numpy arrays), so this stage does not change
``World.fingerprint()``.
"""

from __future__ import annotations

from ..config.model import Config
from ..naming import cultures, forge, grammar, lore
from ..util import rng
from ..world.world import World


def _culture_at(region_culture: dict[int, str], world: World, x: int, y: int) -> str:
    """Culture of the region under (x, y); 'common' if the tile has no region (open water)."""
    rid = int(world.region_id[y, x])
    return region_culture.get(rid, "common")


def run(world: World, config: Config, seed: int) -> None:
    """Name everything and write region lore, mutating the entities in place."""
    if not world.regions:
        world.island_name = ""
        _name_features(world, config, seed, {})
        return

    naming_cfg = config.section("naming")
    generators = config.get("naming.generators")
    lore_min = int(config.get("naming.lore_min"))
    lore_max = int(config.get("naming.lore_max"))
    rules = grammar.load_rules()

    # 1. Assign a culture to each region (stable, biome-biased).
    region_culture = {r.id: cultures.culture_for_region(seed, r) for r in world.regions}

    # 2. Name and describe each region.
    for region in sorted(world.regions, key=lambda r: r.id):
        cult_name = region_culture[region.id]
        culture = cultures.CULTURES[cult_name]
        descriptor = lore.geo_word(rng.derive(seed, "naming", "regiondesc", region.id), region.biome_class)
        region.name = forge.name_entity(
            seed, "region", (region.id,), cult_name, generators, naming_cfg, descriptor=descriptor
        )
        facts = lore.extract_facts(world, region, culture, rng.derive(seed, "naming", "lorefacts", region.id))
        facts["region_name"] = region.name
        region.lore = grammar.render_lore(
            rng.derive(seed, "naming", "lore", region.id), rules, facts, lore_min, lore_max
        )

    # 3. Island name from the dominant region (largest by tiles; lowest id breaks ties).
    dominant = max(world.regions, key=lambda r: (r.size, -r.id))
    world.island_name = forge.name_entity(
        seed, "island", (dominant.id,), region_culture[dominant.id], generators, naming_cfg
    )

    # 4. Name POIs (bridges stay unnamed - they are infrastructure).
    for poi in world.pois:
        if poi.kind == "bridge":
            continue
        cult = region_culture.get(poi.region_id, "common") if poi.region_id >= 0 else "common"
        poi.name = forge.name_entity(
            seed, "poi", (poi.x, poi.y), cult, generators, naming_cfg, kind=poi.kind, civilized=poi.civilized
        )

    # 5. Name rivers and lakes by the culture of the region they traverse.
    for river in world.rivers:
        cell = river.mouth or river.path[len(river.path) // 2]
        river.name = forge.name_entity(
            seed,
            "river",
            (cell[0], cell[1]),
            _culture_at(region_culture, world, cell[0], cell[1]),
            generators,
            naming_cfg,
        )
    for lake in world.lakes:
        cell = sorted(lake.tiles)[0] if lake.tiles else (0, 0)
        lake.name = forge.name_entity(
            seed,
            "lake",
            (cell[0], cell[1]),
            _culture_at(region_culture, world, cell[0], cell[1]),
            generators,
            naming_cfg,
        )
    _name_features(world, config, seed, region_culture)


def _name_features(world: World, config: Config, seed: int, region_culture: dict[int, str]) -> None:
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
            culture = _culture_at(region_culture, world, x, y)
            feature.name = forge.name_feature(
                seed, feature.kind, (x, y), culture, rows[feature.kind], generators, naming_cfg
            )

"""Tests for the legend and gazetteer."""

from __future__ import annotations

from biomegen.render.backends.plain import to_plain
from biomegen.render.furniture.legend import build_legend
from biomegen.render.views import View
from biomegen.world.tile import Biome, Relief, WaterType
from tests.render.conftest import add_feature, make_world

TERRAIN = View("terrain", ("terrain",))
ELEVATION = View("elevation", ("terrain", "tint"), "elevation")


def _world():
    world = make_world(20, 10, Biome.GRASS, 100.0)
    world.biome[:, :5] = int(Biome.DEEP)
    world.relief[4, 10] = int(Relief.MOUNTAIN)
    world.water_type[2, 10] = int(WaterType.FRESH)
    world.temperature_c[:] = 12.0
    world.rain_mm[:] = 900.0
    peak = add_feature(world, "peak", "Mount Kel", (10, 4), elevation_m=2100.0)
    add_feature(world, "landmass", "Orlo", (12, 5), [(10, 4)], area_km2=2_000_000.0, summit=peak.id)
    add_feature(world, "sea", "Calm Sea", (2, 5), elevation_m=-3200.0)
    return world


def _text(config, view=TERRAIN, ascii_only=False) -> str:
    return to_plain(build_legend(_world(), config, view, 100, ascii_only))


def test_legend_lists_the_biomes_present(config) -> None:
    text = _text(config)
    assert config.get("tables.biomes.grass.label") in text and config.get("tables.biomes.desert.label") not in text


def test_legend_lists_rivers_and_relief_that_exist(config) -> None:
    assert "River" in _text(config) and config.get("tables.relief.mountain.label") in _text(config)


def test_legend_omits_roads_when_there_are_none(config) -> None:
    assert "Road" not in _text(config)


def test_geography_calls_a_large_landmass_a_continent(config) -> None:
    assert "Orlo - continent, 2.0 million km²" in _text(config)


def test_geography_names_the_summit(config) -> None:
    assert "highest point Mount Kel (2,100 m)" in _text(config)


def test_geography_gives_sea_depth(config) -> None:
    assert "Calm Sea - depths to 3,200 m" in _text(config)


def test_climate_reports_the_extremes(config) -> None:
    assert "Temperature 12 °C" in _text(config) and "900 mm/yr" in _text(config)


def test_data_view_adds_a_ramp_bar(config) -> None:
    assert "ELEVATION (m)" in _text(config, ELEVATION)


def test_data_view_hides_the_biome_swatches(config) -> None:
    assert config.get("tables.biomes.grass.label") not in _text(config, ELEVATION)


def test_ascii_legend_is_pure_ascii(config) -> None:
    assert _text(config, ascii_only=True).isascii()


def test_legend_wraps_within_the_width(config) -> None:
    assert max(len(line) for line in _text(config).split("\n")) <= 100 + 24


def test_a_political_legend_has_no_ramp_bar_but_lists_relief(config) -> None:
    text = _text(config, View("political", ("terrain", "tint"), "realm"))
    assert config.get("tables.relief.mountain.label") in text and "ELEVATION" not in text


# --- the political legend -----------------------------------------------------------------------------------------

POLITICAL = View("political", ("terrain", "tint"), "realm")


def _political_world():
    from biomegen.world.entities import POI, Realm, Relation

    world = _world()
    world.pois.append(
        POI(kind="capital", x=12, y=5, interior_seed=1, civilized=True, name="Aldoria", realm_id=0, pop=900)
    )
    world.pois.append(POI(kind="town", x=14, y=5, interior_seed=2, civilized=True, name="Dunmere", realm_id=2, pop=90))
    world.pois.append(
        POI(kind="village", x=7, y=5, interior_seed=3, civilized=True, name="Nowhere Hamlet", realm_id=-1)
    )
    world.realms = [
        Realm(
            id=0,
            kind="major",
            name="Kingdom of Aldor",
            short="Aldor",
            ruler="Queen Mara",
            seat_poi=0,
            area_km2=1_200_000.0,
            pop=3_400_000,
            vassals=[1],
            color=(200, 40, 40),
        ),
        Realm(
            id=1,
            kind="tribal",
            name="The Hill Holds",
            short="Hills",
            ruler="the Moot",
            liege=0,
            area_km2=20_000.0,
            pop=2_500,
            color=(220, 120, 120),
        ),
        Realm(
            id=2,
            kind="major",
            name="Duchy of Brek",
            short="Brek",
            ruler="Duke Orn",
            seat_poi=1,
            area_km2=800_000.0,
            pop=700_000,
            color=(40, 40, 200),
        ),
    ]
    world.realm_id[:, 5:12] = 0
    world.realm_id[:, 12:] = 2
    world.relations = [
        Relation(a=0, b=2, kind="war", border_km=450.0, why="an assassinated envoy", attacker=2, claim_poi=0),
        Relation(a=0, b=2, kind="trade", border_km=0.0, why="grain from Aldor for timber from Brek"),
    ]
    return world


def _political_text(config, ascii_only=False) -> str:
    return to_plain(build_legend(_political_world(), config, POLITICAL, 100, ascii_only))


def test_the_political_legend_lists_each_realm_with_its_ruler(config) -> None:
    text = _political_text(config)
    assert "Kingdom of Aldor" in text and "Ruled by Queen Mara from Aldoria" in text and "Duchy of Brek" in text


def test_a_realm_without_a_seat_has_no_fixed_seat(config) -> None:
    assert "Ruled by the Moot with no fixed seat" in _political_text(config)


def test_a_vassal_is_listed_below_its_overlord_and_tagged(config) -> None:
    lines = _political_text(config).splitlines()
    overlord = next(i for i, line in enumerate(lines) if "Kingdom of Aldor" in line)
    vassal = next(i for i, line in enumerate(lines) if "The Hill Holds" in line)
    assert (
        vassal > overlord
        and "[vassal tribal lands]" in lines[vassal]
        and lines[vassal].index("■") > lines[overlord].index("■")
    )


def test_a_realm_line_gives_area_population_and_settlements(config) -> None:
    assert "1.2 million km²" in _political_text(config) and "pop. ~3.4 million" in _political_text(config)


def test_free_settlements_are_counted_with_the_wilds(config) -> None:
    assert "holding 1 free settlement." in _political_text(config)


def test_a_war_names_the_sides_the_reason_and_the_claimed_town(config) -> None:
    text = " ".join(_political_text(config).split())
    assert (
        "WAR Duchy of Brek vs Kingdom of Aldor over an assassinated envoy; front 450 km. Brek claims Aldoria." in text
    )


def test_a_pact_across_the_sea_is_marked(config) -> None:
    assert "(by sea)." in _political_text(config)


def test_wars_are_listed_before_trade(config) -> None:
    text = _political_text(config)
    assert text.index("WAR") < text.index("TRADE PACT")


def test_the_political_legend_uses_an_ascii_swatch(config) -> None:
    assert "# Kingdom of Aldor" in _political_text(config, ascii_only=True)


def test_other_views_have_no_realms_section(config) -> None:
    assert "REALMS" not in to_plain(build_legend(_political_world(), config, TERRAIN, 100, False))


def _free_text(config, realm_id: int) -> str:
    from biomegen.world.entities import POI

    world = _world()
    world.pois.append(POI(kind="village", x=8, y=5, interior_seed=3, civilized=True, realm_id=realm_id))
    return to_plain(build_legend(world, config, TERRAIN, 100, False))


def test_the_legend_has_a_swatch_for_free_settlements(config) -> None:
    assert "Free settlement" in _free_text(config, -1)


def test_the_legend_has_no_free_swatch_when_every_settlement_is_held(config) -> None:
    assert "Free settlement" not in _free_text(config, 0)


def _origin_text(config, **fields) -> str:
    from biomegen.world.entities import Predecessor

    world = _political_world()
    world.realms[1].founded = 480
    for name, value in fields.items():
        setattr(world.realms[1], name, value)
    world.predecessors = [Predecessor(id=0, founded=20, split_year=480, name="Old Kingdom")]
    return " ".join(to_plain(build_legend(world, config, POLITICAL, 100, False)).split())  # the legend wraps lines


def test_an_offshoot_is_listed_with_the_realm_it_broke_from(config) -> None:
    assert "Broke from" in _origin_text(config, origin="offshoot", parent=0)


def test_a_realm_of_a_split_is_listed_with_the_old_realm(config) -> None:
    assert "Came of the split of Old Kingdom in year 480" in _origin_text(config, origin="split", predecessor=0)


def test_a_realm_founded_outright_has_no_origin_line(config) -> None:
    assert "Broke from" not in _origin_text(config) and "split of" not in _origin_text(config)


def _political_text_with(config, *extra) -> str:
    world = _political_world()
    world.pois.extend(extra)
    return to_plain(build_legend(world, config, POLITICAL, 100, False))


def test_a_hamlet_is_not_counted_among_a_realms_settlements(config) -> None:
    from biomegen.world.entities import POI

    held = POI(kind="hamlet", x=13, y=6, interior_seed=9, civilized=True, name="Tiny", realm_id=0, pop=30)
    realms = lambda text: text[text.index("REALMS") :]  # noqa: E731  (the marker list above it gains a hamlet swatch)
    assert realms(_political_text_with(config, held)) == realms(_political_text(config))


def test_a_free_hamlet_is_not_counted_among_the_free_settlements(config) -> None:
    from biomegen.world.entities import POI

    free = POI(kind="hamlet", x=6, y=6, interior_seed=9, civilized=True, name="Tiny", realm_id=-1, pop=30)
    assert "holding 1 free settlement." in _political_text_with(config, free)

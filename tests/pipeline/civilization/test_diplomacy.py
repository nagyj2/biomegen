"""Tests for the diplomacy stage: borders, vassal trees, colours, relations and war fronts."""

from __future__ import annotations

import colorsys

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.civilization import diplomacy
from biomegen.pipeline.story.places import nearest_feature
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI, Realm
from biomegen.world.tile import Biome
from biomegen.world.world import World

HEIGHT = 4


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def generated(cfg: Config) -> World:
    return pipeline.generate(cfg, 42)


def _config(**weights: float) -> Config:
    """Defaults where every vassal chance is 1 and relations are drawn from ``weights`` (war only when none given)."""
    config = load_config(None)
    for kind in ("major", "city_state", "tribal"):
        config.data["tables"]["realm_kinds"][kind]["vassal_chance"] = 0.0
    chosen = weights or {"war": 1.0}
    for pair in ("major_pair", "other_pair"):
        config.data["tables"]["relation_weights"][pair] = {
            key: chosen.get(key, 0.0) for key in ("war", "rivalry", "alliance", "trade", "none")
        }
    return config


def _land(widths: list[int], kinds: list[str]) -> World:
    """A land of ``HEIGHT`` rows split into side-by-side realms of the given column widths (30 x 60 km cells)."""
    width = sum(widths)
    world = World(width, HEIGHT, 1, grid_scale(width, HEIGHT, (width * 30.0, HEIGHT * 60.0), 30.0, 0.0))
    world.biome[:] = int(Biome.GRASS)
    start = 0
    for k, (cols, kind) in enumerate(zip(widths, kinds, strict=True)):
        world.realm_id[:, start : start + cols] = k
        world.realms.append(Realm(id=k, kind=kind, area_km2=cols * HEIGHT * world.scale.cell_area_km2))
        start += cols
    return world


def _town(world: World, kind: str, x: int, y: int) -> int:
    poi = POI(kind=kind, x=x, y=y, interior_seed=1, civilized=True, pop=500, realm_id=int(world.realm_id[y, x]))
    world.pois.append(poi)
    return len(world.pois) - 1


def _run(world: World, config: Config) -> World:
    diplomacy.run(world, config, 1)
    return world


def _saturation(rgb: tuple[int, int, int]) -> float:
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[1]


# --- borders ----------------------------------------------------------------------------------------------------------


def test_border_length_is_the_edge_length_in_km() -> None:
    # Two realms side by side share one vertical boundary: HEIGHT rows of 60 km.
    world = _land([3, 3], ["major", "major"])
    assert diplomacy._border_km(diplomacy._edges(world)) == {(0, 1): HEIGHT * 60.0}


def test_realms_that_do_not_touch_share_no_border() -> None:
    world = _land([2, 2, 2], ["major", "major", "major"])
    assert (0, 2) not in diplomacy._border_km(diplomacy._edges(world))


# --- vassalage --------------------------------------------------------------------------------------------------------


def test_a_much_smaller_major_swears_fealty() -> None:
    config = _config()
    config.data["tables"]["realm_kinds"]["major"]["vassal_chance"] = 1.0
    world = _run(_land([2, 6], ["major", "major"]), config)
    assert (world.realms[0].liege, world.realms[1].vassals) == (1, [0])


def test_a_major_of_similar_size_stays_independent() -> None:
    config = _config()
    config.data["tables"]["realm_kinds"]["major"]["vassal_chance"] = 1.0
    world = _run(_land([4, 5], ["major", "major"]), config)
    assert world.realms[0].liege == -1 and world.realms[1].liege == -1


def test_an_overlord_cannot_itself_swear_fealty() -> None:
    # C swears to B, so B (which now has a vassal) stays independent even though A dwarfs it.
    config = _config()
    config.data["tables"]["realm_kinds"]["major"]["vassal_chance"] = 1.0
    world = _run(_land([1, 4, 10], ["major", "major", "major"]), config)
    assert (world.realms[0].liege, world.realms[1].liege) == (1, -1)


def test_a_city_state_swears_to_a_neighbouring_major() -> None:
    config = _config()
    config.data["tables"]["realm_kinds"]["city_state"]["vassal_chance"] = 1.0
    world = _run(_land([5, 2], ["major", "city_state"]), config)
    assert world.realms[1].liege == 0


def test_a_city_state_with_no_major_neighbour_stays_independent() -> None:
    config = _config()
    config.data["tables"]["realm_kinds"]["city_state"]["vassal_chance"] = 1.0
    world = _run(_land([2, 2], ["city_state", "city_state"]), config)
    assert [r.liege for r in world.realms] == [-1, -1]


def test_a_vassal_is_listed_by_its_overlord(generated: World) -> None:
    assert all(r.id in generated.realms[r.liege].vassals for r in generated.realms if r.liege >= 0)


def test_the_vassal_tree_has_no_cycles(generated: World) -> None:
    # Following lieges from any realm reaches an independent one in fewer steps than there are realms.
    for realm in generated.realms:
        steps, here = 0, realm
        while here.liege >= 0:
            here = generated.realms[here.liege]
            steps += 1
            assert steps < len(generated.realms)


# --- colours ----------------------------------------------------------------------------------------------------------


def test_a_vassal_is_paler_than_its_overlord(generated: World) -> None:
    vassals = [r for r in generated.realms if r.liege >= 0]
    assert vassals and all(
        _saturation(r.color) < _saturation(generated.realms[generated.top_realm(r.id)].color) for r in vassals
    )


def test_independent_majors_have_distinct_colours(generated: World) -> None:
    colours = [r.color for r in generated.realms if r.kind == "major" and r.liege < 0]
    assert len(set(colours)) == len(colours)


# --- relations --------------------------------------------------------------------------------------------------------


def test_relations_are_only_between_independent_powers(generated: World) -> None:
    assert all(generated.realms[r.a].liege < 0 and generated.realms[r.b].liege < 0 for r in generated.relations)


def test_each_pair_has_at_most_one_relation(generated: World) -> None:
    pairs = [(r.a, r.b) for r in generated.relations]
    assert len(pairs) == len(set(pairs)) and all(a < b for a, b in pairs)


def test_a_world_with_a_border_has_a_war(generated: World) -> None:
    assert any(r.kind == "war" for r in generated.relations)


def test_a_war_is_forced_when_the_draw_gives_none() -> None:
    # Every pair draws "no relation", yet the longest border becomes a war.
    world = _run(_land([3, 3], ["major", "major"]), _config(none=1.0))
    assert [r.kind for r in world.relations] == ["war"]


def test_a_relation_names_a_reason_template() -> None:
    # The stage stores a raw template of the relation's kind; naming fills its tokens later.
    config = _config(war=1.0, rivalry=1.0, alliance=1.0, trade=1.0)
    world = _run(_land([3, 3, 3, 3], ["major"] * 4), config)
    assert world.relations and all(r.why in config.get(f"tables.reasons.{r.kind}.templates") for r in world.relations)


def test_far_apart_majors_may_pact_across_the_sea() -> None:
    # A and C do not touch; with only B between them and war drawn, the sea pact joins A and C with no border.
    world = _run(_land([2, 2, 2], ["major", "major", "major"]), _config())
    pacts = [r for r in world.relations if r.kind != "war"]
    assert [(r.a, r.b, r.border_km) for r in pacts] == [(0, 2, 0.0)]


def test_a_vassal_borders_count_for_its_overlord() -> None:
    # B is A's vassal, so A's war partner is C (B's neighbour): the pair is A-C, never B-C.
    config = _config()
    config.data["tables"]["realm_kinds"]["major"]["vassal_chance"] = 1.0
    world = _run(_land([6, 1, 3], ["major", "major", "major"]), config)
    assert [(r.a, r.b) for r in world.relations if r.kind == "war"] == [(0, 2)]


# --- fronts and claims ------------------------------------------------------------------------------------------------


def test_a_front_marks_both_sides_of_the_boundary() -> None:
    world = _run(_land([3, 3], ["major", "major"]), _config())
    assert np.flatnonzero(world.front.any(axis=0)).tolist() == [2, 3]


def test_a_lone_realm_has_no_front_and_no_relations() -> None:
    # Nothing borders it, so there is nothing to fight over or to trade with.
    world = _run(_land([6], ["major"]), _config())
    assert not world.front.any() and world.relations == []


def test_front_cells_belong_to_warring_powers(generated: World) -> None:
    tops = np.array([generated.top_realm(r.id) for r in generated.realms])
    warring = {i for r in generated.relations if r.kind == "war" for i in (r.a, r.b)}
    cells = tops[generated.realm_id[generated.front]]
    assert set(cells.tolist()) <= warring


def test_a_war_has_an_attacker_from_its_sides(generated: World) -> None:
    wars = [r for r in generated.relations if r.kind == "war"]
    assert all(r.attacker in (r.a, r.b) for r in wars)


def test_peace_has_no_attacker(generated: World) -> None:
    assert all(r.attacker == -1 and r.claim_poi == -1 for r in generated.relations if r.kind != "war")


def test_a_war_claims_a_town_of_the_defender(generated: World) -> None:
    tops = [generated.top_realm(r.id) for r in generated.realms]
    claims = [(r, generated.pois[r.claim_poi]) for r in generated.relations if r.kind == "war" and r.claim_poi >= 0]
    assert claims and all(
        poi.kind != "capital" and tops[poi.realm_id] == (r.b if r.attacker == r.a else r.a) for r, poi in claims
    )


def test_the_claimed_town_is_the_one_nearest_the_front() -> None:
    # Realm 1 holds a town at the boundary and one far away: the near one is claimed (when realm 1 defends).
    world = _land([4, 8], ["major", "major"])
    _town(world, "town", 1, 1)
    near = _town(world, "town", 5, 1)
    _town(world, "town", 11, 1)
    _run(world, _config())
    relation = world.relations[0]
    claimed_realm = world.pois[relation.claim_poi].realm_id
    assert (claimed_realm == 1 and relation.claim_poi == near) or (claimed_realm == 0 and relation.attacker == 1)


def test_a_capital_is_never_claimed() -> None:
    world = _land([4, 4], ["major", "major"])
    _town(world, "capital", 3, 1)
    _town(world, "capital", 4, 1)
    _run(world, _config())
    assert world.relations[0].claim_poi == -1


def test_running_twice_gives_the_same_relations() -> None:
    first = _run(_land([3, 3, 3], ["major", "major", "major"]), _config(war=1.0, trade=1.0))
    second = _run(_land([3, 3, 3], ["major", "major", "major"]), _config(war=1.0, trade=1.0))
    assert [(r.a, r.b, r.kind, r.why) for r in first.relations] == [(r.a, r.b, r.kind, r.why) for r in second.relations]


def test_front_cells_of_a_war_are_marked_on_the_front(generated: World) -> None:
    # front_cells names the cells a war puts on World.front: every one is marked.
    wars = [r for r in generated.relations if r.kind == "war"]
    cells = np.concatenate([diplomacy.front_cells(generated, r.a, r.b) for r in wars])
    assert cells.size and generated.front.reshape(-1)[cells].all()


def test_front_cells_of_all_wars_cover_the_front(generated: World) -> None:
    # Together the wars' cells are exactly the marked front.
    wars = [r for r in generated.relations if r.kind == "war"]
    cells = np.unique(np.concatenate([diplomacy.front_cells(generated, r.a, r.b) for r in wars]))
    assert cells.tolist() == np.flatnonzero(generated.front.reshape(-1)).tolist()


def test_front_cells_do_not_depend_on_the_pair_order(generated: World) -> None:
    war = next(r for r in generated.relations if r.kind == "war")
    assert (
        diplomacy.front_cells(generated, war.a, war.b).tolist()
        == diplomacy.front_cells(generated, war.b, war.a).tolist()
    )


# --- reasons name only what lies near the border ---------------------------------------------------------------------


def _war_with_reasons(templates: list[str]) -> tuple[World, Config]:
    config = _config()
    config.data["tables"]["reasons"]["war"]["templates"] = templates
    config.data["politics"]["reason_near_km"] = 100.0
    world = _land([3, 3], ["major", "major"])
    world.landmass_id[:] = 0
    return world, config


def _river_at(world: World, x: int) -> None:
    from biomegen.world.entities import GeoFeature, River

    world.rivers.append(River(id=0, path=[(x, y) for y in range(HEIGHT)]))
    world.features.append(GeoFeature(id=0, kind="river", anchor=(x, 0), ref=0, name="The Wend"))


def test_a_reason_naming_a_far_river_is_never_chosen() -> None:
    # The border runs 15 cells in; at 30 km a cell a river at column 0 is 450 km away, beyond the 100 km cap.
    config = _config()
    config.data["tables"]["reasons"]["war"]["templates"] = ["control of the {river}", "an assassinated envoy"]
    config.data["politics"]["reason_near_km"] = 100.0
    world = _land([15, 15], ["major", "major"])
    world.landmass_id[:] = 0
    _river_at(world, 0)
    assert _run(world, config).relations[0].why == "an assassinated envoy"


def test_a_reason_may_name_a_river_beside_the_border() -> None:
    world, config = _war_with_reasons(["control of the {river}"])
    _river_at(world, 3)
    relation = _run(world, config).relations[0]
    assert relation.why == "control of the {river}" and relation.places == {"river": 0}


def test_a_reason_with_no_place_token_records_no_place() -> None:
    world, config = _war_with_reasons(["an assassinated envoy"])
    _river_at(world, 3)
    assert _run(world, config).relations[0].places == {}


def test_when_no_template_qualifies_the_whole_list_stays() -> None:
    # Naming then uses the fallback words, so a world with no river near the border still gets a reason.
    world, config = _war_with_reasons(["control of the {river}"])
    assert _run(world, config).relations[0].why == "control of the {river}"


def test_every_named_place_of_a_generated_reason_lies_near_the_border(generated: World, cfg: Config) -> None:
    for relation in generated.relations:
        points = diplomacy._reason_points(generated, relation)
        for token, feature in relation.places.items():
            assert nearest_feature(generated, cfg, token, points) == feature
            assert generated.features[feature].name.removeprefix("The ") in relation.why

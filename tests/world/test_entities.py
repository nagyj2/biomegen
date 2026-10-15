"""Tests for the sparse political entities: realms, relations and the POI's realm link."""

from __future__ import annotations

from biomegen.world.entities import EVENT_KINDS, NO_LOCATION, POI, ChronicleEvent, FallenRealm, Realm, Relation


def test_realm_starts_independent_and_unnamed() -> None:
    # A fresh realm has no liege, no vassals and no names: later stages fill them in.
    realm = Realm(id=2, kind="tribal")
    assert (realm.liege, realm.vassals, realm.name, realm.seat_poi) == (-1, [], "", -1)


def test_realm_vassal_lists_are_not_shared() -> None:
    # The default vassal list is per instance.
    first, second = Realm(id=0, kind="major"), Realm(id=1, kind="major")
    first.vassals.append(1)
    assert second.vassals == []


def test_peace_relation_has_no_attacker() -> None:
    # Only a war names an attacker and a claimed town.
    relation = Relation(a=0, b=1, kind="trade")
    assert (relation.attacker, relation.claim_poi) == (-1, -1)


def test_poi_starts_in_no_realm() -> None:
    assert POI(kind="tower", x=0, y=0, interior_seed=1).realm_id == -1


def test_chronicle_event_starts_unlocated_and_unrendered() -> None:
    # A fresh event names no place and has no text: the history stage sets the template, naming the text.
    event = ChronicleEvent(id=0, year=10, kind="founding", template="{realm} is founded")
    assert (event.location, event.text, event.realm_ids) == (NO_LOCATION, "", [])


def test_chronicle_event_id_lists_are_not_shared() -> None:
    # The default id lists are per instance.
    first, second = ChronicleEvent(id=0, year=1, kind="war"), ChronicleEvent(id=1, year=1, kind="war")
    first.realm_ids.append(3)
    assert second.realm_ids == []


def test_fallen_realm_starts_unnamed() -> None:
    # Naming fills the culture and name of a fallen realm.
    fallen = FallenRealm(id=0, location=(4, 5), founded=100, fell=400)
    assert (fallen.name, fallen.culture) == ("", "")


def test_realm_and_settlement_start_undated() -> None:
    # Birth years default to 0 until the history stage dates them.
    assert (Realm(id=0, kind="major").founded, POI(kind="town", x=0, y=0, interior_seed=1).founded) == (0, 0)


def test_event_kinds_are_unique() -> None:
    assert len(set(EVENT_KINDS)) == len(EVENT_KINDS)


def test_poi_starts_standing_and_unlinked() -> None:
    # A new POI has not fallen, belongs to no event, holds no bandits and has no hook or purpose yet.
    poi = POI(kind="ruin", x=1, y=2, interior_seed=0)
    assert (poi.fell, poi.event_ids, poi.hook, poi.hook_refs, poi.bandit_strength, poi.purpose) == (
        None,
        [],
        "",
        [],
        0,
        "",
    )


def test_poi_link_lists_are_not_shared() -> None:
    first, second = POI(kind="ruin", x=1, y=2, interior_seed=0), POI(kind="ruin", x=3, y=4, interior_seed=0)
    first.event_ids.append(7)
    first.hook_refs.append((0, 1, "poi", 0))
    assert second.event_ids == [] and second.hook_refs == []


def test_a_civilized_poi_no_realm_holds_is_free() -> None:
    assert POI(kind="town", x=0, y=0, interior_seed=1, civilized=True, realm_id=-1).free


def test_a_held_settlement_is_not_free() -> None:
    assert not POI(kind="town", x=0, y=0, interior_seed=1, civilized=True, realm_id=2).free


def test_a_wild_poi_is_not_free() -> None:
    assert not POI(kind="tower", x=0, y=0, interior_seed=1, realm_id=-1).free

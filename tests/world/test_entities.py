"""Tests for the sparse political entities: realms, relations and the POI's realm link."""

from __future__ import annotations

from biomegen.world.entities import POI, Realm, Relation


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

"""The founding and settling events a secession step may add or change, shared with the history stage."""

from __future__ import annotations

from ...config.model import Config
from ...world.entities import NO_LOCATION, Realm
from ...world.world import World
from .ledger import Ledger
from .places import nearest_settlement


def add_founding(world: World, config: Config, seed: int, ledger: Ledger, realm: Realm) -> None:
    """Add the ``founding`` event of ``realm``: dated by the realm, tied to its seat, and tagged ``capital`` for one."""
    seat = realm.seat_poi
    poi = world.pois[seat] if seat >= 0 else None
    ledger.add(
        realm.founded,
        "founding",
        "founding",
        (realm.id,),
        seed,
        realm_ids=[realm.id],
        poi_ids=[seat] if poi else [],
        location=(poi.x, poi.y) if poi else NO_LOCATION,
        near_poi=nearest_settlement(world, config, poi.x, poi.y, (seat,)) if poi else -1,
        tags=(realm.kind, "capital") if poi and poi.kind == "capital" else (realm.kind,),
    )


def add_settling(world: World, config: Config, seed: int, ledger: Ledger, index: int, realm_id: int) -> None:
    """Add the ``settling`` event of the held settlement ``index``, settled by realm ``realm_id``."""
    poi = world.pois[index]
    ledger.add(
        poi.founded,
        "settling",
        "settling",
        (index,),
        seed,
        realm_ids=[realm_id],
        poi_ids=[index],
        location=(poi.x, poi.y),
        near_poi=nearest_settlement(world, config, poi.x, poi.y, (index,)),
        tags=(poi.kind,),
    )

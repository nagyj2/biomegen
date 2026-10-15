"""How plausible a secession is: the score the history stage rolls against, and a later simulation shares.

A secession is an offshoot (a realm leaves an older one), a clean split (an old realm ends in two) or a defection (a
settlement changes sides). Each is scored from 0 to 1 as the weighted mean of **terms**, each itself 0 to 1, weighted by
``tables.secession_terms`` (``data/secession.toml``); a term that does not apply to a form is left out of the mean:

- **proximity**: the two seats lie close (a shared border counts as close; ``history.secession.proximity_km``);
- **size**: the breakaway is small against its parent (full inside ``size_share``), or for a split the two halves are
  of one size;
- **age**: the parent is old at the time (full at ``history.secession.age_years``);
- **relation**: the present relation of the two sides (``tables.secession_relations``);
- **prosperity**: the breakaway has more people per km² than its parent (full at ``prosperity_ratio``);
- **leader**: the parent's ruler of that year trusts little and is aggressive (the ruler's traits);
- **strength**: the parent is weak at that moment, against the mean (``weak_strength``); a clean split has no living
  parent, so it leaves this out.

Every function is pure: it reads the world, the config and what it is given, and writes nothing, so generation and a
later simulation score from the same code. Generation uses the first three entry points (:func:`offshoot_score`,
:func:`split_score`, :func:`defection_score`), the simulation :func:`fracture_score`; :func:`relation_tag` words
a break.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config.model import Config
from ...world.entities import POI, Realm, Relation, Ruler
from ...world.world import World


def proximity_term(config: Config, km: float, bordering: bool) -> float:
    """Return 1 for sides that share a border, else how close ``km`` is against ``history.secession.proximity_km``."""
    if bordering:
        return 1.0
    return max(0.0, 1.0 - km / float(config.get("history.secession.proximity_km")))


def size_term(config: Config, share: float) -> float:
    """Return how well a breakaway of ``share`` of its parent's area fits: full in ``size_share``, none if equal."""
    low, high = (float(v) for v in config.get("history.secession.size_share"))
    if share < low:
        return max(0.0, share / low)
    if share <= high:
        return 1.0
    return max(0.0, 1.0 - (share - high) / (1.0 - high))


def balance_term(first_km2: float, second_km2: float) -> float:
    """Return how even two halves of a split are: the smaller area over the larger (1 when equal)."""
    larger = max(first_km2, second_km2)
    return min(first_km2, second_km2) / larger if larger > 0 else 0.0


def age_term(config: Config, years: float) -> float:
    """Return how old a parent is against ``history.secession.age_years`` (1 once it has reached it)."""
    return min(1.0, max(0.0, years / float(config.get("history.secession.age_years"))))


def relation_term(config: Config, kind: str | None) -> float:
    """Return the ``tables.secession_relations`` score of a relation kind (``None``: the sides have no relation)."""
    return float(config.get(f"tables.secession_relations.{kind or 'none'}.score"))


def prosperity_term(config: Config, ratio: float) -> float:
    """Return how much richer per km² a breakaway is than its parent: 0 at equal or less, 1 at ``prosperity_ratio``."""
    full = float(config.get("history.secession.prosperity_ratio"))
    return min(1.0, max(0.0, (ratio - 1.0) / (full - 1.0))) if full > 1.0 else float(ratio > 1.0)


def leader_term(ruler: Ruler | None) -> float | None:
    """Return how poor a keeper of a realm ``ruler`` is (little trust, much aggression), or ``None`` without one."""
    if ruler is None:
        return None
    return (1.0 - float(ruler.traits["trust"]) + float(ruler.traits["aggression"])) / 2.0


def strength_term(config: Config, ratio: float | None) -> float | None:
    """Return how weak a parent is: 1 at or below ``weak_strength`` of the mean strength, 0 at the mean or more.

    ``None`` (no strength known: a clean split, or a world with no timeline) leaves the term out.
    """
    if ratio is None:
        return None
    weak = float(config.get("history.secession.weak_strength"))
    return min(1.0, max(0.0, (1.0 - ratio) / (1.0 - weak))) if weak < 1.0 else float(ratio <= weak)


def combine(config: Config, terms: Mapping[str, float | None]) -> float:
    """Return the weighted mean of the terms that apply (a ``None`` term is left out), 0 when none does."""
    rows = config.get("tables.secession_terms")
    names = [name for name in sorted(terms) if terms[name] is not None]
    total = sum(float(rows[name]["weight"]) for name in names)
    if total <= 0.0:
        return 0.0
    return sum(float(rows[name]["weight"]) * float(terms[name]) for name in names) / total  # type: ignore[arg-type]


def relation_between(world: World, first: Realm, second: Realm) -> Relation | None:
    """Return the relation between the independent powers that ``first`` and ``second`` belong to, if they have one."""
    a, b = world.top_realm(first.id), world.top_realm(second.id)
    if a == b:
        return None
    pair = (min(a, b), max(a, b))
    return next((r for r in world.relations if (r.a, r.b) == pair), None)


def relation_tag(world: World, config: Config, first: Realm, second: Realm) -> str:
    """Return how a break between the two is worded, ``bitter`` or ``amicable``, from the relation between them."""
    relation = relation_between(world, first, second)
    return str(config.get(f"tables.secession_relations.{relation.kind if relation else 'none'}.tag"))


def _seat_km(world: World, first: Realm, second: Realm) -> float | None:
    """Return the km between two realms' seats, or ``None`` when either has no seat (a tribe)."""
    if first.seat_poi < 0 or second.seat_poi < 0:
        return None
    a, b = world.pois[first.seat_poi], world.pois[second.seat_poi]
    return world.scale.distance_km(a.x, a.y, b.x, b.y)


def _proximity(world: World, config: Config, first: Realm, second: Realm) -> float:
    relation = relation_between(world, first, second)
    km = _seat_km(world, first, second)
    return proximity_term(config, float("inf") if km is None else km, bool(relation and relation.border_km > 0.0))


def _density(realm: Realm) -> float:
    return realm.pop / realm.area_km2 if realm.area_km2 > 0 else 0.0


def offshoot_score(
    world: World,
    config: Config,
    breakaway: Realm,
    parent: Realm,
    year: int,
    strength_ratio: float | None = None,
) -> float:
    """Return how plausible it is that ``breakaway`` left ``parent`` in ``year``.

    ``strength_ratio`` is the parent's strength over the mean at that moment (``None`` leaves the term out).
    """
    relation = relation_between(world, breakaway, parent)
    return combine(
        config,
        {
            "proximity": _proximity(world, config, breakaway, parent),
            "size": size_term(config, breakaway.area_km2 / parent.area_km2 if parent.area_km2 > 0 else 1.0),
            "age": age_term(config, year - parent.founded),
            "relation": relation_term(config, relation.kind if relation else None),
            "prosperity": prosperity_term(config, _density(breakaway) / _density(parent) if _density(parent) else 1.0),
            "leader": leader_term(world.ruler_at(parent.id, year)),
            "strength": strength_term(config, strength_ratio),
        },
    )


def split_score(world: World, config: Config, first: Realm, second: Realm, year: int, founded: int) -> float:
    """Return how plausible it is that a realm founded in ``founded`` split in ``year`` into ``first`` and ``second``.

    There is no living parent, so the leader, prosperity and strength terms are left out; the size term is the balance
    of the two halves.
    """
    relation = relation_between(world, first, second)
    return combine(
        config,
        {
            "proximity": _proximity(world, config, first, second),
            "size": balance_term(first.area_km2, second.area_km2),
            "age": age_term(config, year - founded),
            "relation": relation_term(config, relation.kind if relation else None),
        },
    )


def defection_score(
    world: World,
    config: Config,
    town: POI,
    old_owner: Realm,
    new_owner: Realm,
    year: int,
    strength_ratio: float | None = None,
) -> float:
    """Return how plausible it is that ``town`` left ``old_owner`` for ``new_owner`` in ``year``.

    The size and prosperity terms are left out (a town has no area of its own); ``strength_ratio`` is the old owner's.
    """
    relation = relation_between(world, old_owner, new_owner)
    km = (
        world.scale.distance_km(town.x, town.y, world.pois[old_owner.seat_poi].x, world.pois[old_owner.seat_poi].y)
        if old_owner.seat_poi >= 0
        else float("inf")
    )
    return combine(
        config,
        {
            "proximity": proximity_term(config, km, bool(relation and relation.border_km > 0.0)),
            "age": age_term(config, year - old_owner.founded),
            "relation": relation_term(config, relation.kind if relation else None),
            "leader": leader_term(world.ruler_at(old_owner.id, year)),
            "strength": strength_term(config, strength_ratio),
        },
    )


def fracture_score(world: World, config: Config, realm: Realm, year: int, strength_ratio: float | None = None) -> float:
    """Return how plausible it is that ``realm`` fractures in ``year`` (the simulation scores each realm on its check).

    A large realm fractures more readily (the size term is its area against the mean realm's, capped at twice), as does
    an old one, one whose neighbours are hostile (its worst relation), one with a poor ruler and a weak one; proximity
    is how close its nearest neighbour's seat is, the neighbour a part might join. Prosperity is left to the simulation,
    which knows its settlements' wealth.
    """
    others = [r for r in world.realms if r.id != realm.id]
    mean_area = sum(r.area_km2 for r in world.realms) / len(world.realms) if world.realms else 0.0
    kms = [km for other in others if (km := _seat_km(world, realm, other)) is not None]
    relations = [relation_between(world, realm, other) for other in others]
    worst = max(
        (relation_term(config, r.kind) for r in relations if r is not None), default=relation_term(config, None)
    )
    return combine(
        config,
        {
            "proximity": proximity_term(config, min(kms, default=float("inf")), False),
            "size": min(1.0, realm.area_km2 / (2.0 * mean_area)) if mean_area > 0 else 0.0,
            "age": age_term(config, year - realm.founded),
            "relation": worst,
            "leader": leader_term(world.ruler_at(realm.id, year)),
            "strength": strength_term(config, strength_ratio),
        },
    )

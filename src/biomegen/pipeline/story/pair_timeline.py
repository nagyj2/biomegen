"""The history of one pair of independent powers, drawn backwards from today's relation (generation only).

A pair's history is a run of **episodes** (:mod:`.episodes` weighs and times them). It is drawn from the present back:
the present relation, if the pair has one, is the newest episode and keeps its kind (the map, fronts and watchtowers
never move); only its age is drawn, from ``tables.episode_kinds.<kind>.present_age``. Before it, with a chance that
falls with each one drawn, come quiet years (``history.episodes.gap_years``) and an older episode whose kind the ruler
traits of the time tilt. The run stops at the realms' founding, at ``max_per_pair`` episodes, or when the dice say so.

Each episode has its own stream, ``rng.derive(seed, "history", "episode", a, b, number)`` (``number`` counts back from
the present), with a fixed set of rolls drawn up front, so an episode never depends on how many others were drawn.
Nothing here writes the world: :mod:`.conflicts` turns the spans into events.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ...config.model import Config
from ...util import rng
from ...world.entities import Relation
from ...world.world import World
from . import episodes

Pair = tuple[int, int]
_ROLLS = 7  # more, gap, kind, length, side, deal, spare: always drawn, so the stream stays aligned


@dataclass(frozen=True)
class Deal:
    """How a trade is struck: its ``name`` (one of ``world.entities.DEALS``), the ``goods`` (a swap: what side ``a`` and
    side ``b`` give; a purchase: the good bought), the ``buyer`` realm id (-1 for a swap) and its ``volume``."""

    name: str
    goods: tuple[str, ...]
    buyer: int
    volume: str


@dataclass(frozen=True)
class Span:
    """One episode of a pair, from year ``start`` to ``end`` (the present for ``present``; a one-off purchase has
    ``end == start``). ``number`` counts back from the present (0 is the newest drawn). A war has an ``attacker``; a
    trade has its ``deal``."""

    kind: str
    start: int
    end: int
    present: bool
    number: int
    attacker: int = -1
    deal: Deal | None = None


def _traits(world: World, realm_id: int, year: int) -> Mapping[str, float]:
    """The personality of realm ``realm_id``'s ruler in ``year`` (empty when it has no rulers)."""
    ruler = world.ruler_at(realm_id, year)
    return ruler.traits if ruler is not None else {}


def _trade(
    config: Config,
    pair: Pair,
    supply: Mapping[int, Mapping[str, float]],
    traits: tuple[Mapping[str, float], Mapping[str, float]],
    roll: float,
    *,
    lasting: bool,
) -> Deal:
    """Draw the deal of a trade between ``pair``, its goods and its volume."""
    name = episodes.draw_deal(episodes.deal_weights(config, *traits, lasting=lasting), roll)
    goods = episodes.pact_goods(config, pair[0], pair[1], supply[pair[0]], supply[pair[1]], name)
    return Deal(
        name=name,
        goods=(goods.give, goods.get) if name == "swap" else (goods.give,),
        buyer=goods.buyer,
        volume=episodes.deal_volume(config, name, goods.match, *traits),
    )


def plan_pair(
    world: World,
    config: Config,
    seed: int,
    year: int,
    pair: Pair,
    present: Relation | None,
    border_km: float,
    strengths: tuple[float, float],
    supply: Mapping[int, Mapping[str, float]],
) -> list[Span]:
    """Return the episodes of ``pair`` (realm ids ``a < b``), oldest first, ending in ``present`` when it is a relation.

    ``year`` is the present, ``border_km`` the length of the pair's border (0 across the sea: no war), ``strengths`` the
    two realms' starting strengths (the gap that makes a war likelier) and ``supply`` each realm's
    :func:`~biomegen.world.resources.realm_supply`.
    """
    a, b = pair
    settings = config.get("history.episodes")
    gap_low, gap_high = (int(v) for v in settings["gap_years"])
    first = min(max(world.realms[a].founded, world.realms[b].founded) + int(config.get("history.min_gap_years")), year)
    pull = episodes.war_pull(config, border_km, *strengths)
    row_class = episodes.pair_class(world.realms[a].kind, world.realms[b].kind)
    spans: list[Span] = []
    wars = 0

    def rolls(number: int) -> list[float]:
        stream = rng.derive(seed, "history", "episode", a, b, number)
        return [stream.random() for _ in range(_ROLLS)]

    cursor = year
    if present is not None:
        draw = rolls(0)
        traits = (_traits(world, a, year), _traits(world, b, year))
        age = episodes.episode_years(config, present.kind, *traits, draw[3], present=True)
        deal = _trade(config, pair, supply, traits, draw[5], lasting=True) if present.kind == "trade" else None
        attacker = present.attacker if present.kind == "war" else -1
        spans.append(Span(present.kind, max(first, year - age), year, True, 0, attacker=attacker, deal=deal))
        cursor = spans[0].start
        wars += present.kind == "war"
    while len(spans) < int(settings["max_per_pair"]):
        number = len(spans)
        draw = rolls(number)
        earlier = number - (1 if present is not None else 0)  # the older episodes drawn so far
        chance = float(settings["first_chance"]) if earlier == 0 and present is None else float(settings["more_chance"])
        if draw[0] >= chance * float(settings["decay"]) ** earlier:
            break
        end = cursor - (gap_low + int(draw[1] * (gap_high - gap_low + 1)))
        if end <= first:
            break
        traits = (_traits(world, a, end), _traits(world, b, end))
        weights = episodes.kind_weights(
            config,
            row_class,
            *traits,
            bordering=border_km > 0.0,
            war_factor=pull,
            wars_left=int(settings["max_wars_per_pair"]) - wars,
        )
        kind = episodes.draw_kind(weights, draw[2])
        if kind is None:
            break
        deal = _trade(config, pair, supply, traits, draw[5], lasting=False) if kind == "trade" else None
        once = deal is not None and deal.name == "buy_once"
        start = end if once else max(first, end - episodes.episode_years(config, kind, *traits, draw[3]))
        attacker = (a if draw[4] < 0.5 else b) if kind == "war" else -1
        spans.append(Span(kind, start, end, False, number, attacker=attacker, deal=deal))
        cursor = start
        wars += kind == "war"
    return spans[::-1]

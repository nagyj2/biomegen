"""How a pair of powers' history is weighed, timed and sized: the pure functions generation and a simulation share.

A pair of independent powers goes through **episodes** (a war, a rivalry, an alliance, a trade), each with a kind, a
length and an end. Generation draws the past of every pair once, backwards from today's relation
(:mod:`.pair_timeline`); a later simulation (docs/simulation_plan.md 3.7, 3.6) starts episodes forward from the present
with the same functions, so the past and the future feel alike. Every function here reads the config and what it is
given and writes nothing: the caller draws the random numbers (``roll`` arguments, in [0, 1)) and keeps the order, so
no function depends on a stream's position.

- **Tilt.** Ruler personality (``world.entities.TRAITS``) tilts the odds, the length and the volume of an episode: the
  factor :func:`tilt` is ``1 + sum(coefficient * (the two rulers' mean of the trait - 0.5))`` for a row of
  ``data/episodes.toml``.
- **Kind.** :func:`kind_weights` and :func:`draw_kind` pick the kind of an earlier episode from the pair class's
  ``tables.relation_weights``, scaled and tilted by traits; a war's odds also grow with the border and the strength
  gap (:func:`war_pull`) and only a bordering pair fights.
- **Length.** :func:`episode_years` draws how long an episode lasted, or how old it is when it is today's relation.
- **Peace.** :func:`truce_terms` says whether a war ended in a truce or a peace; :func:`war_salience` whether a war is
  worth a major entry.
- **Deals.** :func:`deal_weights` and :func:`draw_deal` pick how a trade is struck (a swap of goods, or a purchase paid
  in money, once or on going), :func:`pact_goods` which goods change hands, from what each side's land has and lacks
  (``world/resources.py``), and :func:`deal_volume` how large the deal is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ...config.model import Config
from ...world.entities import DEALS, RELATION_KINDS
from ...world.resources import land_resources

Traits = Mapping[str, float]
Supply = Mapping[str, float]
NEUTRAL = 0.5  # a trait at this value neither raises nor lowers any odds


@dataclass(frozen=True)
class Goods:
    """What a trade moves. A swap: side ``a`` gives ``give`` and side ``b`` gives ``get``. A purchase: ``give`` is the
    good bought, ``get`` is empty and ``buyer`` is the realm id paying money for it (-1 for a swap). ``match`` is how
    well one side's surplus meets the other's lack, 0 to 1."""

    give: str
    get: str = ""
    buyer: int = -1
    match: float = 0.0


def tilt(config: Config, coefficients: Mapping[str, float], first: Traits, second: Traits) -> float:
    """Return ``1 + sum(coefficient * (mean of the two rulers' trait - 0.5))``, never below ``episodes.tilt_floor``.

    A trait a ruler lacks counts as neutral, so an empty ``first`` or ``second`` (a realm with no rulers) has no effect.
    """
    total = 1.0
    for name in sorted(coefficients):
        mean = (float(first.get(name, NEUTRAL)) + float(second.get(name, NEUTRAL))) / 2.0
        total += float(coefficients[name]) * (mean - NEUTRAL)
    return max(float(config.get("history.episodes.tilt_floor")), total)


def pair_class(first_kind: str, second_kind: str) -> str:
    """Return the ``tables.relation_weights`` row of a pair of realm kinds: both majors, or any other."""
    return "major_pair" if first_kind == "major" and second_kind == "major" else "other_pair"


def war_pull(config: Config, border_km: float, strength_a: float, strength_b: float) -> float:
    """Return the factor a pair's border and strength gap put on the odds of a war (1 for an average pair).

    The border term is the border over ``episodes.border_ref_km`` kept within ``episodes.border_range``; the gap term is
    ``1 + gap_weight`` times the larger side's lead over the pair's total strength (0 for equals, up to 1).
    """
    low, high = (float(v) for v in config.get("history.episodes.border_range"))
    border = min(high, max(low, border_km / float(config.get("history.episodes.border_ref_km"))))
    total = strength_a + strength_b
    lead = abs(strength_a - strength_b) / total if total > 0.0 else 0.0
    return border * (1.0 + float(config.get("history.episodes.gap_weight")) * lead)


def kind_weights(
    config: Config,
    pair_row: str,
    traits_a: Traits,
    traits_b: Traits,
    *,
    bordering: bool,
    war_factor: float = 1.0,
    wars_left: int = 1,
) -> dict[str, float]:
    """Return the weight of each relation kind for an earlier episode of a pair, in ``RELATION_KINDS`` order.

    The base is the kind's ``tables.relation_weights`` odds for the pair class ``pair_row``, times its
    ``weight_scale`` and its trait tilt. A war needs a border, ``wars_left`` above 0 and gets ``war_factor``
    (:func:`war_pull`).
    """
    base = config.get(f"tables.relation_weights.{pair_row}")
    weights: dict[str, float] = {}
    for kind in RELATION_KINDS:
        row = config.get(f"tables.episode_kinds.{kind}")
        weight = float(base[kind]) * float(row["weight_scale"]) * tilt(config, row["traits"], traits_a, traits_b)
        if kind == "war":
            weight = weight * war_factor if bordering and wars_left > 0 else 0.0
        weights[kind] = weight
    return weights


def _pick(weights: Mapping[str, float], roll: float) -> str | None:
    """Return the key whose share of the total weight holds ``roll`` (keys in the mapping's order), else ``None``."""
    total = sum(weights.values())
    if total <= 0.0:
        return None
    point, running = roll * total, 0.0
    last = None
    for key, weight in weights.items():
        if weight <= 0.0:
            continue
        running += weight
        last = key
        if point < running:
            return key
    return last


def draw_kind(weights: Mapping[str, float], roll: float) -> str | None:
    """Pick a relation kind from ``kind_weights`` by ``roll`` (``None`` when every weight is 0)."""
    return _pick(weights, roll)


def episode_years(
    config: Config, kind: str, traits_a: Traits, traits_b: Traits, roll: float, *, present: bool = False
) -> int:
    """Return how many years an episode of ``kind`` lasted (``present``: how old it is today), at least 1.

    The row's ``years`` (or ``present_age``) range is drawn with ``roll`` and tilted by the kind's ``length_traits``.
    """
    row = config.get(f"tables.episode_kinds.{kind}")
    low, high = (int(v) for v in row["present_age" if present else "years"])
    drawn = low + roll * (high - low + 1)
    return max(1, int(drawn * tilt(config, row["length_traits"], traits_a, traits_b)))


def truce_terms(config: Config, strength_a: float, strength_b: float) -> str:
    """Return ``truce`` when the two sides are near equal at the peace (the weaker at least ``episodes.truce_balance``
    of the stronger), else ``peace`` (one side won)."""
    stronger = max(strength_a, strength_b)
    if stronger <= 0.0:
        return "truce"
    return (
        "truce"
        if min(strength_a, strength_b) / stronger >= float(config.get("history.episodes.truce_balance"))
        else "peace"
    )


def war_salience(config: Config, kind_a: str, kind_b: str) -> str:
    """Return ``minor`` for a war between two small powers (both ``episodes.minor_war_kinds``), else the war row's."""
    small = set(config.get("history.episodes.minor_war_kinds"))
    if kind_a in small and kind_b in small:
        return "minor"
    return str(config.get("tables.episode_kinds.war.salience"))


def deal_weights(config: Config, traits_a: Traits, traits_b: Traits, *, lasting: bool) -> dict[str, float]:
    """Return the weight of each deal in ``DEALS`` order, tilted by traits; ``lasting`` leaves out one-off deals (a
    relation that is today's lasts, so it cannot be a one-off purchase)."""
    weights: dict[str, float] = {}
    for deal in DEALS:
        row = config.get(f"tables.deals.{deal}")
        weight = float(row["weight"]) * tilt(config, row["traits"], traits_a, traits_b)
        weights[deal] = weight if (row["ongoing"] or not lasting) else 0.0
    return weights


def draw_deal(weights: Mapping[str, float], roll: float) -> str:
    """Pick a deal from ``deal_weights`` by ``roll`` (``swap`` when every weight is 0)."""
    return _pick(weights, roll) or "swap"


def pact_goods(
    config: Config, first: int, second: int, supply_first: Supply, supply_second: Supply, deal: str
) -> Goods:
    """Return the goods of a trade between realm ``first`` and ``second`` from what each side's land yields.

    The surplus of one side over the other is the difference in the share of land that yields a resource
    (``world.resources.realm_supply``). A swap has the first side give the resource it is richest in and the second
    give the one it is richest in among the rest. A purchase is the one resource where the two differ most: the richer
    side sells and the poorer buys; with no difference at all the first side sells. Ties go to the resource whose name
    sorts first.
    """
    names = land_resources(config)
    lead = {name: float(supply_first.get(name, 0.0)) - float(supply_second.get(name, 0.0)) for name in names}
    if deal == "swap":
        give = max(names, key=lambda name: lead[name])
        get = max((name for name in names if name != give), key=lambda name: -lead[name])
        match = min(1.0, max(0.0, lead[give]) + max(0.0, -lead[get]))
        return Goods(give=give, get=get, match=match)
    good = max(names, key=lambda name: abs(lead[name]))
    buyer = second if lead[good] >= 0.0 else first
    return Goods(give=good, buyer=buyer, match=min(1.0, abs(lead[good])))


def deal_volume(config: Config, deal: str, match: float, traits_a: Traits, traits_b: Traits) -> str:
    """Return how large a deal is: ``small``, ``steady`` or ``large``, by its goods match tilted by the rulers' traits.

    The score is ``match`` times the deal's ``volume_traits`` tilt; under ``episodes.volume_cuts[0]`` it is small, from
    ``volume_cuts[1]`` large. A simulation turns the level into units with the resource's ``base_value``.
    """
    row = config.get(f"tables.deals.{deal}")
    score = match * tilt(config, row["volume_traits"], traits_a, traits_b)
    small, large = (float(v) for v in config.get("history.episodes.volume_cuts"))
    return "small" if score < small else "large" if score >= large else "steady"
